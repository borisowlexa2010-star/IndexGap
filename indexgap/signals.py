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
import json
import os
import re
from collections import Counter, defaultdict
from urllib.parse import urlsplit

from .core import ALWAYS_SKIP, _CODE_TAG, tokenize
from .i18n import N_, tr
from .settings import DENSE_SCRIPT
from .subject import Said

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

# Точка или запятая после года — конец фразы («in 2023, explained», «for
# 2023.»), если за ней не цифра: «2023.5» и «2023,45» — числа, а не годы.
_YEAR = re.compile(r"(?<![\w.,])(20\d\d)(?!\d|[.,]\d)")
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
    from .aeo import _ld_items, _ld_types
    for block in getattr(page, "jsonld", None) or ():
        try:
            nodes = _ld_items(json.loads(block), ("mainentity",))
        except (ValueError, RecursionError):
            years.update(int(y) for y in _LD_DATE.findall(block))
            continue
        # Дата самой страницы, а не вложенного отзыва или комментария: отзыв
        # 2024 года не делает «2024» в заголовке датой страницы.
        for node in nodes:
            if _ld_types(node) & {"review", "comment"}:
                continue
            for key, value in node.items():
                if str(key).lower() in ("datepublished", "datecreated"):
                    found = re.match(r"\s*(\d{4})", str(value or ""))
                    if found:
                        years.add(int(found.group(1)))
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


def stale_years(pages: list, today: datetime.date = None, base_path: str = "") -> list:
    """
    Прошлый год в заголовках раздела: шаблон, который не обновили.

    Одна страница с годом в заголовке ничего не говорит: «2019 Honda Civic»,
    «The Batman (2022) review», «Paris Olympics 2024» — о том годе и написаны.
    Забытый шаблон виден по-другому: один и тот же прошлый год стоит в
    заголовках у пяти и больше страниц и не меньше чем у трети раздела.
    Страница, датированная тем же годом, — запись о нём и не считается.
    Одна находка на раздел. `base_path` — путь сайта под префиксом
    (`--site https://example.com/blog`): раздел считается от него, иначе
    весь сайт оказывался одним разделом `/blog/`.
    """
    current = (today or datetime.date.today()).year
    base = base_path.strip("/")
    by_section = defaultdict(list)
    for page in pages:
        path = urlsplit(page.url).path.strip("/")
        if base and (path == base or path.startswith(base + "/")):
            path = path[len(base):].strip("/")
        parts = path.split("/")
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
            # Адрес находки — раздел, а не страница: `/plumbing/`. Находка про
            # шаблон заголовка, и у страницы раздела года в заголовке может не
            # быть вовсе. Раньше здесь искали страницу раздела среди `members`,
            # а она состоит из одного сегмента и лежит в корневом разделе: у
            # любого именованного раздела её не находили никогда, и адрес был
            # пустым (у корневого находилась главная). Две такие находки в разных
            # разделах базовая линия не различала (один раздел починили, другой
            # устарел — «без изменений»), а `ignore` по пути не мог принять ни
            # одну. Путь, а не адрес страницы, — чтобы находка не пропадала,
            # когда страница раздела закрыта от индекса, и не уходила в наряд
            # на эту страницу.
            prefix = f"/{base}" if base else ""
            address = f"{prefix}/{section}/" if section else f"{prefix}/"
            issues.append(("warning", address, "stale-year", tr(
                "у {a0} из {a1} страниц раздела /{a2} в заголовке {a3} год, а сейчас {a4}: "
                "шаблон заголовка не обновили. Например: {a5}",
                a0=len(found), a1=len(members), a2=address.lstrip("/"),
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
    if DENSE_SCRIPT.search(h1 + " " + title):
        return False                       # иероглифика: слов по пробелам нет
    head = _words(h1)
    parts = [_words(p) for p in _SEPARATORS.split(title)] or [_words(title)]
    if len(head) < 2 or max(len(p) for p in parts) < 2:
        return False
    return not any(_share(head, p) for p in parts)


# ── постраничные сигналы ─────────────────────────────────────────────────────

def page_signals(pages: list, today: datetime.date = None) -> list:
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


# ── lang против письма ───────────────────────────────────────────────────────

# Письмо: название для сообщения и знаки. Считаются только буквы.
SCRIPTS = {
    "latin": (N_("латиница"), "A-Za-z\u00c0-\u024f\u1e00-\u1eff"),
    "cyrillic": (N_("кириллица"), "\u0400-\u052f\u1c80-\u1c8f\u2de0-\u2dff\ua640-\ua69f"),
    "greek": (N_("греческое письмо"), "\u0370-\u03ff\u1f00-\u1fff"),
    "armenian": (N_("армянское письмо"), "\u0530-\u058f"),
    "hebrew": (N_("еврейское письмо"), "\u0590-\u05ff\ufb1d-\ufb4f"),
    "arabic": (N_("арабское письмо"),
               "\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff"),
    "devanagari": (N_("деванагари"), "\u0900-\u097f"),
    "bengali": (N_("бенгальское письмо"), "\u0980-\u09ff"),
    "gujarati": (N_("гуджаратское письмо"), "\u0a80-\u0aff"),
    "tamil": (N_("тамильское письмо"), "\u0b80-\u0bff"),
    "telugu": (N_("телугу"), "\u0c00-\u0c7f"),
    "kannada": (N_("каннада"), "\u0c80-\u0cff"),
    "malayalam": (N_("малаялам"), "\u0d00-\u0d7f"),
    "sinhala": (N_("сингальское письмо"), "\u0d80-\u0dff"),
    "thai": (N_("тайское письмо"), "\u0e00-\u0e7f"),
    "lao": (N_("лаосское письмо"), "\u0e80-\u0eff"),
    "myanmar": (N_("бирманское письмо"), "\u1000-\u109f"),
    "georgian": (N_("грузинское письмо"), "\u10a0-\u10ff\u1c90-\u1cbf"),
    "ethiopic": (N_("эфиопское письмо"), "\u1200-\u139f"),
    "khmer": (N_("кхмерское письмо"), "\u1780-\u17ff"),
    "hangul": (N_("хангыль"), "\u1100-\u11ff\u3130-\u318f\uac00-\ud7af"),
    "kana": (N_("японская кана"), "\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f"),
    "han": (N_("китайские иероглифы"),
            "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ffff"),
}
_SCRIPT_RE = {name: re.compile(f"[{chars}]+") for name, (_, chars) in SCRIPTS.items()}
_LETTERS = re.compile(r"[^\W\d_]+")

_BY_LANG = {"ja": {"han", "kana"}, "ko": {"hangul", "han"}}
for _script, _codes in (
        ("latin", "en de fr es it pt nl sv da no nb nn fi pl cs sk sl hr bs ro hu tr vi id "
                  "ms tl fil et lv lt is ga cy eu ca gl sq af sw mt lb eo la oc br fy gd "
                  "zu xh yo ha ig so mi haw sm to qu ht jv su ceb"),
        ("cyrillic", "ru uk be bg mk kk ky tg mn ba tt cv ce os"),
        ("greek", "el"), ("armenian", "hy"), ("georgian", "ka"),
        ("hebrew", "he iw yi"), ("arabic", "ar fa ur ps ug sd ckb"),
        ("devanagari", "hi mr ne sa"), ("bengali", "bn as"), ("gujarati", "gu"),
        ("tamil", "ta"), ("telugu", "te"), ("kannada", "kn"), ("malayalam", "ml"),
        ("sinhala", "si"), ("thai", "th"), ("lao", "lo"), ("myanmar", "my"),
        ("khmer", "km"), ("ethiopic", "am ti"), ("han", "zh yue")):
    for _code in _codes.split():
        _BY_LANG[_code] = {_script}
# Подтег письма (`sr-Latn`, `zh-Hant`) говорит сам за себя и снимает
# двусмысленность языков с двумя письмами: sr, az, uz, ku, pa без него не судим.
_BY_SUBTAG = {"latn": {"latin"}, "cyrl": {"cyrillic"}, "grek": {"greek"},
              "arab": {"arabic"}, "hebr": {"hebrew"}, "deva": {"devanagari"},
              "beng": {"bengali"}, "thai": {"thai"}, "geor": {"georgian"},
              "armn": {"armenian"}, "hans": {"han"}, "hant": {"han"}, "hani": {"han"},
              "jpan": {"han", "kana"}, "kore": {"hangul", "han"}, "hang": {"hangul"}}

LANG_SCRIPT_MIN_LETTERS = 200
LANG_SCRIPT_SHARE = 0.8
LANG_SCRIPT_SAMPLE = 3000


def declared_scripts(lang: str) -> set:
    """Каким письмом пишется объявленный язык. Пустое множество — не судим."""
    parts = re.split(r"[-_]", (lang or "").strip().lower())
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            return set(_BY_SUBTAG.get(part, ()))
    return set(_BY_LANG.get(parts[0], ()))


def _count(rx, letters: str) -> int:
    # Считаются серии, а не знаки: findall по одному знаку вдесятеро медленнее.
    return sum(map(len, rx.findall(letters)))


def text_script(text: str, expected: set = frozenset()) -> tuple:
    """
    (письмо, доля букв, число букв) — самое частое письмо текста. Если
    ожидаемых писем больше пятой части, другое не наберёт восьми десятых:
    остальные не считаются, и ответ — первое из ожидаемых.
    """
    text = text or ""
    if len(text) > 2 * LANG_SCRIPT_SAMPLE:
        # Начало и конец: двуязычная страница часто — две половины подряд.
        text = text[:LANG_SCRIPT_SAMPLE] + "\n" + text[-LANG_SCRIPT_SAMPLE:]
    letters = "".join(_LETTERS.findall(text))
    if not letters:
        return "", 0.0, 0
    counts = {name: _count(_SCRIPT_RE[name], letters) for name in sorted(expected)}
    if sum(counts.values()) > len(letters) * (1 - LANG_SCRIPT_SHARE):
        script = max(counts, key=counts.get)
        return script, counts[script] / len(letters), len(letters)
    for name, rx in _SCRIPT_RE.items():
        if name not in counts:
            counts[name] = _count(rx, letters)
    script = max(counts, key=counts.get)
    return script, counts[script] / len(letters), len(letters)


# Языки с иероглифами различаются второй письменностью: японский текст без
# каны и корейский без хангыля — китайский, а кана под lang="zh" — японский.
# Японская проза — это кана в каждом предложении (частицы), корейская — хангыль.
CJK_SECOND_MIN = 0.03
CJK_KANA_IN_ZH = 0.25


def cjk_swap(text: str, expected: set) -> tuple:
    """(письмо, доля) — когда иероглифический текст написан не на объявленном языке; иначе ("", 0)."""
    if "han" not in expected:
        return "", 0.0
    text = text or ""
    if len(text) > 2 * LANG_SCRIPT_SAMPLE:
        text = text[:LANG_SCRIPT_SAMPLE] + "\n" + text[-LANG_SCRIPT_SAMPLE:]
    letters = "".join(_LETTERS.findall(text))
    if len(letters) < LANG_SCRIPT_MIN_LETTERS:
        return "", 0.0
    share = {name: _count(_SCRIPT_RE[name], letters) / len(letters)
             for name in ("han", "kana", "hangul")}
    if expected == {"han"} and share["kana"] >= CJK_KANA_IN_ZH:
        return "kana", share["kana"]
    second = ({"kana"} & expected) or ({"hangul"} & expected)
    if (len(expected) == 2 and second and share[next(iter(second))] < CJK_SECOND_MIN
            and share["han"] >= LANG_SCRIPT_SHARE):
        return "han", share["han"]
    return "", 0.0


# Страница документации, где код — заметная часть текста: английские
# идентификаторы и примеры не значат, что тело не переведено. Один `<code>`
# с номером формы на странице прозы — не документация.
CODE_SHARE = 0.2
_CODE_SPAN = re.compile(r"<(pre|code)\b[^<>]*>(.*?)</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^<>]*>")
# Где код читателю не виден и к тексту страницы не относится: комментарий,
# шаблон в <script>, скрытый блок, меню и подвал. `<pre>` в шаблоне виджета
# глушил обе проверки языка на непереведённой странице.
_UNSEEN = re.compile(r"<!--.*?-->|<(script|style|template|noscript|nav|footer|aside)(?=[\s>]).*?</\1\s*>"
                     r"|<(\w+)\b[^<>]*\s(?:hidden|aria-hidden\s*=\s*[\"']?true)(?=[\s>/=\"'])[^<>]*>"
                     r".*?</\2\s*>",
                     re.I | re.S)
_ELEMENT_LANG = re.compile(r"<(?:body|main|article|section|div)\b[^<>]*?\slang\s*=\s*[\"']?([\w-]+)",
                           re.I)


def _much_code(raw: str, prose: str) -> bool:
    """Код в `<pre>`/`<code>` — не меньше пятой части букв прозы."""
    raw = _UNSEEN.sub(" ", (raw or "")[:400_000])
    if not _CODE_TAG.search(raw):
        return False
    code = sum(len("".join(_LETTERS.findall(_TAG.sub(" ", m.group(2)))))
               for m in _CODE_SPAN.finditer(raw))
    if code == 0 and not _CODE_SPAN.search(raw):
        # Незакрытый `<pre>`: размер не измерить — как раньше, молчим.
        return True
    prose_letters = len("".join(_LETTERS.findall(prose or "")))
    return code >= CODE_SHARE * prose_letters


def lang_script(pages: list) -> list:
    """
    `lang` против письма текста. Текст — абзацы основного блока, как у проверок
    содержания: меню, подвал и примеры кода не в счёт. Судим, только когда букв
    не меньше двухсот и восемь из десяти — письмом, которым объявленный язык
    не пишется. Двуязычная страница молчит.
    """
    issues = []
    for page in sorted(pages, key=lambda p: p.url):
        expected = declared_scripts(page.lang)
        if not expected:
            continue
        prose = "\n".join(page.paragraphs or ())
        # Язык, объявленный у блока (`<main lang="de">`, `<div lang="en">`), —
        # верная разметка части страницы: текст на нём не «непереведён».
        parts = {m.group(1) for m in _ELEMENT_LANG.finditer((page.raw or "")[:400_000])}
        script, share, letters = text_script(prose, expected)
        swapped, swapped_share = cjk_swap(prose, expected)
        if swapped:
            script, share = swapped, swapped_share
        elif letters >= LANG_SCRIPT_MIN_LETTERS and script in expected:
            # Письмо то, но язык может быть другим: английский под lang="de",
            # индонезийский под lang="ms", арабский под lang="fa". Письменность
            # этого не видит, служебные слова — видят.
            from . import langid
            other = langid.mismatch(page.lang, prose)
            if other in {langid.primary(p) for p in parts}:
                other = ""
            if other and not (other == "en" and _much_code(page.raw, prose)):
                issues.append(("warning", page.url, "lang-text-mismatch", tr(
                    "страница объявляет lang=«{a0}», а текст написан на другом языке "
                    "({a1}) — похоже, тело страницы не переведено", a0=page.lang.strip(),
                    a1=other)))
            continue
        if not swapped and (letters < LANG_SCRIPT_MIN_LETTERS or share < LANG_SCRIPT_SHARE
                            or script in expected):
            continue
        # Без прозы абзацами становятся код и таблицы, а код — латиница.
        if script == "latin" and _much_code(page.raw, prose):
            continue
        if any(script in declared_scripts(p) for p in parts):
            continue
        issues.append(("warning", page.url, "lang-script-mismatch", tr(
            "страница объявляет lang=«{a0}», а {a1:.0%} букв её текста — {a2}. "
            "Поисковик и экранный диктор верят lang и прочтут страницу не на том языке",
            a0=page.lang.strip(), a1=share, a2=tr(SCRIPTS[script][0]))))
    return issues


# ── хабы ─────────────────────────────────────────────────────────────────────

# Пагинация — `page/2`, `p/2`, `page-2`, `seite/2`, `strona/2`, `страница/2`.
# Голое число (`/products/1001/`, `/archive/2019/`) — адрес страницы, а не
# номер листа: раньше такие разделы не проверялись вовсе.
_PAGINATION = re.compile(r"^(?:(?:page|seite|strona|pagina|страница)[/-]?|p/)\d+$", re.I)
# `p7` и `/plumbing/2/` (Gatsby, Astro) бывают и листом, и слагом поста;
# `/plumbing-2/` рядом с `/plumbing/` — пагинация WordPress и Jekyll, но и
# `/windows-10/` рядом с `/windows/`. Такие засчитываются, только если на них
# ведёт сам раздел или его список и они ведут к его детям. Четыре цифры —
# год или артикул, а не номер листа.
_MAYBE_PAGE = re.compile(r"^(?:p-?\d+|\d{1,3})$", re.I)
_SIBLING_PAGE = re.compile(r"^(.*[^/-])-(\d{1,4})$")
# Буква алфавитного указателя: `/plumbing/a/`, `/plumbing/letter-a/`.
_LETTER = re.compile(r"^(?:(?:letter|alpha|starts?-with|bukva|буква)[-_]?)?(?:[^\W\d_]|0-9)$",
                     re.I)


def hub_links(pages: list, graph: dict, skip: set = frozenset()) -> list:
    """
    Раздел, который не ссылается на свои страницы.

    `/plumbing/` есть, а `/plumbing/boston/` с него не связан: поисковик
    доходит до страницы через sitemap или случайную ссылку, и вес раздела до
    неё не доходит. Ссылка засчитывается и со страниц-списков раздела: их
    находит обход от хаба. Список — это лист пагинации (`/plumbing/page/2/`,
    `/plumbing-2/`), буква указателя или страница глубже детей, на которую
    ведёт хаб или другой список и чьи ссылки внутри раздела — в основном на
    детей. Размер не важен: в букве X бывает один город. Ребёнок хаба со
    своим блоком «рядом» списком не становится: такой блок есть на каждой
    странице программного сайта и прятал хаб, который ссылается на две из
    двадцати.

    Один проход по страницам: каждая встаёт под своих предков-разделов. Раньше
    каждый раздел перебирал весь сайт, и на 40 тысячах страниц это были
    одиннадцать секунд.
    """
    key_of = {p.url: p.key for p in pages}
    by_key = {key: p for p in pages for key in (key_of[p.url],)}
    inbound = graph.get("inbound") or {}
    outbound = graph.get("outbound") or {}
    children = defaultdict(list)
    for page in pages:
        if page.url in skip:
            continue
        key = key_of[page.url]
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
    # Свой ребёнок раздела с такими ссылками засчитывается, только если он
    # один: оглавление раздела — одна страница, а блок «рядом» со всеми
    # соседями стоит на каждой, и раньше с шести детей он прятал хаб, который
    # не ссылается ни на кого.
    own_tocs = defaultdict(list)
    # Чужие страницы с такими ссылками — тоже: оглавление и карта сайта. Но
    # когда их много, а общего ядра ссылок у них нет, это вращающийся блок
    # «рядом» на страницах соседнего раздела, а не оглавление.
    other_tocs = defaultdict(list)
    for page in pages:
        out = set(outbound.get(page.url, ()))
        if len(out) < 5:
            continue
        touched = Counter(hub_of[u] for u in out if u in hub_of)
        for hub_key, n in touched.items():
            if n >= max(5, 0.8 * len(kid_urls[hub_key])):
                if page.url in kid_urls[hub_key]:
                    own_tocs[hub_key].append(page.url)
                else:
                    other_tocs[hub_key].append(page.url)

    def common_core(hub_key, tocs):
        # Два вида одного списка (`/all-cities/` и `/map/`) ссылаются на одних
        # и тех же детей; блок «рядом» у каждой страницы свой.
        kids = kid_urls[hub_key]
        core = set(kids)
        for url in tocs:
            core &= set(outbound.get(url, ()))
        return len(core) >= max(5, 0.8 * len(kids))

    for hub_key, tocs in other_tocs.items():
        if len(tocs) <= 2 or common_core(hub_key, tocs):
            listing[hub_key].update(tocs)
    for hub_key, tocs in own_tocs.items():
        if len(tocs) == 1 or common_core(hub_key, tocs):
            listing[hub_key].update(tocs)
    # Кандидаты в списки: страница → «лист» (засчитывается, если ведёт хоть к
    # одному ребёнку) или «глубже» (если дети — большинство её ссылок в разделе).
    candidates = defaultdict(dict)
    pagers = set()
    for page in pages:
        key = key_of[page.url]
        cut = key.rfind("/")
        while key.count("/", 0, cut) >= 2:
            hub_key = key[:cut]
            if hub_key in hubs:
                tail = key[len(hub_key) + 1:]
                if _PAGINATION.match(tail):
                    listing[hub_key].add(page.url)
                    pagers.add(page.url)
                elif _MAYBE_PAGE.match(tail):
                    candidates[hub_key][page.url] = "pager"
                elif _LETTER.match(tail.rsplit("/", 1)[-1]):
                    candidates[hub_key][page.url] = "letter"
                elif "/" in tail:
                    candidates[hub_key][page.url] = "deeper"
            cut = key.rfind("/", 0, cut)
        sibling = _SIBLING_PAGE.match(key)
        if sibling and sibling.group(1) in hubs:
            candidates[sibling.group(1)][page.url] = "pager"
    out_sets = {}

    def out_of(url):
        found = out_sets.get(url)
        if found is None:
            found = out_sets[url] = set(outbound.get(url, ()))
        return found

    for hub_key, cands in candidates.items():
        kids = kid_urls[hub_key]
        queue = sorted(listing[hub_key])
        reached = set(queue)
        while queue:
            out = out_of(queue.pop())
            # Перебирается меньшее: оглавление на весь сайт ссылается на
            # тысячи страниц, а кандидатов у раздела обычно единицы.
            hits = ([u for u in cands if u in out] if len(cands) < len(out)
                    else [u for u in out if u in cands])
            for url in hits:
                if url in reached:
                    continue
                links = out_of(url)
                to_kids = len(links & kids)
                if not to_kids:
                    continue
                if cands[url] != "deeper" and url in kids:
                    # Ребёнок со слагом-числом или буквой (`/products/100/`,
                    # `/vitamins/c/`), который ссылается только на таких же
                    # соседей, и немногих, — это блок «похожие», а не лист.
                    same = sum(1 for u in links & kids if cands.get(u) == cands[url])
                    if same == to_kids and to_kids < 5:
                        continue
                if cands[url] == "deeper":
                    own = key_of[url]
                    own = own[:own.rfind("/") + 1]
                    # Хлебная крошка на своего предка-ребёнка
                    # (`/plumbing/city0/` у `/plumbing/city0/emergency/`) —
                    # не ссылка списка.
                    crumb = {u for u in links & kids if own.startswith(key_of[u] + "/")}
                    to_kids -= len(crumb)
                    # Соседи по уровню (другие буквы, другие листы) — навигация
                    # самого списка, а не чужие ссылки.
                    inside = sum(1 for u in links if u in key_of and u not in crumb
                                 and key_of[u].startswith(hub_key + "/")
                                 and not key_of[u].startswith(own))
                    if not to_kids or to_kids * 2 <= inside:
                        continue
                reached.add(url)
                listing[hub_key].add(url)
                queue.append(url)
                if cands[url] == "pager":
                    pagers.add(url)

    issues = []
    for hub_key, kids in sorted(hubs.items()):
        hub = by_key[hub_key]
        missing = sorted(k.url for k in kids
                         if not set(inbound.get(k.url, ())) & listing[hub_key]
                         and k.url not in pagers)
        if missing:
            shown = ", ".join(urlsplit(u).path for u in missing[:3])
            issues.append(("warning", hub.url, "hub-missing-links", Said(tr(
                "раздел не ссылается на {a0} из {a1} своих страниц: {a2}{a3} — до них "
                "доходят только через sitemap или случайные ссылки",
                a0=len(missing), a1=len(kids), a2=shown,
                a3=tr(" и ещё {a0}", a0=len(missing) - 3) if len(missing) > 3 else ""),
                [urlsplit(u).path for u in missing])))
    return issues


# ── картинки ─────────────────────────────────────────────────────────────────

def _site_folder(page) -> str:
    """
    Корень сборки по странице: её каталог минус путь URL. Все страницы в
    `/guides/`, а картинки в `/images/` — общий каталог страниц картинок не видел.
    """
    from urllib.parse import unquote
    folder = os.path.dirname(page.path)
    parts = [x for x in unquote(urlsplit(page.url).path).split("/") if x]
    if parts and parts[-1] in (os.path.basename(page.path),
                               os.path.splitext(os.path.basename(page.path))[0]):
        parts.pop()
    for part in reversed(parts):
        if os.path.basename(folder) != part:
            break
        folder = os.path.dirname(folder)
    return folder


def _inline_heavy(pages: list) -> list:
    """
    Страницы, где встроенные data:-картинки весят больше 1 МБ: их браузер
    скачивает с каждым заходом, кеш картинок им не помогает, а на диске
    файла нет — обход сборки их не видел. Иконки и спрайты в счёт не идут.
    """
    from urllib.parse import unquote
    out = []
    for page in pages:
        total, biggest, _n = page.__dict__.get("_inline_images") or (0, 0, 0)
        if total > IMAGE_LIMIT or biggest > IMAGE_LIMIT:
            out.append((total, unquote(urlsplit(page.url).path) or "/"))
    return sorted(out, key=lambda x: (-x[0], x[1]))


def heavy_images(pages: list) -> list:
    """Картинки тяжелее 1 МБ в сборке — одна находка на сайт, с самыми тяжёлыми."""
    from .subject import Said
    inline = _inline_heavy(pages)
    inline_text = ""
    if inline:
        inline_text = tr(
            "встроенных в HTML картинок (data:) больше 1 МБ на {a0} стр. — {a1}. Их браузер "
            "скачивает заново с каждой страницей; вынеси их в файлы",
            a0=len(inline), a1=", ".join(f"{path} ({size / 1024 / 1024:.1f} MB)"
                                         for size, path in inline[:5]))
    found = _heavy_files(pages)
    if not found and not inline:
        return []
    names = [name for _, name in found] + [path for _, path in inline]
    if not found:
        # Без файлов — только встроенные: совет про сжатие файлов не к месту.
        return [("info", "", "heavy-images", Said(inline_text, names))]
    shown = ", ".join(f"{name} ({size / 1024 / 1024:.1f} MB)" for size, name in found[:5])
    # Предмет — все файлы и страницы: новая тяжёлая картинка видна в --baseline.
    text = tr(
        "картинок тяжелее 1 МБ в сборке: {a0} — {a1}. Они замедляют страницу на телефоне; "
        "сожми их или отдай WebP/AVIF", a0=len(found), a1=shown)
    if inline_text:
        text += "; " + inline_text
    return [("info", "", "heavy-images", Said(text, names))]


def _heavy_files(pages: list) -> list:
    """Файлы картинок тяжелее 1 МБ: (размер, путь от корня сборки), тяжёлые первыми."""
    paths = [_site_folder(p) for p in pages if p.path and _is_html(p)]
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
    heavy.sort(key=lambda x: (-x[0], x[1]))
    return heavy
