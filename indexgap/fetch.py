# -*- coding: utf-8 -*-
"""
Живой сайт → каталог, который читает `check`.

Не у всех есть сборка: аудит чужого сайта начинается с адреса, а не с файлов.
`fetch` скачивает страницы из sitemap и раскладывает их так, что `check`
видит каждую под тем адресом, с которого она пришла.

Сеть — только по необходимости и вежливо: тот же агент, что у любого запроса
пакета; robots.txt соблюдается; запросы на другой хост не уходят никогда, даже
по редиректу; потолок числа страниц снимается только явным `--all`.

Чего у сборки нет, а проверкам нужно, записывается рядом:

  * `X-Robots-Tag` — в `_headers` (формат Netlify), его читает `check`;
  * код ответа, редиректы, размер, тип — в `fetch.json`;
  * robots.txt и sitemap-файлы — как они лежат на сайте.

`--crawl` идёт ещё и по ссылкам: от главной и адресов sitemap, в ширину.
Так видно, каких страниц нет в sitemap и на какие из sitemap не ведёт ни
одна ссылка. `--render` сохраняет DOM, который нарисовал установленный
Chromium, а не исходный HTML; без браузера флаг — ошибка ввода.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, unquote, urldefrag, urljoin, urlsplit

from . import __version__, aeo, checks, core, doctor
from .core import SourceError
from .i18n import tr

DEFAULT_LIMIT = 500
MAX_JOBS = 16
TIMEOUT = 30
MAX_REDIRECTS = 5
# Страница больше этого не сохраняется: обрезанный HTML проверялся бы как целый.
MAX_PAGE_BYTES = 5 * 1024 * 1024
# Googlebot читает первые 2 МБ HTML; что дальше — для индекса не существует.
GOOGLEBOT_BYTES = 2 * 1024 * 1024
# Google читает первые 500 КиБ robots.txt.
MAX_ROBOTS_BYTES = 500 * 1024
# Имя, под которым пакет ищет свою группу в robots.txt; иначе действует `*`.
AGENT = "indexgap"
RESERVED = {"robots.txt", "_headers", core.FETCH_MANIFEST}

# Ссылки на такие файлы обход не открывает: это не страницы, а скачивать их
# ради «не HTML» в fetch.json — мегабайты чужого трафика.
_ASSET = re.compile(r"\.(?:png|jpe?g|gif|webp|avif|svg|ico|bmp|tiff?|mp4|webm|mov|avi|mp3|"
                    r"wav|ogg|m4a|zip|gz|tgz|rar|7z|tar|dmg|exe|pdf|docx?|xlsx?|pptx?|"
                    r"woff2?|ttf|otf|eot|css|m?js|json|xml|txt|csv|rss|atom)$", re.I)

# Браузер для --render. Ищется, а не ставится: пакет без зависимостей.
BROWSER_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                 "chrome", "msedge")
RENDER_TIMEOUT = 60
RENDER_BUDGET_MS = 5000
# Адрес, который уходит браузеру аргументом: только http(s) и печатный ASCII
# без пробела — после `_quote` иного и не бывает, а флагом он не станет.
_URL_ARG = re.compile(r"https?://[!-~]+", re.ASCII)

_SAFE = ":/?&=%#+,;@~-._!$'()*[]"



def _safe(text) -> str:
    """
    Строка с чужого сервера — в консоль и лог CI без управляющих знаков:
    `Location: /a\n::error::…` иначе стал бы командой GitHub Actions.
    """
    return core._CONTROL.sub(lambda m: "%%%02X" % ord(m.group()), str(text))

def _quote(url: str) -> str:
    """Пробел или кириллица в адресе роняли http.client раньше запроса."""
    return quote(urldefrag(url)[0], safe=_SAFE)


def _host(url: str) -> str:
    """Хост в той форме, в какой пакет их сравнивает: без www и порта по умолчанию."""
    return urlsplit(core.url_key(url)).netloc


def same_site(url: str, site: str) -> bool:
    return (urlsplit(url).scheme in ("http", "https")
            and bool(_host(url)) and _host(url) == _host(site))


def check_site(site: str) -> str:
    """Адрес сайта со схемой → его корень, `https://example.com/`."""
    site = (site or "").strip()
    parts = urlsplit(site)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        guess = site.split("//")[-1].strip("/") or "example.com"
        raise SourceError(tr("{a0} — так не годится: нужен полный адрес со схемой. "
                             "Попробуй: indexgap fetch https://{a1}", a0=site, a1=guess))
    return f"{parts.scheme}://{parts.netloc}/"


# ── адрес ↔ файл ─────────────────────────────────────────────────────────────

_SKIP_DIRS = core.ALWAYS_SKIP | core.OWN_DIRS


def _segments(url: str) -> tuple:
    """Раскодированные сегменты пути или ("", причина)."""
    parts = urlsplit(url)
    if parts.query:
        return None, tr("адрес с параметрами (?…) файлом не записать")
    raw = parts.path or "/"
    if "//" in raw:
        return None, tr("пустой сегмент пути (//)")
    segments = []
    for piece in raw.split("/")[1:]:
        # `%2F` внутри сегмента — это не разделитель каталогов, но файлом
        # стал бы именно он.
        if re.search(r"%2f|%5c|%00", piece, re.I):
            return None, tr("в сегменте пути закодирован / , \\ или NUL")
        name = unicodedata.normalize("NFC", unquote(piece))
        if name in (".", "..") or "\\" in name or "\x00" in name:
            return None, tr("сегмент пути . или .. — файлом не записать")
        if len(name.encode("utf-8")) > 200:
            return None, tr("сегмент пути длиннее 200 байт")
        segments.append(name)
    return segments, ""


def url_to_file(url: str) -> tuple:
    """
    Адрес страницы → (путь файла внутри каталога, "") или ("", причина).

        /            → index.html
        /a/b/        → a/b/index.html
        /a/b         → a/b.html          (так кладёт страницы Next.js-экспорт)
        /a/b.html    → a/b.html
        /p.php       → p.php.html        (`check` читает только .html)

    `load_pages` превращает эти файлы обратно в те же адреса по `fetch.json`;
    без него сходятся ключи (`url_key`). Путь, который `check` пропустил бы
    (`.git/`, `node_modules/`, `404.html`), файлом не становится: страница
    молча выпала бы из проверки.
    """
    segments, reason = _segments(url)
    if segments is None:
        return "", reason
    if not segments or segments[-1] == "":
        rel = "/".join(segments[:-1] + ["index.html"]) if segments else "index.html"
    elif segments[-1].lower().endswith((".html", ".htm")):
        rel = "/".join(segments)
    else:
        rel = "/".join(segments) + ".html"
    names = rel.split("/")
    for name in names[:-1]:
        if name.startswith(".") or name in _SKIP_DIRS:
            return "", tr("каталог {a0} check не читает", a0=name)
    if names[-1].startswith(".") or names[-1].lower() in core.OWN_FILES:
        return "", tr("файл {a0} check не читает", a0=names[-1])
    if core._ERROR_PAGE.search(rel):
        return "", tr("{a0}: check считает такой файл страницей ошибки", a0=rel)
    return rel, ""


def _sitemap_file(url: str) -> str:
    """Где лежит копия sitemap: по пути адреса, чтобы индекс нашёл дочерние."""
    segments, _ = _segments(url.split("?")[0])
    if not segments or not segments[-1]:
        return ""
    if any(s.startswith(".") for s in segments):
        return ""
    return "/".join(segments)


# ── сеть ─────────────────────────────────────────────────────────────────────

class _Stay(urllib.request.HTTPRedirectHandler):
    """Редирект не выполняется сам: куда идти, решает `_visit`."""

    def redirect_request(self, *args, **kwargs):
        return None


class _Pacer:
    """Пауза между запросами одного потока."""

    def __init__(self, delay: float):
        self.delay = max(0.0, float(delay or 0))
        self.local = threading.local()

    def wait(self):
        last = getattr(self.local, "last", None)
        if last is not None and self.delay:
            left = self.delay - (time.monotonic() - last)
            if left > 0:
                time.sleep(left)
        self.local.last = time.monotonic()


def _get(url: str, cap: int, pacer: _Pacer = None, timeout: int = TIMEOUT) -> dict:
    """
    Один запрос без следования редиректам.

    {"status", "headers", "body", "error", "too_big"}; `body` не больше `cap`.
    """
    if pacer:
        pacer.wait()
    opener = urllib.request.build_opener(_Stay)
    out = {"status": None, "headers": None, "body": b"", "error": "", "too_big": False}
    try:
        response = opener.open(core.request(url, headers={
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"}), timeout=timeout)
    except urllib.error.HTTPError as exc:
        out.update(status=exc.code, headers=exc.headers)
        exc.close()
        return out
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
        out["error"] = str(getattr(exc, "reason", "") or exc)
        return out
    try:
        with response:
            out.update(status=response.status, headers=response.headers)
            length = response.headers.get("Content-Length") or ""
            if length.isdigit() and int(length) > cap:
                out["too_big"] = True
                return out
            body = response.read(cap + 1)
    except (http.client.HTTPException, OSError, ValueError) as exc:
        out["error"] = str(exc)
        return out
    if len(body) > cap:
        out["too_big"] = True
        body = b""
    out["body"] = body
    return out


def _robots_path(url: str) -> str:
    parts = urlsplit(url)
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


class Crawl:
    """Состояние одного обхода: что куда записано, кто чей файл занял."""

    def __init__(self, site: str, out_dir: str, delay: float, follow: bool = False,
                 browser: str = "", no_sandbox: bool = False):
        self.site = site
        self.out = out_dir
        self.pacer = _Pacer(delay)
        self.follow = follow
        self.browser = browser
        self.no_sandbox = no_sandbox
        self.robots = {"found": False, "rules": {}, "sitemaps": []}
        self.lock = threading.Lock()
        # Имя файла в нижнем регистре → адрес: macOS и Windows не различают
        # `/About` и `/about`, и вторая страница молча затёрла бы первую.
        self.claims = {name: "" for name in RESERVED}
        self.sitemap_files = {}
        self.done = 0
        self.written = []

    # robots.txt ──────────────────────────────────────────────────────────────

    def read_robots(self) -> dict:
        url = urljoin(self.site, "/robots.txt")
        current, status = url, None
        for _ in range(MAX_REDIRECTS + 1):
            got = _get(current, MAX_ROBOTS_BYTES * 4, self.pacer)
            status = got["status"]
            location = got["headers"].get("Location") if got["headers"] is not None else None
            if status and 300 <= status < 400 and location:
                target = urljoin(current, location)
                if not same_site(target, self.site):
                    break
                current = target
                continue
            break
        info = {"url": url, "status": status, "final_url": current}
        if got["error"]:
            raise SourceError(tr("{a0} не читается: {a1} — обход не начат", a0=url,
                                 a1=got["error"]))
        if status and status >= 500:
            # Google в этом случае не обходит сайт вовсе — и пакет тоже.
            raise SourceError(tr("{a0} отдал {a1}: по правилам robots.txt это «не обходить» "
                                 "— обход не начат. Повтори позже", a0=url, a1=status))
        if status == 200:
            path = self._write("robots.txt", got["body"][:MAX_ROBOTS_BYTES])
            self.robots = aeo.read_robots(path)
            info["file"] = "robots.txt"
        # 4xx — robots.txt нет, и запретов тоже нет.
        return info

    def blocked(self, url: str) -> str:
        return aeo.blocking_rule(self.robots, _robots_path(url), AGENT)

    # sitemap ─────────────────────────────────────────────────────────────────

    def fetch_sitemap(self, source: str) -> bytes:
        """`fetcher` для doctor.read_sitemap: свой хост, копия на диск."""
        if not same_site(source, self.site):
            raise SourceError(tr("{a0}: sitemap на другом хосте — не скачивается", a0=source))
        current = _quote(source)
        for _ in range(MAX_REDIRECTS + 1):
            got = _get(current, core.MAX_INPUT_BYTES, self.pacer)
            location = got["headers"].get("Location") if got["headers"] is not None else None
            if got["status"] and 300 <= got["status"] < 400 and location:
                target = urljoin(current, location)
                if not same_site(target, self.site):
                    raise SourceError(tr("{a0} ведёт редиректом на другой хост: {a1}",
                                         a0=source, a1=target))
                current = _quote(target)
                continue
            break
        if got["error"]:
            raise SourceError(tr("{a0} не читается: {a1}", a0=source, a1=got["error"]))
        if got["too_big"]:
            raise SourceError(tr("{a0}: больше {a1} МБ — читать не стал", a0=source,
                                 a1=core.MAX_INPUT_BYTES // (1024 * 1024)))
        if got["status"] != 200:
            raise SourceError(tr("{a0} отдал {a1}", a0=source, a1=got["status"]))
        data = got["body"]
        rel = _sitemap_file(source)
        if rel:
            with self.lock:
                taken = self.claims.get(rel.lower())
                if taken is None:
                    self.claims[rel.lower()] = source
            if taken is None:
                # Копия как есть, со сжатием: локальное чтение узнаёт gzip по байтам.
                self._write(rel, data)
                self.sitemap_files[source] = rel
        if data[:2] == b"\x1f\x8b":
            try:
                data = core.gunzip(data)
            except SourceError as exc:
                raise SourceError(f"{source}: {exc}")
        return data

    # страницы ────────────────────────────────────────────────────────────────

    def _write(self, rel: str, data: bytes) -> str:
        path = os.path.join(self.out, *rel.split("/"))
        real = os.path.realpath(path)
        base = os.path.realpath(self.out)
        if not real.startswith(base + os.sep):
            raise OSError(tr("путь {a0} выходит за каталог", a0=rel))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        with self.lock:
            self.written.append(path)
        return path

    def undo(self, created: bool) -> None:
        """
        Обход не состоялся — убрать то, что он успел записать, и только это.
        Иначе повторный запуск упёрся бы в «каталог не пуст».
        """
        for path in self.written:
            try:
                os.remove(path)
            except OSError:
                pass
        for dirpath, _, _ in sorted(os.walk(self.out), key=lambda w: -len(w[0])):
            if dirpath != self.out or created:
                try:
                    os.rmdir(dirpath)
                except OSError:
                    pass

    def visit(self, url: str) -> dict:
        """Скачивает адрес, идёт по редиректам своего хоста, сохраняет HTML."""
        record = {"url": url, "status": None, "final_url": url, "bytes": 0,
                  "content_type": "", "file": None, "redirects": [],
                  "x_robots_tag": "", "over_2mb": False, "found_by": "sitemap",
                  "rendered": False, "js_shell": False}
        current = _quote(url)
        for hop in range(MAX_REDIRECTS + 1):
            got = _get(current, MAX_PAGE_BYTES, self.pacer)
            record.update(status=got["status"], final_url=current)
            if got["error"]:
                record["error"] = got["error"]
                return record
            headers = got["headers"]
            location = headers.get("Location") if headers is not None else None
            if not (300 <= got["status"] < 400 and location):
                break
            target = urljoin(current, location)
            record["redirects"].append({"url": current, "status": got["status"]})
            record["final_url"] = target
            if not same_site(target, self.site):
                record["note"] = tr("редирект на другой хост — не скачивался")
                return record
            if self.blocked(target):
                record["note"] = tr("редирект на адрес, закрытый robots.txt, — не скачивался")
                return record
            if hop == MAX_REDIRECTS:
                record["note"] = tr("больше {a0} редиректов подряд", a0=MAX_REDIRECTS)
                return record
            current = _quote(target)
        headers = got["headers"]
        record["content_type"] = headers.get("Content-Type", "") if headers is not None else ""
        if headers is not None and hasattr(headers, "get_all"):
            tags = [" ".join(v.split()) for v in headers.get_all("X-Robots-Tag") or ()]
            record["x_robots_tag"] = ", ".join(t for t in tags if t)
        if got["too_big"]:
            length = headers.get("Content-Length", "") if headers is not None else ""
            record["bytes"] = int(length) if length.isdigit() else 0
            record["over_2mb"] = True
            record["note"] = tr("больше {a0} МБ — не сохранялась", a0=MAX_PAGE_BYTES // (1024 * 1024))
            return record
        body = got["body"]
        record["bytes"] = len(body)
        record["over_2mb"] = len(body) > GOOGLEBOT_BYTES
        if record["status"] != 200:
            return record
        if not _is_html(record["content_type"], body):
            return record
        rel, reason = url_to_file(record["final_url"])
        if not rel:
            record["note"] = reason
            return record
        with self.lock:
            taken = self.claims.get(rel.lower())
            if taken is None:
                self.claims[rel.lower()] = record["final_url"]
        if taken is not None:
            if taken == record["final_url"]:
                record["same_as"] = taken
            else:
                record["note"] = tr("файл {a0} уже занят адресом {a1}", a0=rel, a1=taken or rel)
            return record
        data = _as_declared(body, record["content_type"])
        if self.browser:
            # Браузер запрашивает страницу ещё раз — пауза та же, что у запроса.
            self.pacer.wait()
            dom, error = render(self.browser, _quote(record["final_url"]), self.site,
                                self.no_sandbox)
            if dom is None:
                record["render_error"] = error
            else:
                data = dom
                record["rendered"] = True
                record["rendered_bytes"] = len(dom)
        try:
            path = self._write(rel, data)
        except OSError as exc:
            record["note"] = str(exc)
            return record
        record["file"] = rel
        try:
            page = core.load_page(path, self.out, self.site)
        except (SourceError, ValueError, RecursionError):
            return record
        record["js_shell"] = checks.is_shell(page)
        if self.follow:
            record["_links"] = _page_links(page.raw or "", record["final_url"], self.site)
        return record


def _is_html(content_type: str, body: bytes) -> bool:
    kind = (content_type or "").split(";")[0].strip().lower()
    if kind:
        return "html" in kind
    head = body[:512].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html"))


def _as_declared(body: bytes, content_type: str) -> bytes:
    """
    Кодировку, объявленную только заголовком, в файл не унести — и страница
    в cp1251 без <meta charset> читалась бы гаданием. Такой HTML
    перекодируется в UTF-8, как его и показал бы браузер.
    """
    found = re.search(r"charset\s*=\s*[\"']?([\w.:-]+)", content_type or "", re.I)
    if not found or core._declared_charset(body):
        return body
    name = found.group(1)
    if core.is_utf8(name) or any(body.startswith(bom) for bom, _ in core.BOMS):
        return body
    try:
        text = body.decode(name)
    except (LookupError, UnicodeDecodeError):
        return body
    return text.encode("utf-8")


def _page_links(raw: str, page_url: str, site: str) -> list:
    """Ссылки страницы на свой сайт: абсолютные, без #фрагмента, в порядке документа."""
    ex = core._Extractor()
    try:
        ex.feed(raw)
        ex.close()
    except (ValueError, AssertionError):
        pass
    base = page_url
    if ex.base:
        try:
            base = urljoin(page_url, ex.base)
        except ValueError:
            pass
    out = []
    for href in ex.hrefs:
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        try:
            absolute = urldefrag(urljoin(base, href))[0]
        except ValueError:
            continue
        if same_site(absolute, site):
            out.append(absolute)
    return out


# ── браузер для --render ─────────────────────────────────────────────────────

def _known_browser_paths() -> list:
    """Где браузер лежит, даже если его нет в PATH."""
    if sys.platform == "darwin":
        return ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    if os.name == "nt":
        found = []
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.environ.get(env)
            if root:
                found += [os.path.join(root, "Google", "Chrome", "Application", "chrome.exe"),
                          os.path.join(root, "Microsoft", "Edge", "Application", "msedge.exe")]
        return found
    return []


def find_browser(given: str = None) -> str:
    """Путь к Chromium-браузеру или SourceError с тем, что поставить."""
    if given:
        path = given if os.path.isfile(given) else shutil.which(given)
        if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
            raise SourceError(tr("--browser {a0}: такого исполняемого файла нет", a0=given))
        return os.path.abspath(path)
    for name in BROWSER_NAMES:
        path = shutil.which(name)
        if path:
            return path
    for path in _known_browser_paths():
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    raise SourceError(tr("--render нужен браузер семейства Chromium, а его нет: ни {a0} в PATH, "
                         "ни Google Chrome или Chromium на обычном месте. Поставь Google Chrome "
                         "или Chromium либо укажи путь: --browser /путь/к/chrome",
                         a0=", ".join(BROWSER_NAMES)))


_BATCH_URL = re.compile(r"https?://[A-Za-z0-9.:/_~\-]+", re.ASCII)


def _site_hosts(site: str) -> list:
    import ipaddress
    host = (urlsplit(site).hostname or "").lower()
    try:
        ipaddress.ip_address(host)
        return [host]                      # у IP-адреса нет www-двойника
    except ValueError:
        pass
    bare = host[4:] if host.startswith("www.") else host
    return sorted({host, bare, "www." + bare} - {"", "www."})


def browser_args(browser: str, url: str, profile: str = "", site: str = "",
                 no_sandbox: bool = False, proxy_port: int = 9, pins: dict = None) -> list:
    """
    Список аргументов, не строка: shell между пакетом и браузером нет.

    Страница сама тянет скрипты, шрифты и API — в том числе с чужих хостов,
    из внутренней сети, с loopback и с 169.254.169.254. Весь трафик браузера,
    loopback тоже (`<-loopback>`), идёт через прокси-шлюз пакета (`_Gate`),
    а тот соединяет только с хостом и портом сайта по адресу, разрешённому
    один раз: ни чужой хост, ни подмена DNS посреди обхода, ни соседний порт
    на своей машине недоступны. WebRTC мимо прокси не ходит.
    """
    args = [browser, "--headless=new", "--disable-gpu"]
    if no_sandbox:
        # Только по явной просьбе: песочница — главная защита от чужого JS.
        args.append("--no-sandbox")
    args += ["--no-first-run", "--no-default-browser-check"]
    hosts = _site_hosts(site or url)
    if hosts:
        args += ["--host-resolver-rules=MAP * ~NOTFOUND, "
                 + ", ".join(f"EXCLUDE {h}" for h in hosts),
                 f"--proxy-server=127.0.0.1:{proxy_port}",
                 "--proxy-bypass-list=<-loopback>",
                 "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]
    if profile:
        # Свой профиль на каждый вызов: открытый Chrome человека не трогается.
        args.append("--user-data-dir=" + profile)
    args += ["--user-agent=" + core.USER_AGENT, "--dump-dom",
             f"--virtual-time-budget={RENDER_BUDGET_MS}", url]
    return args


def _site_targets(site: str) -> dict:
    """
    (хост, порт) сайта → адрес, разрешённый здесь и сейчас. Имена с www и без,
    порт из адреса или по схеме. IP-адрес сайта остаётся как есть.
    """
    import ipaddress
    import socket
    parts = urlsplit(site)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    targets = {}
    for host in _site_hosts(site):
        try:
            ipaddress.ip_address(host)
            targets[(host, port)] = host
            continue
        except ValueError:
            pass
        try:
            info = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError:
            continue
        if info:
            targets[(host, port)] = info[0][4][0]
    return targets


class _Gate:
    """
    Прокси-шлюз для браузера на свободном порту 127.0.0.1. Пропускает только
    к сайту: CONNECT host:port и запросы `http://host:port/…`, где (host, port)
    — из `targets`, соединяясь по заранее разрешённому адресу. Всё остальное —
    соединение закрывается. Свой слушатель, а не «заведомо пустой» порт: на
    чужой машине на нём может сидеть что угодно.
    """

    MAX_HEAD = 64 * 1024

    def __init__(self, targets: dict):
        import socket
        self.targets = dict(targets)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(32)
        self.sock.settimeout(0.5)
        self.port = self.sock.getsockname()[1]
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.done.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _target(self, host: str, port: int):
        return self.targets.get(((host or "").lower().strip("[]"), port))

    def _serve(self, conn):
        import socket
        upstream = None
        try:
            conn.settimeout(30)
            head = b""
            while b"\r\n\r\n" not in head and len(head) < self.MAX_HEAD:
                chunk = conn.recv(8192)
                if not chunk:
                    return
                head += chunk
            line, _, rest = head.partition(b"\r\n")
            parts = line.split(b" ")
            if len(parts) != 3:
                return
            method, target, version = parts
            if method == b"CONNECT":
                host, _, port = target.decode("ascii", "replace").rpartition(":")
                address = self._target(host, int(port) if port.isdigit() else -1)
                if not address:
                    return
                upstream = socket.create_connection((address, int(port)), timeout=30)
                conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                leftover = head.split(b"\r\n\r\n", 1)[1]
                if leftover:
                    upstream.sendall(leftover)
            else:
                url = urlsplit(target.decode("ascii", "replace"))
                if url.scheme != "http":
                    return
                port = url.port or 80
                address = self._target(url.hostname, port)
                if not address:
                    return
                upstream = socket.create_connection((address, port), timeout=30)
                path = (url.path or "/") + (f"?{url.query}" if url.query else "")
                upstream.sendall(method + b" " + path.encode("ascii", "replace") + b" "
                                 + version + b"\r\n" + rest)
            self._pipe(conn, upstream)
        except (OSError, ValueError):
            return
        finally:
            for s in (conn, upstream):
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass

    @staticmethod
    def _pipe(a, b):
        """Байты в обе стороны, пока одна не закроется."""
        import select
        a.settimeout(None)
        b.settimeout(None)
        while True:
            ready, _, _ = select.select([a, b], [], [], 30)
            if not ready:
                return
            for src in ready:
                data = src.recv(65536)
                if not data:
                    return
                (b if src is a else a).sendall(data)

    def close(self):
        self.done.set()
        self.sock.close()
        self.thread.join(timeout=2)


def needs_no_sandbox() -> bool:
    """Chromium без песочницы не стартует под root — это контейнеры и CI на Linux."""
    return sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0


def _stop(proc) -> None:
    """Браузер не уложился: остановить его вместе с дочерними процессами."""
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.communicate(timeout=5)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


def render(browser: str, url: str, site: str, no_sandbox: bool = False) -> tuple:
    """
    (DOM в байтах, "") или (None, причина). Адрес проверяется до запуска:
    он пришёл из sitemap или ссылки чужого сервера. Браузер в `.bat`/`.cmd`
    запускает cmd, а он разбирает `& | ^ %` в аргументах — для него адрес
    только из букв, цифр и `.:/_~-`.
    """
    batch = browser.lower().endswith((".bat", ".cmd"))
    pattern = _BATCH_URL if batch else _URL_ARG
    if not pattern.fullmatch(url or "") or not same_site(url, site):
        return None, tr("адрес не http(s) на сайте {a0} или с пробелом — браузеру не "
                        "передаётся", a0=site)
    profile = tempfile.mkdtemp(prefix="indexgap-render-")
    extra = {} if os.name == "nt" else {"start_new_session": True}
    gate = _Gate(_site_targets(site))
    try:
        try:
            proc = subprocess.Popen(browser_args(browser, url, profile, site, no_sandbox,
                                                 gate.port),
                                    shell=False,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, **extra)
        except OSError as exc:
            return None, tr("браузер не запустился: {a0}", a0=exc)
        try:
            out, _ = proc.communicate(timeout=RENDER_TIMEOUT)
        except subprocess.TimeoutExpired:
            _stop(proc)
            return None, tr("браузер не уложился в {a0} с — остановлен", a0=RENDER_TIMEOUT)
    finally:
        gate.close()
        shutil.rmtree(profile, ignore_errors=True)
    if proc.returncode != 0:
        return None, tr("браузер завершился с кодом {a0}", a0=proc.returncode)
    if len(out) > MAX_PAGE_BYTES:
        return None, tr("отрисованный DOM больше {a0} МБ", a0=MAX_PAGE_BYTES // (1024 * 1024))
    head = out[:2048].lstrip().lower()
    if not head.startswith((b"<html", b"<!doctype")):
        return None, tr("браузер вернул не HTML")
    if not head.startswith(b"<!doctype"):
        # --dump-dom отдаёт documentElement без doctype.
        out = b"<!doctype html>\n" + out.lstrip()
    return out, ""


# ── обход ─────────────────────────────────────────────────────────────────────

def _empty_dir(path: str) -> None:
    if os.path.exists(path):
        if not os.path.isdir(path):
            raise SourceError(tr("--out-dir {a0} — это файл, а нужен каталог", a0=path))
        if os.listdir(path):
            raise SourceError(tr("--out-dir {a0} не пуст. Скачанное смешалось бы с тем, что там "
                                 "лежит, — укажи новый каталог или очисти этот", a0=path))
    os.makedirs(path, exist_ok=True)


def run(site: str, out_dir: str, sitemaps=None, limit: int = None, all_pages: bool = False,
        delay: float = 0.5, jobs: int = 4, progress=None, follow: bool = False,
        render_pages: bool = False, browser: str = None, no_sandbox: bool = False) -> dict:
    """Весь обход. Возвращает сводку; манифест и файлы уже на диске."""
    site = check_site(site)
    if all_pages and limit not in (None, 0):
        raise SourceError(tr("--all и --limit {a0} противоречат друг другу: либо потолок, "
                             "либо все страницы", a0=limit))
    if limit is None:
        limit = 0 if all_pages else DEFAULT_LIMIT
    if limit < 0:
        raise SourceError(tr("--limit не может быть отрицательным"))
    if limit == 0 and not all_pages:
        raise SourceError(tr("--limit 0 значит «без потолка» — это только вместе с --all"))
    if not 1 <= jobs <= MAX_JOBS:
        raise SourceError(tr("--jobs от 1 до {a0}", a0=MAX_JOBS))
    if delay < 0:
        raise SourceError(tr("--delay не может быть отрицательным"))
    if browser and not render_pages:
        raise SourceError(tr("--browser задаёт браузер для --render — без --render он не нужен"))
    if no_sandbox and not render_pages:
        raise SourceError(tr("--browser-no-sandbox относится к --render — без него не нужен"))
    found_browser = find_browser(browser) if render_pages else ""
    if render_pages and needs_no_sandbox() and not no_sandbox:
        raise SourceError(tr(
            "под root на Linux Chromium без песочницы не запускается, а песочница — главная "
            "защита от чужого JavaScript. Запусти fetch не под root или, если понимаешь "
            "риск (контейнер, который выбрасывается после прогона), добавь "
            "--browser-no-sandbox"))
    given = list(sitemaps or ())
    for source in given:
        if not source.startswith(("http://", "https://")):
            raise SourceError(tr("--sitemap {a0}: нужен адрес на сайте; файл с диска "
                                 "передай сразу в check", a0=source))
        if not same_site(source, site):
            raise SourceError(tr("--sitemap {a0}: другой хост, чем {a1} — туда fetch "
                                 "не ходит", a0=source, a1=site))
    created = not os.path.exists(out_dir)
    _empty_dir(out_dir)
    crawl = Crawl(site, out_dir, delay, follow=follow, browser=found_browser,
                  no_sandbox=no_sandbox)
    try:
        return _crawl(crawl, given, limit, jobs, progress)
    except SourceError:
        crawl.undo(created)
        raise


def _fetch_all(crawl: Crawl, urls: list, jobs: int, progress, total: int) -> list:
    """Адреса параллельно; записи — в том порядке, в каком адреса пришли."""
    def one(url):
        record = crawl.visit(url)
        with crawl.lock:
            crawl.done += 1
            done = crawl.done
        if progress and done % 50 == 0 and done < total:
            progress(done, total)
        return record

    pool = ThreadPoolExecutor(max_workers=jobs)
    try:
        futures = [pool.submit(one, url) for url in urls]
        records = [future.result() for future in futures]
    except KeyboardInterrupt:
        # Без отмены Ctrl-C ждал бы, пока скачается вся очередь.
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown()
    return records


def _follow(crawl: Crawl, candidates: list, limit: int, jobs: int, progress,
            skipped: list) -> dict:
    """
    Обход в ширину: главная и sitemap, потом их ссылки, потом ссылки ссылок.
    Очередь разбирается слоями, и каждый слой — в порядке постановки, поэтому
    порядок записей не зависит от того, какой поток ответил первым.
    """
    site = crawl.site
    sitemap_keys = {core.url_key(u) for u in candidates}
    queued, pending = set(), []
    blocked = {core.url_key(u) for u in skipped}
    with_query = set()

    def enqueue(url, how, parent):
        key = core.url_key(url)
        if key not in queued:
            queued.add(key)
            pending.append((url, how, parent))

    if crawl.blocked(site):
        if core.url_key(site) not in blocked:
            skipped.append(site)
    else:
        enqueue(site, "start", None)
    for url in candidates:
        enqueue(url, "sitemap", None)

    records, linked = [], set()
    while pending and (limit == 0 or len(records) < limit):
        room = len(pending) if limit == 0 else limit - len(records)
        batch, pending = pending[:room], pending[room:]
        got = _fetch_all(crawl, [u for u, _, _ in batch], jobs, progress,
                         len(records) + len(batch) + len(pending))
        for (url, how, parent), record in zip(batch, got):
            record["found_by"] = how
            if parent:
                record["linked_from"] = parent
            records.append(record)
            own = {core.url_key(url), core.url_key(record["final_url"])}
            queued.update(own)
            for link in record.pop("_links", ()):
                key = core.url_key(link)
                if key in own:
                    continue
                linked.add(key)
                if key in queued or key in blocked or key in with_query:
                    continue
                parts = urlsplit(link)
                # Параметры дают бесконечные страницы фильтров и календарей;
                # адрес с ними обходится, только если он есть в sitemap.
                if parts.query:
                    with_query.add(key)
                elif _ASSET.search(parts.path):
                    queued.add(key)
                elif crawl.blocked(link):
                    blocked.add(key)
                    skipped.append(link)
                else:
                    enqueue(link, "link", record["final_url"])

    # Ссылка на адрес с редиректом — это ссылка и на то, куда он ведёт.
    for record in records:
        if core.url_key(record["url"]) in linked:
            linked.add(core.url_key(record["final_url"]))
    for record in records:
        if (core.url_key(record["url"]) in sitemap_keys
                or core.url_key(record["final_url"]) in sitemap_keys):
            record["found_by"] = "sitemap"
        elif record["found_by"] == "start" and core.url_key(record["url"]) in linked:
            record["found_by"] = "link"
    home = core.url_key(site)
    link_only = [r["url"] for r in records if r["file"] and r["found_by"] != "sitemap"]
    orphans = [u for u in candidates
               if core.url_key(u) not in linked and core.url_key(u) != home]
    return {"records": records, "over_limit": len(pending),
            "link_only": link_only if candidates else [],
            "orphan_candidates": orphans, "skipped_query": len(with_query)}


def _crawl(crawl: Crawl, given: list, limit: int, jobs: int, progress) -> dict:
    site = crawl.site
    robots_info = crawl.read_robots()
    notes = []
    if not given:
        declared = crawl.robots.get("sitemaps") or []
        own = [s for s in declared if same_site(s, site)]
        for other in declared:
            if other not in own:
                notes.append(tr("robots.txt объявляет sitemap на другом хосте — не скачивался: "
                                "{a0}", a0=other))
        given = own or [urljoin(site, "/sitemap.xml")]
    found = doctor.read_sitemaps(given, fetcher=crawl.fetch_sitemap)
    if not found["urls"]:
        reason = (found["errors"] or [", ".join(given)])[0]
        if not crawl.follow:
            raise SourceError(tr("sitemap не прочитан: {a0}", a0=reason))
        notes.append(tr("sitemap не прочитан: {a0} — обход только по ссылкам от главной",
                        a0=reason))
    else:
        notes += [tr("sitemap прочитан не целиком: {a0}", a0=e) for e in found["errors"]]

    candidates, other_host, skipped = [], [], []
    seen = set()
    for url in found["urls"]:
        if url in seen:
            continue
        seen.add(url)
        if not same_site(url, site):
            other_host.append(url)
        elif crawl.blocked(url):
            skipped.append(url)
        else:
            candidates.append(url)
    links = {"link_only": [], "orphan_candidates": [], "skipped_query": 0}
    if crawl.follow:
        links = _follow(crawl, candidates, limit, jobs, progress, skipped)
        records, over_limit = links.pop("records"), links.pop("over_limit")
    else:
        chosen = candidates if limit == 0 else candidates[:limit]
        over_limit = len(candidates) - len(chosen)
        records = _fetch_all(crawl, chosen, jobs, progress, len(chosen))

    headers = [(urlsplit(r["final_url"]).path or "/", r["x_robots_tag"])
               for r in records if r["file"] and r["x_robots_tag"]]
    if headers:
        crawl._write("_headers", "".join(
            f"{path}\n  X-Robots-Tag: {value}\n" for path, value in headers).encode("utf-8"))
    root_sitemaps = [crawl.sitemap_files[s] for s in given if s in crawl.sitemap_files]
    manifest = {
        "generator": core.FETCH_GENERATOR,
        "version": __version__,
        "site": site,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "limit": limit,
        "crawl": crawl.follow,
        # Только имя: полный путь к браузеру — это путь на машине человека.
        "render": {"browser": os.path.basename(crawl.browser)} if crawl.browser else None,
        "robots": robots_info,
        "sitemaps": [{"url": url, "file": rel} for url, rel in crawl.sitemap_files.items()],
        "root_sitemaps": root_sitemaps,
        "sitemap_urls": len(seen),
        "other_host": other_host,
        "skipped_robots": skipped,
        "over_limit": over_limit,
        "js_shells": sum(1 for r in records if r["js_shell"]),
        **links,
        "notes": notes,
        "pages": records,
    }
    crawl._write(core.FETCH_MANIFEST, json.dumps(manifest, ensure_ascii=False,
                                                 indent=1).encode("utf-8"))
    return manifest


# Для cmd и PowerShell — белый список, а не чёрный: PowerShell считает
# кавычками и «умные» “ ” ‘ ’, а `$` в регулярке совпадает перед `\n`.
_NT_PLAIN = re.compile(r"[A-Za-z0-9_\-.:\\/~@+=,]+", re.ASCII)
_NT_QUOTED = re.compile(r"[A-Za-z0-9_\-.:\\/~@+=, ]+", re.ASCII)


def _nt_arg(arg: str, trusted: bool = False) -> str:
    """
    Аргумент для cmd и PowerShell: как есть, в двойных кавычках или никак.
    Каталог задал сам человек (`trusted`) — он может быть и кириллическим;
    имя sitemap пришло с сервера и проходит только по белому списку.
    """
    if _NT_PLAIN.fullmatch(arg):
        return arg
    if _NT_QUOTED.fullmatch(arg) or (trusted and not re.search(r'["\r\n]', arg)):
        return f'"{arg}"'
    return ""


def next_command(out_dir: str, manifest: dict) -> str:
    """
    Команда, которую человек скопирует в терминал. Имя sitemap пришло с
    чужого сервера: `/a&calc.xml` в команде для cmd стал бы второй командой.
    На POSIX это закрывает shlex.quote; в Windows одинарных кавычек нет,
    поэтому аргумент со знаками, которые раскрываются и в двойных кавычках,
    в команду не попадает вовсе — check найдёт sitemap и без него.
    """
    if os.name != "nt":
        parts = ["indexgap", "check", out_dir, "--site", manifest["site"]]
        for rel in manifest.get("root_sitemaps") or ():
            parts += ["--sitemap", os.path.join(out_dir, *rel.split("/"))]
        return " ".join(shlex.quote(p) for p in parts)
    words = ["indexgap", "check", _nt_arg(out_dir, trusted=True) or tr("<каталог>"),
             "--site", _nt_arg(manifest["site"], trusted=True)]
    for rel in manifest.get("root_sitemaps") or ():
        # Проверяется именно часть с сервера; каталог задал сам человек.
        if _NT_QUOTED.fullmatch(rel):
            quoted = _nt_arg(os.path.join(out_dir, *rel.split("/")), trusted=True)
            if quoted:
                words += ["--sitemap", quoted]
    return " ".join(words)


def _print_links(manifest: dict, records: list) -> None:
    """Что дал обход по ссылкам сверх sitemap."""
    link_only = manifest.get("link_only") or []
    if link_only:
        print(tr("  найдены только по ссылкам: {a0} — их нет в sitemap", a0=len(link_only)))
        for url in link_only[:5]:
            print(f"      {_safe(url)}")
    orphans = manifest.get("orphan_candidates") or []
    if orphans:
        line = tr("  в sitemap, но на них не ведёт ни одной ссылки: {a0} — кандидаты в сироты",
                  a0=len(orphans))
        if manifest.get("over_limit"):
            line += tr(" (обход неполный — часть ссылок не прочитана)")
        print(line)
        for url in orphans[:5]:
            print(f"      {_safe(url)}")
    broken = [r for r in records if r.get("found_by") == "link"
              and r["status"] and r["status"] >= 400]
    if broken:
        print(tr("  битые ссылки: {a0} — адрес по ссылке отвечает ошибкой", a0=len(broken)))
        for r in broken[:5]:
            print(f"      {_safe(r['url'])} ({r['status']}) ← {_safe(r.get('linked_from', ''))}")
    if manifest.get("skipped_query"):
        print(tr("  ссылки с параметрами (?…) не обходились: {a0}", a0=manifest["skipped_query"]))


def print_summary(out_dir: str, manifest: dict) -> int:
    """Сводка обхода. Код возврата: 1, если проверять нечего."""
    records = manifest["pages"]
    saved = [r for r in records if r["file"]]
    statuses = Counter(r["status"] for r in records
                       if r["status"] and r["status"] >= 400)
    no_answer = [r for r in records if r["status"] is None]
    redirected = [r for r in records if r["redirects"]]
    not_html = [r for r in records if r["status"] == 200 and not r["file"]
                and not r.get("same_as") and not r.get("note")
                and not _is_html(r["content_type"], b"")]
    unsaved = [r for r in records if r.get("note") and r["status"] == 200 and not r["file"]]
    for note in manifest.get("notes") or ():
        print(f"  ! {_safe(note)}")
    print(tr("Адресов в sitemap: {a0} (sitemap-файлов: {a1})", a0=manifest["sitemap_urls"],
             a1=len(manifest["sitemaps"])))
    if manifest["other_host"]:
        print(tr("  другой хост: {a0} — не скачивались", a0=len(manifest["other_host"])))
    if manifest["skipped_robots"]:
        print(tr("  закрыто robots.txt: {a0} — не скачивались", a0=len(manifest["skipped_robots"])))
    if manifest["over_limit"]:
        print(tr("  сверх --limit {a0}: {a1} — не скачивались (поднять: --limit N или "
                 "--limit 0 --all)", a0=manifest["limit"], a1=manifest["over_limit"]))
    print(tr("Запрошено: {a0}   Сохранено страниц: {a1}   С редиректом: {a2}",
             a0=len(records), a1=len(saved), a2=len(redirected)))
    if statuses:
        print(tr("  ответы с ошибкой: {a0}", a0=", ".join(
            f"{code} ×{n}" for code, n in sorted(statuses.items()))))
    if no_answer:
        print(tr("  без ответа (таймаут, обрыв): {a0}", a0=len(no_answer)))
    if not_html:
        print(tr("  не HTML — записаны в fetch.json, страницами не сохранены: {a0}",
                 a0=len(not_html)))
    over = [r for r in records if r["over_2mb"]]
    if over:
        print(tr("  больше 2 МБ: {a0} — Googlebot читает только первые 2 МБ HTML", a0=len(over)))
        for r in over[:5]:
            print(f"      {_safe(r['final_url'])}")
    if unsaved:
        print(tr("  ответ 200, но не сохранены: {a0}", a0=len(unsaved)))
        for r in unsaved[:5]:
            print(f"      {_safe(r['final_url'])} — {_safe(r['note'])}")
    if manifest.get("crawl"):
        _print_links(manifest, records)
    if manifest.get("render"):
        rendered = [r for r in saved if r.get("rendered")]
        failed = [r for r in saved if r.get("render_error")]
        print(tr("Отрисовано браузером: {a0} из {a1}", a0=len(rendered), a1=len(saved)))
        if failed:
            print(tr("  не отрисованы — сохранён исходный HTML: {a0}", a0=len(failed)))
            for r in failed[:5]:
                print(f"      {_safe(r['final_url'])} — {_safe(r['render_error'])}")
    elif manifest.get("js_shells"):
        print(tr("{a0} страниц(ы) похожи на пустой JS-каркас: текст рисует JavaScript, "
                 "и check его не увидит. Повтори с --render", a0=manifest["js_shells"]))
    print(tr("Записано: {a0}", a0=os.path.join(out_dir, core.FETCH_MANIFEST)))
    if not saved:
        print(tr("Ни одной страницы не сохранено — проверять нечего."))
        return 1
    print(tr("Дальше:"))
    print("  " + _safe(next_command(out_dir, manifest)))
    return 0
