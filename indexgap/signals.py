# -*- coding: utf-8 -*-
"""
Сигналы страницы, которые видны по файлу сборки: год в заголовке, title
против H1, превью для соцсетей, мобильная разметка, вес файлов, хабы.

Каждая проверка здесь отвечает на вопрос, который в разборе чужого списка
SEO-приёмов можно было закрыть без сети и без браузера. То, что требует
браузера («уберите лишние скрипты»), сюда не попало: честно измерить это по
файлу нельзя.
"""

from __future__ import annotations

import datetime
import os
import re
from collections import Counter, defaultdict
from urllib.parse import urlsplit

from .core import ALWAYS_SKIP, tokenize, url_key
from .i18n import tr

# Googlebot читает первые 2 МБ поддерживаемого файла и отдаёт в индекс то, что
# успел прочитать (developers.google.com/search/docs/crawling-indexing/googlebot,
# обновлено 2026-02-03).
HTML_LIMIT = 2 * 1024 * 1024
IMAGE_LIMIT = 1024 * 1024
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".tif", ".tiff", ".svg")
MAX_WALK = 200_000


def _is_html(page) -> bool:
    return (getattr(page, "path", "") or "").lower().endswith((".html", ".htm"))


# ── год в заголовке ──────────────────────────────────────────────────────────

_YEAR = re.compile(r"(?<![\w.,])(20\d\d)(?![\d.,])")
# Год в имени продукта — версия, а не дата: «SQL Server 2019», «Office 2016»,
# «Windows 2000». «ES2017» отсекает уже граница слова.
_PRODUCT = re.compile(
    r"\b(?:server|windows|office|studio|excel|word|outlook|exchange|sharepoint|"
    r"autocad|revit|photoshop|ecmascript|es|sql|dynamics|navision|1с|1c)\s+$", re.I)
# Диапазон, который доходит до текущего года, — не прошлое: «2025–2026»,
# «2025/26», «2025-26».
_RANGE_AFTER = re.compile(r"^\s*[–—/-]\s*(\d{2,4})\b")
_RANGE_BEFORE = re.compile(r"\b(20\d\d)\s*[–—/-]\s*$")
# Год как точка отсчёта: «since 2015», «established in 2015», «с 2015 года».
_SINCE = re.compile(r"\b(?:since|established(?:\s+in)?|est\.?|founded(?:\s+in)?|from|"
                    r"с|со|от|основан\w*(?:\s+в)?)\s+$", re.I)
_LD_DATE = re.compile(r'"date(?:Published|Created)"\s*:\s*"(\d{4})')
_TIME_YEAR = re.compile(r"(\d{4})")
STALE_MIN_PAGES = 5
STALE_SHARE = 0.3


def _page_years(page) -> set:
    """Годы, которыми страница датирована: публикация, JSON-LD, `<time>`."""
    years = set()
    meta = getattr(page, "meta", {}) or {}
    for key in ("datepublished", "date", "datecreated", "datemodified"):
        found = re.match(r"\s*(\d{4})", str(meta.get(key) or ""))
        if found:
            years.add(int(found.group(1)))
    for block in getattr(page, "jsonld", None) or ():
        years.update(int(y) for y in _LD_DATE.findall(block))
    return years


def _past_years(text: str, current: int) -> set:
    """Прошлые годы в строке — без диапазонов до текущего года и без «since 2015»."""
    out = set()
    for m in _YEAR.finditer(text or ""):
        year = int(m.group(1))
        if not 2000 <= year < current:
            continue
        before, after = text[:m.start()], text[m.end():]
        if _SINCE.search(before) or _PRODUCT.search(before):
            continue
        tail = _RANGE_AFTER.match(after)
        if tail:
            end = int(tail.group(1))
            end = end + 2000 if end < 100 else end
            if end >= current:
                continue
        head = _RANGE_BEFORE.search(before)
        if head and int(head.group(1)) < year:
            continue                        # вторая половина «2023–2025» решается по ней
        out.add(year)
    return out


def stale_years(pages: list, today: datetime.date = None) -> list:
    """
    Прошлый год в заголовках раздела: шаблон, который не обновили.

    Одна страница с годом в заголовке ничего не говорит: «2019 Honda Civic»,
    «The Batman (2022) review», «Paris Olympics 2024» — о том годе и написаны.
    Забытый шаблон виден по-другому: один и тот же прошлый год стоит в
    заголовках у пяти и больше страниц и не меньше чем у трети раздела.
    Страница, датированная тем же годом, — запись о нём и не считается.
    Одна находка на раздел.
    """
    current = (today or datetime.date.today()).year
    by_section = defaultdict(list)
    for page in pages:
        parts = urlsplit(page.url).path.strip("/").split("/")
        by_section[parts[0] if len(parts) > 1 else ""].append(page)
    issues = []
    for section, members in sorted(by_section.items()):
        hits = defaultdict(list)
        for page in members:
            h1 = next((t for level, t in (page.headings or []) if level == 1), "")
            years = _past_years(page.title, current) | _past_years(h1, current)
            for year in years - _page_years(page):
                hits[year].append(page)
        for year, found in sorted(hits.items()):
            if len(found) < STALE_MIN_PAGES or len(found) < STALE_SHARE * len(members):
                continue
            examples = "; ".join(f"«{p.title[:60]}»" for p in sorted(found, key=lambda p: p.url)[:2])
            hub = next((p.url for p in members
                        if urlsplit(p.url).path.strip("/") == section), "")
            issues.append(("warning", hub, "stale-year", tr(
                "у {a0} из {a1} страниц раздела /{a2} в заголовке {a3} год, а сейчас {a4}: "
                "шаблон заголовка не обновили. Например: {a5}",
                a0=len(found), a1=len(members), a2=(section + "/") if section else "",
                a3=year, a4=current, a5=examples)))
    return issues


# ── title против H1 ──────────────────────────────────────────────────────────

_SEPARATORS = re.compile(r"\s+[|·•—–-]\s+|\s*:\s+")
_STOP = {"the", "and", "for", "with", "your", "you", "our", "from", "how", "what",
         "best", "top", "all", "new", "это", "для", "как", "что", "все", "наш", "ваш"}


def _words(text: str) -> set:
    out = set()
    for word in tokenize(text or ""):
        word = word.lower()
        if len(word) < 3 or word in _STOP or word.isdigit():
            continue
        out.add(word)
    return out


def _share(a: set, b: set) -> bool:
    """
    Общее слово с поправкой на форму: plumber/plumbers и электрик/электрики —
    по началу, «أدلة» и «الأدلة» (арабский артикль) — по вхождению.
    """
    for x in a:
        for y in b:
            if x[:5] == y[:5] or (min(len(x), len(y)) >= 3 and (x in y or y in x)):
                return True
    return False


def _title_h1_apart(title: str, h1: str) -> bool:
    if not title or not h1:
        return False
    if any(len(w) == 1 and not w.isascii() for w in tokenize(h1 + " " + title)):
        return False                       # иероглифика: слов по пробелам нет
    head = _words(h1)
    parts = [_words(p) for p in _SEPARATORS.split(title)] or [_words(title)]
    if len(head) < 2 or max(len(p) for p in parts) < 2:
        return False
    return not any(_share(head, p) for p in parts)


# ── постраничные сигналы ─────────────────────────────────────────────────────

def page_signals(pages: list, today: datetime.date = None) -> list:
    current = (today or datetime.date.today()).year
    issues = []
    for page in sorted(pages, key=lambda p: p.url):
        h1s = [t for level, t in (page.headings or []) if level == 1]
        h1 = h1s[0] if h1s else ""
        # Логотип в <h1> шапки — не заголовок статьи: сверяем со всеми H1.
        if h1s and all(_title_h1_apart(page.title, h) for h in h1s):
            issues.append(("info", page.url, "title-h1-mismatch", tr(
                "title и H1 не делят ни одного слова: «{a0}» и «{a1}» — поисковик "
                "может переписать заголовок в выдаче", a0=page.title[:60], a1=h1[:60])))
        if not _is_html(page):
            continue
        meta = page.meta or {}
        missing = [name for name in ("og:title", "og:image") if not meta.get(name)]
        image = meta.get("og:image") or ""
        if image and not image.startswith(("http://", "https://")):
            # Open Graph требует абсолютный адрес: относительный мессенджер не откроет.
            missing.append(tr("абсолютного адреса в og:image ({a0})", a0=image[:60]))
        if missing:
            issues.append(("info", page.url, "no-og", tr(
                "нет {a0}: ссылка на страницу в мессенджере или соцсети выйдет без "
                "заголовка или картинки", a0=", ".join(missing))))
        if not meta.get("viewport"):
            issues.append(("warning", page.url, "no-viewport", tr(
                "нет <meta name=\"viewport\">: на телефоне страница откроется "
                "уменьшенной копией десктопа, а Google индексирует мобильную версию")))
        try:
            size = os.path.getsize(page.path)
        except OSError:
            size = 0
        if size > HTML_LIMIT:
            issues.append(("warning", page.url, "heavy-html", tr(
                "HTML весит {a0:.1f} МБ: Googlebot читает первые 2 МБ файла, остальное в "
                "индекс не попадает", a0=size / 1024 / 1024)))
    return issues


# ── хабы ─────────────────────────────────────────────────────────────────────

# Пагинация — `page/2`, `p/2`, `page-2`, `seite/2`, `strona/2`, `страница/2`.
# Голое число (`/products/1001/`, `/archive/2019/`) — адрес страницы, а не
# номер листа: раньше такие разделы не проверялись вовсе.
_PAGINATION = re.compile(r"^(?:page|p|seite|strona|pagina|страница)[/-]?\d+$", re.I)


def hub_links(pages: list, graph: dict, skip: set = frozenset()) -> list:
    """
    Раздел, который не ссылается на свои страницы.

    `/plumbing/` есть, а `/plumbing/boston/` с него не связан: поисковик
    доходит до страницы через sitemap или случайную ссылку, и вес раздела до
    неё не доходит. Ссылка засчитывается и со страниц пагинации раздела
    (`/plumbing/page/2/`), и с любой страницы-списка внутри раздела, где
    ссылок на детей раздела пять и больше — алфавитные указатели так и устроены.

    Один проход по страницам: каждая встаёт под своих предков-разделов. Раньше
    каждый раздел перебирал весь сайт, и на 40 тысячах страниц это были
    одиннадцать секунд.
    """
    by_key = {p.key: p for p in pages}
    inbound = graph.get("inbound") or {}
    outbound = graph.get("outbound") or {}
    children = defaultdict(list)
    for page in pages:
        if page.url in skip:
            continue
        key = page.key
        parent = key[:key.rfind("/")] if key.count("/") > 2 else ""
        if parent and parent in by_key and by_key[parent].url not in skip:
            children[parent].append(page)
    # `_modules/`, `_sources/` — служебные листинги Sphinx, а не разделы сайта.
    hubs = {k: kids for k, kids in children.items()
            if len(kids) >= 2 and "/_" not in k}
    kid_urls = {k: {p.url for p in kids} for k, kids in hubs.items()}
    listing = {k: {by_key[k].url} for k in hubs}
    # Оглавление на весь сайт (`toc.html` mdBook, HTML-карта сайта) — тоже
    # путь к страницам раздела: оно ссылается почти на всех его детей сразу.
    hub_of = {url: k for k, urls in kid_urls.items() for url in urls}
    for page in pages:
        out = set(outbound.get(page.url, ()))
        if len(out) < 5:
            continue
        touched = Counter(hub_of[u] for u in out if u in hub_of)
        for hub_key, n in touched.items():
            if n >= max(5, 0.8 * len(kid_urls[hub_key])):
                listing[hub_key].add(page.url)
    for page in pages:
        key = page.key
        cut = key.rfind("/")
        while key.count("/", 0, cut) >= 2:
            hub_key = key[:cut]
            if hub_key in hubs:
                tail = key[len(hub_key) + 1:]
                if (_PAGINATION.match(tail)
                        or len(set(outbound.get(page.url, ())) & kid_urls[hub_key]) >= 5):
                    listing[hub_key].add(page.url)
            cut = key.rfind("/", 0, cut)

    issues = []
    for hub_key, kids in sorted(hubs.items()):
        hub = by_key[hub_key]
        missing = sorted(k.url for k in kids
                         if not set(inbound.get(k.url, ())) & listing[hub_key]
                         and not _PAGINATION.match(k.key[len(hub_key) + 1:]))
        if missing:
            shown = ", ".join(urlsplit(u).path for u in missing[:3])
            issues.append(("warning", hub.url, "hub-missing-links", tr(
                "раздел не ссылается на {a0} из {a1} своих страниц: {a2}{a3} — до них "
                "доходят только через sitemap или случайные ссылки",
                a0=len(missing), a1=len(kids), a2=shown,
                a3=tr(" и ещё {a0}", a0=len(missing) - 3) if len(missing) > 3 else "")))
    return issues


# ── картинки ─────────────────────────────────────────────────────────────────

def heavy_images(pages: list) -> list:
    """Картинки тяжелее 1 МБ в сборке — одна находка на сайт, с самыми тяжёлыми."""
    paths = [os.path.dirname(p.path) for p in pages if p.path and _is_html(p)]
    if not paths:
        return []
    try:
        root = os.path.commonpath(paths)
    except ValueError:
        return []
    heavy, seen = [], 0
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in ALWAYS_SKIP and not d.startswith("."))
        for name in files:
            seen += 1
            if not name.lower().endswith(IMAGE_EXTS):
                continue
            path = os.path.join(current, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if size > IMAGE_LIMIT:
                heavy.append((size, os.path.relpath(path, root).replace(os.sep, "/")))
        if seen > MAX_WALK:
            break
    if not heavy:
        return []
    heavy.sort(key=lambda x: (-x[0], x[1]))
    shown = ", ".join(f"{name} ({size / 1024 / 1024:.1f} MB)" for size, name in heavy[:5])
    return [("info", "", "heavy-images", tr(
        "картинок тяжелее 1 МБ в сборке: {a0} — {a1}. Они замедляют страницу на телефоне; "
        "сожми их или отдай WebP/AVIF", a0=len(heavy), a1=shown))]
