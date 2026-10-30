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
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shlex
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, unquote, urldefrag, urljoin, urlsplit

from . import __version__, aeo, core, doctor
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

    def __init__(self, site: str, out_dir: str, delay: float):
        self.site = site
        self.out = out_dir
        self.pacer = _Pacer(delay)
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
                  "x_robots_tag": "", "over_2mb": False}
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
        try:
            self._write(rel, _as_declared(body, record["content_type"]))
        except OSError as exc:
            record["note"] = str(exc)
            return record
        record["file"] = rel
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
        delay: float = 0.5, jobs: int = 4, progress=None) -> dict:
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
    crawl = Crawl(site, out_dir, delay)
    try:
        return _crawl(crawl, given, limit, jobs, progress)
    except SourceError:
        crawl.undo(created)
        raise


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
        raise SourceError(tr("sitemap не прочитан: {a0}",
                             a0=(found["errors"] or [", ".join(given)])[0]))
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
    chosen = candidates if limit == 0 else candidates[:limit]
    over_limit = len(candidates) - len(chosen)

    def one(url):
        record = crawl.visit(url)
        with crawl.lock:
            crawl.done += 1
            done = crawl.done
        if progress and done % 50 == 0 and done < len(chosen):
            progress(done, len(chosen))
        return record

    pool = ThreadPoolExecutor(max_workers=jobs)
    try:
        futures = [pool.submit(one, url) for url in chosen]
        records = [future.result() for future in futures]
    except KeyboardInterrupt:
        # Без отмены Ctrl-C ждал бы, пока скачается вся очередь.
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown()

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
        "robots": robots_info,
        "sitemaps": [{"url": url, "file": rel} for url, rel in crawl.sitemap_files.items()],
        "root_sitemaps": root_sitemaps,
        "sitemap_urls": len(seen),
        "other_host": other_host,
        "skipped_robots": skipped,
        "over_limit": over_limit,
        "notes": notes,
        "pages": records,
    }
    crawl._write(core.FETCH_MANIFEST, json.dumps(manifest, ensure_ascii=False,
                                                 indent=1).encode("utf-8"))
    return manifest


def next_command(out_dir: str, manifest: dict) -> str:
    parts = ["indexgap", "check", out_dir, "--site", manifest["site"]]
    for rel in manifest.get("root_sitemaps") or ():
        parts += ["--sitemap", os.path.join(out_dir, *rel.split("/"))]
    return " ".join(shlex.quote(p) for p in parts)


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
    print(tr("Записано: {a0}", a0=os.path.join(out_dir, core.FETCH_MANIFEST)))
    if not saved:
        print(tr("Ни одной страницы не сохранено — проверять нечего."))
        return 1
    print(tr("Дальше:"))
    print("  " + _safe(next_command(out_dir, manifest)))
    return 0
