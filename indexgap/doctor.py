# -*- coding: utf-8 -*-
"""
Сверка трёх множеств — ответ на вопрос «конвейер отработал, а трафика нет, почему».

    сгенерировано  →  попало в sitemap  →  попало в индекс  →  даёт показы

Каждый переход теряет страницы, и потери на разных переходах лечатся по-разному.
Без этой воронки причина не видна: в интерфейсе Search Console страницы просто
«обнаружены, но не проиндексированы», без объяснения.

Данные берутся из выгрузок, а не из API: никаких ключей и подписок. Панель
вебмастера — прямой источник, но её нет не у всех, поэтому читаются и выгрузки
из Ahrefs, Semrush, Screaming Frog, Sitebulb, GA4, Matomo и других — в CSV,
XLSX, JSON или просто списком адресов. Что каждый источник доказывает, а что
нет, разбирает `sources.py`, и подпись шага воронки меняется вместе
с источником: «хотя бы в одном индексе» и «известно Ahrefs» — разные строки.

Три вещи, исправленные после аудита:

  * **сравнение по ключу URL.** Search Console экспортирует кириллические
    адреса в процент-кодировании, и раньше ни один из них не сходился
    с адресом страницы: воронка показывала «в индексе 0» на живом сайте;
  * **никакого молчаливого нуля.** Нечитаемый sitemap рисовал «потеряно всё»,
    а неопознанная колонка URL просто убирала раздел индексации из отчёта.
    Теперь и то и другое — явное сообщение;
  * **экспорт «Страницы» из Search Console — это отчёт о показах**, а не
    об индексации. Страница в индексе без показов туда не попадает, и на новом
    сайте воронка систематически завышает потери. Об этом сказано вслух.
"""

from __future__ import annotations

import csv
import io
import os
import re
from collections import Counter
import urllib.error
import urllib.request
from xml.etree import ElementTree

from . import sources
from .core import read_text, url_key, SourceError
from .i18n import tr

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def _keys(urls) -> set:
    return {url_key(u) for u in urls if u}


# Сколько sitemap-файлов читается за один прогон. Индекс с чужого сервера
# решает, сколько запросов сделает пакет; без потолка один адрес превращался
# в девятьсот запросов, а на глубине три — в десятки тысяч.
MAX_SITEMAPS = 200


def _host(url: str) -> str:
    from urllib.parse import urlsplit
    host = (urlsplit(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def _fetch_sitemap(source: str) -> bytes:
    """Байты sitemap с диска или по сети. Любая беда — SourceError словами."""
    import http.client
    from . import core
    if source.startswith(("http://", "https://")):
        from urllib.parse import quote
        # Пробел или кириллица в адресе роняли http.client раньше запроса.
        url = quote(source, safe=":/?&=%#+,;@~-._!$'()*[]")
        try:
            with urllib.request.urlopen(core.request(url), timeout=30) as resp:
                data = resp.read(core.MAX_INPUT_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise SourceError(tr("{a0} отдал {a1}", a0=source, a1=exc.code))
        except (urllib.error.URLError, http.client.HTTPException,
                OSError, ValueError) as exc:
            raise SourceError(tr("{a0} не читается: {a1}", a0=source, a1=exc))
    else:
        if not os.path.exists(source):
            raise SourceError(tr("файл {a0} не найден", a0=source))
        # Каталог, именованный канал или /dev/zero файлом не считаются:
        # чтение из них либо падает, либо не кончается.
        if not os.path.isfile(source):
            raise SourceError(tr("{a0} — не обычный файл", a0=source))
        if core.too_big(os.path.getsize(source)):
            raise SourceError(tr("{a0}: больше {a1} МБ — читать не стал", a0=source,
                                 a1=core.MAX_INPUT_BYTES // (1024 * 1024)))
        try:
            with open(source, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            raise SourceError(tr("{a0} не читается: {a1}", a0=source, a1=exc))
    if core.too_big(len(data)):
        raise SourceError(tr("{a0}: больше {a1} МБ — читать не стал", a0=source,
                             a1=core.MAX_INPUT_BYTES // (1024 * 1024)))
    if data[:2] == b"\x1f\x8b":
        try:
            data = core.gunzip(data)
        except SourceError as exc:
            raise SourceError(f"{source}: {exc}")
    return data


def _child_sitemap(source: str, loc: str) -> tuple:
    """
    Куда идти за дочерним файлом индекса: (источник, ошибка).

    Индекс не выбирает, что пакету читать. Индекс из сети ведёт только на свой
    же хост и только по http(s): иначе чужой sitemap называл дочерним локальный
    путь, и тот читался, или адрес во внутренней сети, и туда уходил запрос.
    Индекс с диска ищет дочерние файлы рядом с собой — по пути из адреса
    (`/en/sitemap.xml` → `en/sitemap.xml`), потом по имени — и не выходит за
    свой каталог.
    """
    from urllib.parse import unquote, urlsplit
    remote = loc.startswith(("http://", "https://"))
    if source.startswith(("http://", "https://")):
        if not remote:
            return "", tr("{a0}: дочерний адрес не http(s), не читается", a0=loc)
        if _host(loc) != _host(source):
            return "", tr("{a0}: дочерний sitemap на другом хосте не читается — "
                          "если он ваш, передайте его отдельным --sitemap", a0=loc)
        return loc, ""
    base = os.path.realpath(os.path.dirname(os.path.abspath(source)))
    me = os.path.realpath(source)
    path = unquote(urlsplit(loc).path if remote else loc).lstrip("/")
    for candidate in (os.path.join(base, path), os.path.join(base, os.path.basename(path))):
        real = os.path.realpath(candidate)
        inside = real == base or real.startswith(base + os.sep)
        if inside and real != me and os.path.isfile(real):
            return real, ""
    if remote:
        return loc, ""
    return "", tr("{a0}: дочерний файл не найден рядом с индексом", a0=loc)


def read_sitemap(source: str, _depth: int = 0, _seen: set = None) -> dict:
    """
    Читает sitemap с диска или по URL, разворачивает sitemap-index.

    Возвращает {"urls": [...], "error": "..."} — раньше при любой ошибке
    возвращался пустой список, и опечатка в пути выглядела как «сайт
    не попал в sitemap целиком».
    """
    from .core import parse_xml
    if _depth > 3:
        return {"urls": [], "error": tr("слишком глубокая вложенность sitemap-индексов")}
    _seen = set() if _seen is None else _seen
    key = source if source.startswith(("http://", "https://")) else os.path.realpath(source)
    # Петля — это ошибка, и молчать о ней нельзя: индекс, сославшийся на себя,
    # давал ноль адресов без единого слова, и воронка сообщала, что из sitemap
    # выпал весь сайт.
    if key in _seen:
        return {"urls": [], "error": tr("{a0}: индекс ссылается сам на себя", a0=source)}
    if len(_seen) >= MAX_SITEMAPS:
        return {"urls": [], "error": tr(
            "больше {a0} sitemap-файлов за один прогон — остальные не читались",
            a0=MAX_SITEMAPS)}
    _seen.add(key)
    try:
        root = parse_xml(_fetch_sitemap(source))
    except SourceError as exc:
        text = str(exc)
        return {"urls": [], "error": text if source in text else f"{source}: {text}"}

    tag = root.tag.rsplit("}", 1)[-1]
    if tag == "sitemapindex":
        urls, errors = [], []
        for sm in [e for e in root
                   if e.tag.rsplit("}", 1)[-1] == "sitemap"]:
            loc = next((c.text for c in sm
                        if c.tag.rsplit("}", 1)[-1] == "loc" and c.text), "")
            if not loc:
                continue
            child, problem = _child_sitemap(source, loc.strip())
            if child:
                result = read_sitemap(child, _depth + 1, _seen)
                urls.extend(result["urls"])
                problem = result["error"]
            if problem and problem not in errors:
                errors.append(problem)
            if len(_seen) >= MAX_SITEMAPS and problem:
                break
        if not urls and not errors:
            errors.append(tr("{a0}: индекс не дал ни одного адреса", a0=source))
        return {"urls": urls, "error": "; ".join(errors[:5])}

    # Только <url>/<loc>: у <image:loc> и <video:loc> то же имя, и 831
    # картинка каталога виз засчитывалась страницами sitemap.
    urls = [el.text.strip() for url in root
            if url.tag.rsplit("}", 1)[-1] == "url"
            for el in url
            if el.text and el.tag.rsplit("}", 1)[-1] == "loc"]
    if not urls:
        return {"urls": [], "error": tr("{a0}: в файле нет ни одного <loc>", a0=source)}
    return {"urls": urls, "error": ""}


URL_COLUMN_HINTS = sources.URL_COLUMN_HINTS


def read_sitemaps(sources) -> dict:
    """
    Несколько sitemap-файлов сразу: объединённый список адресов и ошибки по каждому.

    robots.txt на живом сайте объявлял три файла, а принимался один: один давал
    13 адресов, все три — 94, и шаг «в sitemap» занижался всемеро. Сломанный
    файл не прячет остальные — его ошибка называется отдельно.
    """
    if isinstance(sources, str):
        sources = [sources]
    urls, seen, errors = [], set(), []
    for source in sources or ():
        result = read_sitemap(source)
        if result.get("error"):
            errors.append(f"{source}: {result['error']}")
        for url in result.get("urls") or ():
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return {"urls": urls, "errors": errors}


def undeclared_sitemaps(robots_path: str, given) -> list:
    """
    Sitemap-файлы, которые robots.txt объявляет, а сверке не передали.

    Переданный файл узнаётся и по полному адресу, и по имени: скачанная копия
    `sitemap-landings.xml` — тот же файл, что объявлен по адресу.
    """
    if not robots_path:
        return []
    from .aeo import read_robots
    declared = (read_robots(robots_path) or {}).get("sitemaps") or []
    if isinstance(given, str):
        given = [given]
    def name(value):
        return os.path.basename(str(value).split("?")[0].rstrip("/")).lower()
    full = {str(g).rstrip("/") for g in given or ()}
    names = {name(g) for g in given or ()}
    return [s for s in declared
            if s.rstrip("/") not in full and name(s) not in names]


# Файлы, а не страницы: картинка в веб-выдаче — не потерянная страница.
_FILE = re.compile(r"\.(?:webp|png|jpe?g|gif|svg|avif|ico|pdf|zip|mp4|webm|mp3|"
                   r"css|js|json|xml|txt|woff2?)$", re.I)


def foreign_urls(funnel_result: dict, site: str = "") -> dict:
    """
    То, что поисковик знает, а среди страниц сайта нет, — по смыслу.

    Раньше это только считалось. На rumors.app среди таких адресов были
    тестовый стенд и внутренний GitLab — самое важное в выгрузке, и оно не
    доходило до человека. Чужие хосты, файлы и пропавшие страницы требуют
    разного: закрыть, ничего не делать, перенаправить.
    """
    def host(key):
        return key.lstrip("/").split("/", 1)[0].lower()

    def bare(value):
        return value[4:] if value.startswith("www.") else value

    home = bare(host(url_key(site))) if site else ""
    other, files, missing, by_host = [], [], [], {}
    for key in funnel_result.get("indexed_unknown") or ():
        where = bare(host(key))
        path = key.lstrip("/").partition("/")[2]
        if home and where != home:
            other.append(key)
            by_host[where] = by_host.get(where, 0) + 1
        elif _FILE.search(path.split("?")[0]):
            files.append(key)
        else:
            missing.append(key)
    return {"other_hosts": sorted(other), "files": sorted(files),
            "missing": sorted(missing), "by_host": dict(sorted(by_host.items())),
            "exported": dict(funnel_result.get("exported") or {})}


def _probe(url: str, timeout: int = 10) -> tuple:
    """
    (код ответа, заголовки) одного адреса — без следования редиректам.

    Следуй он за 301, перенаправленная страница выглядела бы живой: вернулся
    бы 200 конечного адреса. Представляется именем пакета, как любой его запрос.
    """
    import urllib.error
    from .core import request

    class _Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    def headers_of(message) -> dict:
        out = dict(message or {})
        # Заголовок может прийти дважды, а dict оставляет один: сервер слал
        # `nofollow` и отдельно `noindex`, и хост считался открытым.
        every = (message.get_all("X-Robots-Tag")
                 if hasattr(message, "get_all") else None)
        if every:
            out["X-Robots-Tag"] = ", ".join(every)
        return out

    opener = urllib.request.build_opener(_Stay)
    try:
        response = opener.open(request(url), timeout=timeout)
        headers = headers_of(response.headers)
        # Хост закрывают и тегом в странице. Хватит начала: <meta robots> в <head>.
        if "html" in str(headers.get("Content-Type", "")).lower():
            try:
                headers["_body"] = response.read(65536).decode("utf-8", "replace")
            except Exception:
                pass
        return response.status, headers
    except urllib.error.HTTPError as error:
        return error.code, headers_of(error.headers)
    except Exception:
        return None, {}


# Чьё правило считается: общее или адресованное поисковику.
_SEARCH_BOTS = ("googlebot", "bingbot", "yandex", "yandexbot", "duckduckbot",
                "slurp", "baiduspider", "applebot")
_META_ROBOTS = re.compile(
    r"<meta\b[^>]{0,300}?\bname\s*=\s*[\"']?(?:robots|googlebot)[\"']?[^>]{0,300}>", re.I)
_META_CONTENT = re.compile(r"\bcontent\s*=\s*[\"']([^\"']{0,200})[\"']", re.I)


def _closed_by_robots(header: str, body: str = "") -> bool:
    """
    Закрыта ли страница от индекса: `noindex` или `none`, в заголовке или в теге.

    Правило с именем бота (`otherbot: noindex`) закрывает только от него —
    общим оно считается лишь для поисковиков.
    """
    for part in str(header or "").split(","):
        agent, _, rule = part.strip().lower().rpartition(":")
        if agent and agent.strip() not in _SEARCH_BOTS:
            continue
        if rule.strip() in ("noindex", "none"):
            return True
    for tag in _META_ROBOTS.findall(body or ""):
        content = _META_CONTENT.search(tag)
        if content and {"noindex", "none"} & {
                t.strip().lower() for t in content.group(1).split(",")}:
            return True
    return False


def verify_live(foreign: dict, limit: int = 50, timeout: int = 10) -> dict:
    """
    Что из «поисковик знает, а на сайте нет» ещё требует действий.

    Выгрузка показывает прошлое: на eventiq.io четыре «пропавшие» страницы из
    пяти уже отдавали 301, на rumors.app шесть чужих хостов из семи уже были
    закрыты noindex. Сделанное отделяется от несделанного по живому ответу.

    Пропавшая страница в порядке, если отдаёт 3xx, 404 или 410; живой ответ 200
    значит, что на сайте она есть, а в файлах нет — сборка устарела. Чужой хост
    в порядке, если закрыт `X-Robots-Tag: noindex`, стоит за входом (401/403)
    или исчез. Недоступный адрес не записывается в сделанное.
    """
    from urllib.parse import quote, urljoin, urlsplit, urlunsplit
    done, todo, unknown, details = [], [], [], {}
    exported = foreign.get("exported") or {}
    items = ([(k, "host") for k in foreign.get("other_hosts") or ()]
             + [(k, "page") for k in foreign.get("missing") or ()])

    def address(key):
        # Спрашивается адрес из выгрузки, а не ключ: у ключа нет слэша, `.html`
        # и `www`, и живая страница отвечала на него 301 или 404.
        url = exported.get(key) or ("https:" + key if key.startswith("//") else key)
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc,
                           quote(parts.path, safe="/%:@!$&'()*+,;=~-._"),
                           quote(parts.query, safe="=&%:@!$'()*+,;/?~-._"), ""))

    def lower(headers):
        return {str(k).lower(): str(v) for k, v in (headers or {}).items()}

    for key, kind in items[:limit]:
        url = address(key)
        status, headers = _probe(url, timeout=timeout)
        lowered = lower(headers)
        stuck = False
        if kind == "host":
            # Редирект внутри хоста ничего не закрывает: корень GitLab отвечает
            # 302 на страницу входа, а та — 200 без noindex. Идём по цепочке и
            # судим по последнему ответу. Редирект на другой хост — хост выведен.
            home_host = urlsplit(url).hostname
            for _ in range(5):
                if not (status and 300 <= status < 400):
                    break
                if not lowered.get("location"):
                    stuck = True
                    break
                target = urljoin(url, lowered["location"])
                if urlsplit(target).hostname != home_host:
                    break
                url = target
                status, headers = _probe(url, timeout=timeout)
                lowered = lower(headers)
            else:
                # Пять переходов и всё ещё редирект внутри хоста — петля.
                stuck = bool(status and 300 <= status < 400)
        info = {"key": key, "kind": kind, "status": status, "url": url,
                "location": lowered.get("location", ""),
                "robots": lowered.get("x-robots-tag", "")}
        details[key] = info
        # Нет ответа, сервер занят или просит подождать, цепочка не кончилась —
        # это «не знаю», а не «в порядке» и не «открыт».
        if status is None or status == 429 or status >= 500 or stuck:
            unknown.append(key)
            continue
        closed = _closed_by_robots(info["robots"], lowered.get("_body", ""))
        if kind == "page":
            ok = 300 <= status < 400 or status in (404, 410) or closed
            if not ok and status != 200:
                unknown.append(key)
                continue
        else:
            # Сюда 3xx доходит только как уход на другой хост.
            ok = (closed or status in (401, 403, 404, 410) or 300 <= status < 400)
            if not ok and status != 200:
                unknown.append(key)
                continue
        (done if ok else todo).append(key if ok else info)
    return {"done": done, "todo": todo, "unknown": unknown, "details": details,
            "checked": min(len(items), limit), "total": len(items)}


def _read_rows(csv_path: str) -> tuple:
    """CSV, XLSX, JSON, NDJSON, XML или список адресов — всё через `sources`."""
    return sources.read_table(csv_path)


def read_indexed_header(csv_path: str) -> list:
    """Заголовки экспорта — нужны, чтобы понять, чья это выгрузка."""
    try:
        rows, _ = _read_rows(csv_path)
    except SourceError:
        return []
    return rows[0] if rows else []


def read_indexed(csv_path: str, site: str = "", index_status: bool = False) -> dict:
    """
    Выгрузка чего угодно, где есть адреса страниц: панель вебмастера, Ahrefs,
    Semrush, Screaming Frog, GA4, Matomo, просто список.

    Колонка с адресом ищется по заголовку, а если заголовки непонятные —
    по содержимому первой строки. Формат у всех разный, адрес есть у всех.

    Отдельно про относительные пути: GA4 и Matomo выгружают `/guide/visa/`,
    а не полный адрес. Без `site` такая выгрузка читалась как пустая, и отчёт
    уверенно сообщал «в индексе ноль» — худший вид ошибки. Теперь путь
    достраивается до адреса, а если `site` не передан, об этом говорится вслух.
    """
    rows, encoding = _read_rows(csv_path)
    if not rows:
        raise SourceError(tr("{a0}: файл пустой.", a0=csv_path))

    col, start = _url_column(rows)
    if col is None:
        raise SourceError(
            tr("{a0}: не нашёл колонку с адресами страниц.\n    Заголовки файла: ", a0=csv_path) + ", ".join(str(c) for c in rows[0][:8]) + tr("\n    Нужен экспорт, где есть столбец с адресами (в Search Console — «Страницы», не «Запросы»)."))

    # Статус читается только у панели вебмастера: `status: ok` в произвольном
    # списке — чьё угодно поле, а не слово поисковика.
    status_col = _status_column(rows, start) if index_status else None
    base = (site or "").rstrip("/")
    out, seen, relative, skipped, excluded = [], set(), 0, 0, {}
    for row in rows[start:]:
        if col >= len(row):
            continue
        value = str(row[col]).strip().strip('"')
        if not value:
            continue
        status = (str(row[status_col]).strip()
                  if status_col is not None and status_col < len(row) else "")
        if status_col is not None and not _is_indexed_status(status):
            if value.startswith("/") and base:
                value = base + value
            if value.startswith(("http://", "https://")):
                excluded[value] = status or tr("статус не указан")
            continue
        if value.startswith("/"):
            relative += 1
            if not base:
                skipped += 1
                continue
            value = base + value
        elif not value.startswith(("http://", "https://")):
            continue
        if value not in seen:
            seen.add(value)
            out.append(value)

    notes = []
    if relative and base:
        notes.append(tr("{a0}: {a1} адресов были относительными путями — достроены до {a2}/…", a0=os.path.basename(csv_path), a1=relative, a2=base))
    if skipped:
        notes.append(tr("{a0}: {a1} строк содержат пути вида /guide/… без домена, а --site не задан — они пропущены. Передай --site, чтобы их учесть.", a0=os.path.basename(csv_path), a1=skipped))
    if not out and not excluded:
        raise SourceError(
            tr("{a0}: колонка «{a1}» нашлась, но ни одного адреса в ней нет.", a0=csv_path, a1=rows[0][col] if col < len(rows[0]) else col)
            + (tr("\n    В файле только относительные пути — передай --site.")
               if relative else ""))
    return {"urls": out, "encoding": encoding, "notes": notes, "excluded": excluded}


def _looks_like_address(value) -> bool:
    return str(value or "").strip().strip('"').startswith(("http://", "https://", "/"))


def _url_column(rows: list) -> tuple:
    """
    (номер столбца с адресами, с какой строки начинаются данные).

    Столбец выбирается по содержимому, а заголовок только разрешает спор.
    Search Console переводит заголовок на язык панели («Die häufigsten
    Seiten», «上位のページ»), и поиск по словам отвергал немецкую, испанскую
    и японскую выгрузки, а у Plausible выбирал `pageviews`, потому что в нём
    есть слово page.
    """
    sample = rows[1:51] or rows[:1]
    width = max((len(r) for r in rows[:51]), default=0)
    counts = [sum(1 for r in sample if i < len(r) and _looks_like_address(r[i]))
              for i in range(width)]
    best = max(counts, default=0)
    hinted = sources.guess_column(rows[0], URL_COLUMN_HINTS)
    if best == 0:
        # Данных нет или в них нет адресов — остаётся только заголовок.
        if hinted >= 0 and not _looks_like_address(rows[0][hinted]):
            return hinted, 1
        col = next((i for i, c in enumerate(rows[0]) if _looks_like_address(c)), None)
        return col, 0
    col = counts.index(best)
    if hinted >= 0 and hinted < width and counts[hinted] * 2 >= best:
        col = hinted
    # Первая строка — заголовок, только если в выбранном столбце у неё не адрес:
    # список без заголовка, начинавшийся с `/locations/berlin/`, терял первую
    # страницу, потому что в ней есть слово loc.
    start = 0 if col < len(rows[0]) and _looks_like_address(rows[0][col]) else 1
    return col, start


# Столбцы, где поисковик сам говорит, в индексе ли страница.
_STATUS_HEADERS = ("coverage state", "coverage", "verdict", "index status",
                   "indexing status", "indexing state", "status", "статус",
                   "состояние", "состояние индексации")
_INDEXED = re.compile(
    r"(?<!not )(?<!не )\b(indexed|в поиске|в индексе|проиндексирован\w*|pass|valid)\b",
    re.I)
_NOT_INDEXED = re.compile(
    r"not indexed|not in index|unknown to|excluded|исключ|не проиндексир|не в поиске|"
    r"не в индексе|currently not|blocked|заблокир|duplicate|дубл|малоцен|"
    r"redirect|редирект|soft 404|not found|не найден|noindex|error|ошибк|fail",
    re.I)


def _status_column(rows: list, start: int):
    """Номер столбца со статусом индексации — или None, если такого нет."""
    if start == 0 or not rows:
        return None
    for i, cell in enumerate(rows[0]):
        if str(cell or "").strip().lower() not in _STATUS_HEADERS:
            continue
        values = [str(r[i]).strip() for r in rows[1:51] if i < len(r) and str(r[i]).strip()]
        # «Status: 200» — код ответа сервера, а не слово поисковика.
        if values and not all(v.isdigit() for v in values):
            return i
    return None


def _is_indexed_status(status: str) -> bool:
    """
    В индексе ли страница, по слову самого поисковика.

    «Submitted» из журнала отправки, «URL is unknown to Google», «Исключена:
    дубль» — всё это строки с адресом, и раньше каждая засчитывалась как
    страница в индексе. Засчитывается только то, что сказано прямо.
    """
    if not status or _NOT_INDEXED.search(status):
        return False
    return bool(_INDEXED.search(status))


def read_citations(csv_path: str, site: str = "") -> dict:
    """
    Выгрузка Bing Webmaster Tools → AI Performance → Pages: {адрес: цитирований}.

    Формат снят с живого кабинета: `"Page","Citations"`, каждое поле в кавычках,
    конец строки `\r\n`. Число нужно целиком, а не только адрес: «процитирована
    1 866 раз» и «один раз» — разные страницы.

    У той же панели есть вторая выгрузка — по запросам (`Grounding Query`). Адресов
    в ней нет. Прочитанная молча, она дала бы «ничего не цитируется», поэтому её
    отвергаем с подсказкой, какой файл нужен.
    """
    rows, _ = _read_rows(csv_path)
    if not rows:
        raise SourceError(tr("{a0}: файл пустой.", a0=csv_path))
    header = [str(h or "").strip().lower() for h in rows[0]]
    if "grounding query" in header and not any(
            h in ("page", "url", "address") for h in header):
        raise SourceError(tr(
            "{a0}: это выгрузка запросов (Grounding Queries) — адресов страниц в "
            "ней нет. В Bing Webmaster Tools → AI Performance переключись на "
            "вкладку Pages и выгрузи её.", a0=csv_path))

    url_col = sources.guess_column(rows[0], URL_COLUMN_HINTS)
    count_col = next((i for i, h in enumerate(header) if h == "citations"), -1)
    if url_col < 0 or count_col < 0:
        raise SourceError(tr(
            "{a0}: нужны столбцы с адресом и с числом цитирований. Заголовки файла: {a1}",
            a0=csv_path, a1=", ".join(str(c) for c in rows[0][:8])))

    base = (site or "").rstrip("/")
    out = {}
    for row in rows[1:]:
        if max(url_col, count_col) >= len(row):
            continue
        url = str(row[url_col]).strip().strip('"')
        if url.startswith("/") and base:
            url = base + url
        if not url.startswith(("http://", "https://")):
            continue
        raw = str(row[count_col]).strip().replace(",", "").replace(" ", "")
        try:
            count = int(float(raw))
        except ValueError:
            continue
        out[url] = out.get(url, 0) + count
    if not out:
        raise SourceError(tr("{a0}: ни одной строки с адресом и числом цитирований.",
                             a0=csv_path))
    return out


def read_sources(specs: list, site: str = "") -> dict:
    """
    Читает несколько выгрузок сразу и помнит, чем каждая является.

    Спека — либо `имя=путь`, либо просто путь. Имя может быть поисковиком
    (`google=`, `bing=`) или инструментом (`ahrefs=`, `screamingfrog=`, `ga4=`):
    от этого зависит не метка в отчёте, а смысл шага воронки.

    Возвращает `by_engine` (только панели вебмастера — то, что вправе называться
    индексом) и `by_source` (всё подряд, включая краулеры и сторонние сервисы).
    """
    out, extra, notes, unlabeled, kinds, cited = {}, {}, [], set(), {}, {}
    impressions, excluded = set(), {}
    for spec in specs or ():
        name, path = sources.parse_spec(spec)
        header = read_indexed_header(path)
        if name:
            kind = sources.kind_of(name)
            # Подпись в самом файле сильнее метки, которую ему дали: выгрузка
            # цитирований под именем `bing=` читалась как индекс Bing.
            signed, signed_kind = sources.signature_of(header)
            if signed and signed_kind != kind:
                notes.append(tr(
                    "{a0}: помечен как «{a1}», но по столбцам это {a2} — прочитан как {a2}",
                    a0=os.path.basename(path), a1=name, a2=tr(sources.KIND_TITLE[signed_kind])))
                name, kind = signed, signed_kind
        else:
            guessed, kind, confident = sources.identify(path, header)
            name = guessed or os.path.splitext(os.path.basename(path))[0].lower()
            kind = kind or sources.LIST
            if not confident:
                unlabeled.add(name)
                notes.append(
                    tr("{a0}: не удалось уверенно определить источник, файл засчитан как «{a1}» ({a2}). Если это не так, укажи явно: --indexed google={a3} или --indexed ahrefs={a4}", a0=os.path.basename(path), a1=name, a2=tr(sources.KIND_TITLE[kind]), a3=path, a4=path))
        if kind == sources.CITATION:
            # Не индекс, а шаг после него. Слитая в индекс выборка из 93 страниц
            # объявила бы непроиндексированным всё остальное.
            kinds[name] = kind
            counts = read_citations(path, site)
            cited[name] = {**cited.get(name, {}), **counts}
            continue
        # «Эффективность» из Search Console — отчёт о показах: страница в индексе
        # без показов в него не попадает. Узнаётся по столбцу показов.
        if kind == sources.INDEX and _has_impressions(header, path):
            impressions.add(name)
        result = read_indexed(path, site, index_status=kind == sources.INDEX)
        notes += result.get("notes", [])
        urls = set(result["urls"])
        if kind == sources.INDEX:
            dropped = dict(result.get("excluded") or {})
            issue = sources.zip_issue(path)
            if issue:
                # Архив одной причины из «Индексирования страниц»: всё, что
                # в нём есть, поисковик индексировать отказался.
                dropped.update({url: issue for url in urls})
                urls = set()
            if dropped:
                excluded.setdefault(name, {}).update(dropped)
                reasons = Counter(dropped.values()).most_common(3)
                notes.append(tr(
                    "{a0}: {a1} адрес(ов) поисковик сам называет не проиндексированными "
                    "({a2}) — в шаг «в индексе» они не засчитаны",
                    a0=os.path.basename(path), a1=len(dropped),
                    a2="; ".join(f"{reason} — {n}" for reason, n in reasons)))
            if not urls:
                kinds[name] = kind
                continue
        kinds[name] = kind
        target = out if kind == sources.INDEX else extra
        if name in target:
            notes.append(tr("две выгрузки помечены как «{a0}» — они объединены; если это разные источники, задай метки явно", a0=name))
            target[name] |= urls
        else:
            target[name] = urls

    if not out and extra:
        notes.append(
            tr("панели вебмастера среди выгрузок нет. Воронка построена на том, что есть, но подпись шага это учитывает: ")
            + "; ".join(sources.describe(list(extra))) + ".")
    return {"by_engine": out, "by_source": extra, "kinds": kinds, "cited": cited,
            "impressions": sorted(impressions), "excluded": excluded,
            "notes": notes, "unlabeled": sorted(unlabeled)}


_IMPRESSION_WORDS = ("impression", "impr", "показ", "impresion", "impress",
                     "affichage", "wyświetl", "vertoning", "gösterim", "visning",
                     "表示回数", "展示", "曝光", "노출", "การแสดงผล")


def _has_impressions(header, path: str = "") -> bool:
    """
    Отчёт о показах, а не об индексе.

    Узнаётся по устройству, а не по точному слову: в режиме сравнения периодов
    столбец зовётся «Last 28 days Impressions», в японской панели — «表示回数»,
    и оба раза страницы без показов назывались непроиндексированными. CTR
    считается только от показов и на всех языках пишется одинаково.
    """
    cells = [str(h or "").strip().lower() for h in header or ()]
    if any(word in cell for cell in cells for word in _IMPRESSION_WORDS):
        return True
    if any(cell == "ctr" or cell.endswith(" ctr") or cell.startswith("ctr ") for cell in cells):
        return True
    return "performance-on-search" in os.path.basename(path or "").lower()


def funnel(pages: list, sitemap_urls: list = None, indexed_urls: list = None,
           by_engine: dict = None, by_source: dict = None,
           cited: dict = None, impressions: list = None) -> dict:
    """
    Строит воронку и, главное, объясняет каждую потерю.
    Возвращает как числа, так и конкретные списки URL — чинить надо адресно.

    Всё сравнение идёт по ключу URL: `/виза/`, `/%D0%B2%D0%B8%D0%B7%D0%B0/`
    и `/виза/index.html` — одна страница.
    """
    from .publish import indexable

    display = {url_key(p.url): p.url for p in pages}
    generated = set(display)
    # Все панели — отчёты о показах, и других свидетельств индексации нет.
    live_panels = [n for n, u in (by_engine or {}).items() if u]
    impressions_only = bool(live_panels) and not (by_source or {}) and all(
        n in set(impressions or ()) for n in live_panels)
    publishable = {url_key(p.url) for p in pages if indexable(p)}
    blocked = generated - publishable

    def show(keys):
        return sorted(display.get(k, k) for k in keys)

    in_sitemap = _keys(sitemap_urls or []) if sitemap_urls is not None else None
    # Панели вебмастера и всё остальное считаются вместе, но помнят, кто есть кто:
    # от состава зависит, как честно назвать шаг.
    panels = {name: _keys(urls) for name, urls in (by_engine or {}).items() if urls}
    others = {name: _keys(urls) for name, urls in (by_source or {}).items() if urls}
    engines_keys = dict(panels)
    engines_keys.update(others)
    # Адрес, как он стоял в выгрузке: ключ для сравнения теряет слэш, `.html`
    # и `www`, а спрашивать живой сайт нужно ровно о том, что знает поисковик.
    exported = {}
    for urls in list((by_engine or {}).values()) + list((by_source or {}).values()) \
            + [indexed_urls or ()]:
        for url in urls or ():
            exported.setdefault(url_key(url), url)
    if engines_keys and indexed_urls is None:
        in_index = set().union(*engines_keys.values())
    elif indexed_urls is not None:
        in_index = _keys(indexed_urls)
    else:
        in_index = None

    missing_from_sitemap = show(publishable - in_sitemap) if in_sitemap is not None else []
    stale_in_sitemap = sorted(in_sitemap - generated) if in_sitemap is not None else []

    known = in_sitemap & publishable if in_sitemap is not None else publishable
    not_indexed = show(known - in_index) if in_index is not None else []
    indexed_unknown = sorted(in_index - generated) if in_index is not None else []

    steps = [
        {"name": tr("Сгенерировано"), "count": len(generated)},
        {"name": tr("Пригодно к индексации"), "count": len(publishable),
         "lost": len(blocked),
         "why": tr("noindex или canonical на другую страницу")},
    ]
    if in_sitemap is not None:
        steps.append({"name": tr("В sitemap"), "count": len(in_sitemap & publishable),
                      "lost": len(publishable - in_sitemap),
                      "why": tr("страница есть на диске, но в sitemap не попала")})
    if in_index is not None:
        # Счёт и потери берутся от одного множества `known`, иначе воронка
        # росла: закрытая от индексации страница, ещё сидящая в индексе,
        # давала «в индексе 3» после «в sitemap 2».
        label = sources.index_grade(list(engines_keys)) or tr("Хотя бы в одном индексе")
        why = tr("источник знает про URL, но страницы в нём нет")
        if impressions_only:
            # Отчёт о показах, а не об индексе: на молодом сайте «потеряно 26»
            # значило «у 26 страниц не было показов», и пакет называл это
            # непроиндексированностью.
            label = tr("С показами в поиске")
            why = tr("показов за период не было — страница в индексе без показов "
                     "в эту выгрузку не попадает")
        steps.append({"name": label, "count": len(known & in_index),
                      "lost": len(known - in_index), "why": why})
        for name in sorted(engines_keys):
            hit = engines_keys[name] & known
            kind = sources.kind_of(name)
            suffix = ("" if kind == sources.INDEX
                      else f" ({tr(sources.KIND_TITLE[kind])})")
            steps.append({"name": tr("  из них в {a0}{a1}", a0=name, a1=suffix), "count": len(hit),
                          "lost": len((known & in_index) - hit),
                          "why": tr("есть в других источниках, но не в {a0}", a0=name),
                          "engine": name, "kind": kind})

    # Цитирование — последний шаг, а не вклад в индекс. База — то, что точно в
    # индексе, если индекс известен; иначе всё пригодное.
    cited_keys = {name: {url_key(u): n for u, n in counts.items()}
                  for name, counts in (cited or {}).items() if counts}
    cited_closed, cited_unknown, cited_top, cited_off_map = [], [], [], []
    if cited_keys:
        # База — индексируемые страницы, а не «в sitemap»: цитирование
        # доказывает, что ИИ страницу нашёл, и sitemap тут ни при чём. Иначе
        # процитированная страница, которой нет в sitemap, тихо выпадала.
        base = (publishable & in_index) if in_index is not None else publishable
        every = {}
        for counts in cited_keys.values():
            for k, n in counts.items():
                every[k] = every.get(k, 0) + n
        for name in sorted(cited_keys):
            hit = set(cited_keys[name]) & base
            # Без «потеряно»: отсутствие цитирований — не потеря, данные выборка.
            steps.append({
                "name": tr("Цитируется: {a0}", a0=name),
                "count": len(hit), "lost": None,
                "engine": name, "kind": sources.CITATION})
        # ИИ цитирует страницу, которую сайт закрыл от индекса: страница
        # продолжает работать как источник, хотя владелец её убрал.
        cited_closed = show(set(every) & blocked)
        cited_unknown = sorted(k for k in every if k not in generated)
        if in_sitemap is not None:
            # Заглушка-редирект в sitemap не входит и не должна: её цитируют,
            # потому что люди ссылаются на домен, а не потому, что её забыли.
            from .checks import redirect_target
            stubs = {url_key(p.url) for p in pages if redirect_target(p)}
            cited_off_map = show((set(every) & publishable) - in_sitemap - stubs)
        cited_top = sorted(((display.get(k, k), n) for k, n in every.items()),
                           key=lambda kv: -kv[1])

    foreign = []
    # Краулер и сторонний сервис поднимают цифру шага, не поднимая индексацию.
    # Без этой оговорки добавление выгрузки Screaming Frog выглядело бы как
    # улучшение — самый дорогой вид уверенной неправды.
    if panels and others:
        foreign.append(
            tr("в шаг засчитаны источники, которые индексом не являются ({a0}). Реальную индексацию показывают строки панелей: {a1}.", a0=', '.join(sorted(others)), a1=', '.join(sorted(panels))))
    elif others and not panels:
        foreign.append(
            tr("панели вебмастера среди выгрузок нет, поэтому строгого ответа «в индексе или нет» здесь не будет: ")
            + "; ".join(sources.describe(list(others))) + ".")
    if in_index is not None and generated and not (in_index & generated) and in_index:
        foreign.append(
            tr("ни один из {a0} адресов выгрузки не совпал с адресами сайта. Скорее всего, это экспорт другого проекта или другой домен (проверь --site). Раздел индексации ниже смысла не имеет.", a0=len(in_index)))

    return {
        "steps": steps,
        "foreign": foreign,
        "by_engine": {name: show(keys & generated) for name, keys in engines_keys.items()},
        "engine_keys": {name: sorted(keys) for name, keys in engines_keys.items()},
        "panel_keys": {name: sorted(keys) for name, keys in panels.items()},
        "kinds": {name: sources.kind_of(name) for name in engines_keys},
        "proves": sources.describe(list(engines_keys)),
        "display": display,
        "blocked": show(blocked),
        "missing_from_sitemap": missing_from_sitemap,
        "stale_in_sitemap": stale_in_sitemap,
        "not_indexed": not_indexed,
        "indexed_unknown": indexed_unknown,
        "exported": {k: exported[k] for k in indexed_unknown if k in exported},
        "has_sitemap": in_sitemap is not None,
        "has_index": in_index is not None,
        "cited_closed": cited_closed,
        "cited_unknown": cited_unknown,
        "cited_top": cited_top,
        "cited_not_in_sitemap": cited_off_map,
        "impressions_only": impressions_only,
    }


def cross_engine(funnel_result: dict, pages: list) -> list:
    """
    Сравнивает индексы разных поисковиков. Это меняет диагноз.

    Страница, которой нет НИГДЕ, — почти всегда техническая проблема:
    её не обошли или отбраковали по формальным признакам.
    Страница, которая есть в одном индексе и нет в другом, — уже другое:
    краулер её обошёл и принял, значит дело не в технике, а в оценке
    качества конкретным поисковиком либо в разной скорости индексации.

    Страницы, закрытые от индексации намеренно, в «нигде» не попадают:
    раньше сознательный noindex выглядел как авария.

    Сравниваются только панели вебмастера. Ставить в один ряд «есть в Google»
    и «Screaming Frog дошёл» нельзя: это утверждения о разных вещах, и вывод
    «страница есть у одного и нет у другого» из такой пары был бы бессмыслицей,
    поданной уверенным тоном.
    """
    from .publish import indexable

    panels = funnel_result.get("panel_keys")
    if panels is None:                      # старый вызов без разделения
        panels = funnel_result.get("engine_keys") or {}
    by_engine = {name: set(keys) for name, keys in panels.items()}
    if len(by_engine) < 2:
        return []

    display = funnel_result.get("display") or {}
    expected = {url_key(p.url) for p in pages if indexable(p)}
    everywhere = set.intersection(*by_engine.values()) & expected
    anywhere = set.union(*by_engine.values()) & expected

    def show(keys):
        return sorted(display.get(k, k) for k in keys)

    out = [{
        "kind": tr("везде"),
        "count": len(everywhere),
        "note": tr("во всех подключённых индексах — здесь вопросов нет"),
        "urls": [],
    }]

    for name, keys in sorted(by_engine.items()):
        missing = (anywhere - keys)
        if missing:
            out.append({
                "kind": tr("нет только в {a0}", a0=name),
                "count": len(missing),
                "note": tr("другие поисковики страницу приняли, значит она доступна и валидна. Причина на стороне {a0}: оценка качества или более медленная индексация — техническими правками это обычно не лечится", a0=name),
                "urls": show(missing)[:50],
            })

    nowhere = expected - anywhere
    if nowhere:
        out.append({
            "kind": tr("нигде"),
            "count": len(nowhere),
            "note": tr("ни один поисковик не добавил в индекс — это техническая проблема, ищите причину в разделе ниже"),
            "urls": show(nowhere)[:50],
        })
    return out


def explain(funnel_result: dict, analysis: dict) -> list:
    """
    Связывает потери с найденными причинами: не просто «40 страниц не в индексе»,
    а «из них 31 сирота, 6 почти-дубли». Это и есть то, что нельзя нагуглить.

    Страница может попасть сразу в несколько причин — так и есть в жизни,
    и раньше вторая причина терялась вместе с нужной правкой.
    """
    out = []
    not_indexed = _keys(funnel_result.get("not_indexed", []))
    if not not_indexed:
        return out

    display = funnel_result.get("display") or {}
    graph = analysis["graph"]
    config = analysis["config"]

    orphans = _keys(set(graph["orphans"]) | set(graph["unreachable"]))
    # Только настоящие дубли: «похожа на 57%» — не повод ставить canonical,
    # а раньше разбор потерь предписывал именно это.
    near = analysis["config"].get("near_duplicate", 0.8)
    dupes = _keys({p.url for pair in analysis["duplicates"]
                   if pair[2] >= near for p in pair[:2]})
    thin = _keys({p.url for p in analysis["pages"]
                  if p.word_count < config["thin_words"]})
    deep = _keys({u for u, d in graph["depth"].items() if d > config["max_click_depth"]})
    no_title = _keys({p.url for p in analysis["pages"] if not p.title})

    buckets = [
        (tr("сироты и недостижимые от главной"), not_indexed & orphans,
         tr("добавить ссылки на них с хабовых страниц раздела")),
        (tr("почти-дубли других страниц"), not_indexed & dupes,
         tr("переписать под разные интенты или оставить одну, а с остальных поставить canonical на неё — связывать их ссылками между собой нельзя")),
        (tr("тонкие страницы"), not_indexed & thin,
         tr("добавить содержимое или убрать из индекса")),
        (tr("глубже допустимого клика"), not_indexed & deep,
         tr("поднять выше в структуре")),
        (tr("без title"), not_indexed & no_title,
         tr("заполнить title — без него страница почти не имеет шансов")),
    ]
    explained = set()
    for name, keys, fix in buckets:
        if keys:
            explained |= keys
            out.append({"cause": name, "count": len(keys), "fix": fix,
                        "urls": sorted(display.get(k, k) for k in keys)[:50]})

    rest = not_indexed - explained
    if rest and funnel_result.get("impressions_only"):
        out.append({"cause": tr("показов за период нет, других причин локально не видно"),
                    "count": len(rest),
                    "fix": tr("для новых страниц и молодого сайта это обычно. Индексацию "
                              "показывает Search Console → Индексирование → Страницы, "
                              "а не эта выгрузка"),
                    "urls": sorted(display.get(k, k) for k in rest)[:50]})
    elif rest:
        out.append({"cause": tr("причина не установлена локально"),
                    "count": len(rest),
                    "fix": tr("проверить в Search Console статус конкретных URL и время с публикации"),
                    "urls": sorted(display.get(k, k) for k in rest)[:50]})
    return out
