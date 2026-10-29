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
from collections import defaultdict
from urllib.parse import urlsplit

from .core import ALWAYS_SKIP, tokenize, url_key
from .i18n import tr

# Googlebot читает первые 2 МБ поддерживаемого файла и отдаёт в индекс то, что
# успел прочитать (developers.google.com/search/docs/crawling-indexing/googlebot,
# обновлено 2026-02-03).
HTML_LIMIT = 2 * 1024 * 1024
IMAGE_LIMIT = 1024 * 1024
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".tif", ".tiff")
MAX_WALK = 200_000


def _is_html(page) -> bool:
    return (getattr(page, "path", "") or "").lower().endswith((".html", ".htm"))


# ── год в заголовке ──────────────────────────────────────────────────────────

_YEAR = re.compile(r"(?<![\d.])(20\d\d)(?![\d.])")
# Слова свежести: заголовок с ними обещает актуальность, и прошлый год в нём —
# забытый шаблон, а не история.
_FRESH = re.compile(
    r"\b(?:best|top|guide|review|reviews|price|prices|pricing|cost|costs|rates|list|"
    r"ranking|ranked|update|updated|latest|new|deals|"
    r"лучш\w*|топ|цен\w*|стоимост\w*|рейтинг\w*|обзор\w*|гид|список|актуальн\w*|"
    r"обновл\w*|новы\w*)\b", re.I)
_BEFORE = re.compile(r"(?:\b(?:in|for|of|в|на|для)\s+|[(\[—–-]\s*)$", re.I)
_SINCE = re.compile(r"\b(?:since|from|с|со|от)\s+$", re.I)
_SEPARATORS = re.compile(r"\s+[|·•—–-]\s+|\s*:\s+")
_LD_DATE = re.compile(r'"date(?:Published|Created)"\s*:\s*"(\d{4})')


def _page_year(page) -> int:
    meta = getattr(page, "meta", {}) or {}
    for key in ("datepublished", "date", "datecreated"):
        found = re.match(r"\s*(\d{4})", str(meta.get(key) or ""))
        if found:
            return int(found.group(1))
    for block in getattr(page, "jsonld", None) or ():
        found = _LD_DATE.search(block)
        if found:
            return int(found.group(1))
    return 0


def _stale_year(text: str, current: int) -> int:
    """Прошлый год, поданный как свежесть: в конце заголовка, после «в»/«for» или рядом со словом свежести."""
    text = text or ""
    core = _SEPARATORS.split(text)[0] if _SEPARATORS.search(text) else text
    for m in _YEAR.finditer(text):
        year = int(m.group(1))
        if not 2000 <= year < current:
            continue
        before = text[:m.start()]
        if _SINCE.search(before):
            continue
        at_end = not core[core.find(m.group(1)) + 4:].strip(" )]!?.,") if m.group(1) in core else False
        if at_end or _BEFORE.search(before) or _FRESH.search(text):
            return year
    return 0


# ── title против H1 ──────────────────────────────────────────────────────────

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
        h1 = next((t for level, t in (page.headings or []) if level == 1), "")
        year = _stale_year(page.title, current) or _stale_year(h1, current)
        # Запись с датой публикации до этого года — история, а не забытый
        # шаблон: «опыт студентов OSPP-2020» в блоге apisix. Год в адресе
        # (`/blog/2021/…`, `/2022-meetups/`) — тот же знак: страница о том годе.
        published = _page_year(page)
        if year and (0 < published < current or str(year) in urlsplit(page.url).path):
            year = 0
        if year:
            issues.append(("warning", page.url, "stale-year", tr(
                "в заголовке {a0} год, а сейчас {a1}: страница обещает свежесть и выглядит "
                "заброшенной — шаблон или данные не обновили", a0=year, a1=current)))
        if _title_h1_apart(page.title, h1):
            issues.append(("info", page.url, "title-h1-mismatch", tr(
                "title и H1 не делят ни одного слова: «{a0}» и «{a1}» — поисковик "
                "может переписать заголовок в выдаче", a0=page.title[:60], a1=h1[:60])))
        if not _is_html(page):
            continue
        meta = page.meta or {}
        missing = [name for name in ("og:title", "og:image") if not meta.get(name)]
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

_PAGINATION = re.compile(r"^(?:page|p|seite|страница)/?\d+$|^\d+$", re.I)


def hub_links(pages: list, graph: dict, skip: set = frozenset()) -> list:
    """
    Раздел, который не ссылается на свои страницы.

    `/plumbing/` есть, а `/plumbing/boston/` с него не связан: поисковик
    доходит до страницы через sitemap или случайную ссылку, и вес раздела до
    неё не доходит. Ссылка засчитывается и со страниц пагинации раздела
    (`/plumbing/page/2/`), и с любой страницы-списка внутри раздела, где
    ссылок на детей раздела пять и больше — алфавитные указатели так и устроены.
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
    issues = []
    for hub_key, kids in sorted(children.items()):
        if len(kids) < 2:
            continue
        hub = by_key[hub_key]
        kid_urls = {k.url for k in kids}
        section = [p for p in pages if p.key.startswith(hub_key + "/")]
        listing = {hub.url}
        for p in section:
            tail = p.key[len(hub_key) + 1:]
            if _PAGINATION.match(tail) or len(set(outbound.get(p.url, ())) & kid_urls) >= 5:
                listing.add(p.url)
        missing = sorted(k.url for k in kids
                         if not set(inbound.get(k.url, ())) & listing
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
