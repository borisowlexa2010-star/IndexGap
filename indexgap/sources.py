# -*- coding: utf-8 -*-
"""
Откуда берутся списки страниц — и что каждый список на самом деле доказывает.

Панель вебмастера у человека есть не всегда, а Ahrefs, Semrush, Screaming Frog,
Serpstat, Netpeak или выгрузка из аналитики — почти у каждого. Читать их надо,
но приравнивать друг к другу нельзя: это разные утверждения о мире.

  * **Панель вебмастера** (Search Console, Bing, Яндекс, Naver, Seznam) —
    единственный прямой ответ на вопрос «знает ли поисковик про эту страницу».
    Всё остальное — косвенные признаки.
  * **Аналитика** (GA4, Matomo, Plausible, Umami, Cloudflare) — визит был,
    значит страница точно в индексе. Но только для тех страниц, куда кто-то
    зашёл: молчание аналитики не значит «нет в индексе».
  * **Краулер** (Screaming Frog, Sitebulb, JetOctopus, OnCrawl, Netpeak Spider) —
    обход, а не индекс. Краулер дошёл до страницы; поисковик мог не дойти
    или дойти и отбраковать. Полезно для достижимости, бесполезно для индексации.
  * **Сторонний индекс** (Ahrefs, Semrush, Serpstat, Moz, Similarweb) — это
    их собственный обход и их оценка, а не индекс Google. Хороший прокси
    и плохой источник истины: у Ahrefs страница может быть, а у Google нет,
    и наоборот.

Практический вывод, ради которого модуль и написан: воронку можно строить
на любом из этих источников, но подпись шага обязана меняться вместе
с источником. «Хотя бы в одном индексе» и «известно Ahrefs» — разные строки,
и подменять одну другой значит врать пользователю уверенным тоном.

Форматы читаются те, в которых эти инструменты реально отдают данные:
CSV с любым разделителем и любой кодировкой, XLSX (без сторонних библиотек —
это zip с XML внутри), JSON и NDJSON, простой список адресов в txt,
и XML-карта сайта.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import zipfile

from .core import SourceError, read_text
from .i18n import tr

# ── что источник доказывает ───────────────────────────────────────────────────

INDEX = "index"            # панель вебмастера
ANALYTICS = "analytics"    # аналитика посещений
CRAWL = "crawl"            # обход краулером
THIRDPARTY = "thirdparty"  # чужой индекс
LIST = "list"              # просто список адресов

KIND_TITLE = {
    INDEX: tr("панель вебмастера"),
    ANALYTICS: tr("аналитика"),
    CRAWL: tr("краулер"),
    THIRDPARTY: tr("сторонний индекс"),
    LIST: tr("список адресов"),
}

KIND_PROVES = {
    INDEX: tr("поисковик знает про страницу — прямой ответ"),
    ANALYTICS: tr("на страницу был визит, значит она в индексе; молчание не значит обратного"),
    CRAWL: tr("краулер дошёл до страницы — это обход, а не индексация"),
    THIRDPARTY: tr("страница есть в индексе стороннего сервиса, а не поисковика"),
    LIST: tr("просто перечень адресов — что он значит, знаешь только ты"),
}


# ── чьи бывают выгрузки ───────────────────────────────────────────────────────
#
# file: подстроки в имени файла. header: подстроки в заголовках столбцов.
# Совпадение по имени файла считается уверенным, по заголовкам — нет:
# у половины инструментов шапка «URL, Clicks, Impressions» и различить их
# нельзя, а тихо выдуманная метка сливает две выгрузки в одну.

TOOLS = {
    # панели вебмастера
    "google":        {"kind": INDEX, "title": "Google Search Console",
                      "file": ("gsc", "search-console", "searchconsole", "google"),
                      "header": ("top pages", "самые популярные страницы",
                                 "clicks", "impressions", "ctr", "position")},
    "bing":          {"kind": INDEX, "title": "Bing Webmaster Tools",
                      "file": ("bing", "bwt", "wmt", "webmaster"),
                      "header": ("avg. click position", "avg click position",
                                 "clicks", "impressions")},

    "yandex":        {"kind": INDEX, "title": tr("Яндекс.Вебмастер"),
                      "file": ("yandex", "яндекс", "вебмастер"),
                      "header": ("адрес страницы", "показы", "переходы",
                                 "статус", "последнее посещение")},
    "naver":         {"kind": INDEX, "title": "Naver Search Advisor",
                      "file": ("naver",), "header": ("링크", "주소")},
    "seznam":        {"kind": INDEX, "title": "Seznam Webmaster",
                      "file": ("seznam",), "header": ("odkaz", "stránka")},

    # аналитика
    "ga4":           {"kind": ANALYTICS, "title": "Google Analytics 4",
                      "file": ("ga4", "analytics", "googleanalytics"),
                      "header": ("page path", "landing page", "sessions",
                                 "views", "путь к странице", "сеансы")},
    "matomo":        {"kind": ANALYTICS, "title": "Matomo",
                      "file": ("matomo", "piwik"),
                      "header": ("unique pageviews", "bounce rate", "label")},
    "plausible":     {"kind": ANALYTICS, "title": "Plausible",
                      "file": ("plausible",),
                      "header": ("visitors", "pageviews", "bounce_rate")},
    "umami":         {"kind": ANALYTICS, "title": "Umami",
                      "file": ("umami",), "header": ("views", "visitors")},
    "cloudflare":    {"kind": ANALYTICS, "title": "Cloudflare Web Analytics",
                      "file": ("cloudflare",), "header": ("requests", "page views")},

    # краулеры
    "screamingfrog": {"kind": CRAWL, "title": "Screaming Frog",
                      "file": ("screamingfrog", "screaming-frog", "screaming_frog",
                               "internal_all", "internal_html"),
                      "header": ("status code", "indexability",
                                 "indexability status", "crawl depth")},
    "sitebulb":      {"kind": CRAWL, "title": "Sitebulb",
                      "file": ("sitebulb",),
                      "header": ("http status code", "crawl source",
                                 "internal url count")},
    "jetoctopus":    {"kind": CRAWL, "title": "JetOctopus",
                      "file": ("jetoctopus",), "header": ("crawl", "status_code")},
    "oncrawl":       {"kind": CRAWL, "title": "OnCrawl",
                      "file": ("oncrawl",), "header": ("urlpath", "fetched")},
    "netpeak":       {"kind": CRAWL, "title": "Netpeak Spider",
                      "file": ("netpeak",), "header": ("код ответа", "глубина")},
    "sitemap":       {"kind": CRAWL, "title": tr("карта сайта"),
                      "file": ("sitemap",), "header": ()},

    # сторонние индексы
    "ahrefs":        {"kind": THIRDPARTY, "title": "Ahrefs",
                      "file": ("ahrefs",),
                      "header": ("url rating", "domain rating", "traffic value",
                                 "current url", "keywords count", "top keyword")},
    "semrush":       {"kind": THIRDPARTY, "title": "Semrush",
                      "file": ("semrush",),
                      "header": ("traffic (%)", "number of keywords",
                                 "traffic cost", "page url")},

    "serpstat":      {"kind": THIRDPARTY, "title": "Serpstat",
                      "file": ("serpstat",), "header": ("потенциальный трафик",)},
    "moz":           {"kind": THIRDPARTY, "title": "Moz",
                      "file": ("moz",), "header": ("page authority", "spam score")},
    "similarweb":    {"kind": THIRDPARTY, "title": "Similarweb",
                      "file": ("similarweb",), "header": ()},
    "keyso":         {"kind": THIRDPARTY, "title": "Keys.so",
                      "file": ("keyso", "keys.so"), "header": ("ключей у страницы",)},
}

# Заголовки, которые встречаются у всех и потому ничего не различают.
GENERIC_HEADERS = frozenset({
    "url", "page", "адрес", "страница", "страницы", "link", "ссылка",
    "path", "views", "clicks", "sessions", "crawl",
})

# Колонка с адресом. Инструментов много, слов для «страницы» — тоже.
URL_COLUMN_HINTS = (
    "url", "страниц", "page", "адрес", "address", "top pages", "landing",
    "current url", "final url", "destination", "путь", "path", "loc",
    "link", "ссылка", "링크", "주소", "odkaz", "stránka", "ページ", "网址",
)

# Колонка с ключевым словом — для `plan`, где датасет тоже приходит
# из Ahrefs, Semrush, Wordstat или Keys.so, а не только из своей таблицы.
KEYWORD_COLUMN_HINTS = (
    "keyword", "ключ", "запрос", "query", "фраза", "phrase", "search term",
    "поисковый запрос", "term", "kw",
)


def guess_column(header: list, hints: tuple) -> int:
    """Номер столбца, чей заголовок похож на нужный. -1, если непохож никакой."""
    lowered = [str(h or "").strip().lower() for h in header]
    for i, name in enumerate(lowered):
        if name in hints:                       # точное совпадение важнее
            return i
    for i, name in enumerate(lowered):
        if any(hint in name for hint in hints):
            return i
    return -1


# ── чтение таблиц ─────────────────────────────────────────────────────────────

_SHEET_RE = re.compile(r"xl/worksheets/sheet\d+\.xml$")
_XML_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _read_xlsx(path: str) -> list:
    """
    XLSX без сторонних библиотек: это zip с XML внутри.

    Ahrefs, Semrush и Screaming Frog по умолчанию отдают xlsx, и раньше
    пакет на него просто ругался «распакуй сам». Человек, который не
    программирует, на этом и заканчивал.
    """
    try:
        with zipfile.ZipFile(path) as book:
            names = book.namelist()
            shared = []
            if "xl/sharedStrings.xml" in names:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(book.read("xl/sharedStrings.xml"))
                for si in root:
                    shared.append("".join(t.text or "" for t in si.iter(_XML_NS + "t")))
            sheets = sorted(n for n in names if _SHEET_RE.search(n))
            if not sheets:
                raise SourceError(tr("{a0}: в книге нет ни одного листа.", a0=path))
            import xml.etree.ElementTree as ET
            root = ET.fromstring(book.read(sheets[0]))
            rows = []
            for row in root.iter(_XML_NS + "row"):
                values = []
                for cell in row.iter(_XML_NS + "c"):
                    kind = cell.get("t")
                    if kind == "inlineStr":
                        node = cell.find(_XML_NS + "is")
                        text = "".join(t.text or "" for t in node.iter(_XML_NS + "t")) \
                            if node is not None else ""
                    else:
                        node = cell.find(_XML_NS + "v")
                        text = node.text if node is not None and node.text else ""
                        if kind == "s" and text.isdigit():
                            index = int(text)
                            text = shared[index] if index < len(shared) else ""
                    values.append(text)
                rows.append(values)
            return rows
    except zipfile.BadZipFile:
        raise SourceError(
            tr("{a0}: файл начинается как zip-архив, но не открывается ни как xlsx, ни как книга Excel. Если это архив выгрузки — распакуй его и передай файл изнутри; если книга — пересохрани её или отдай CSV.", a0=path))


def _read_lines(text: str) -> list:
    """Простой список адресов: по одному в строке."""
    return [[line.strip()] for line in text.splitlines() if line.strip()]


def _read_json(text: str) -> list:
    """
    JSON или NDJSON. Ищем словари с полем-адресом, иначе — строки-адреса.
    Возвращаем таблицу, чтобы дальше работал общий путь.
    """
    data = None
    try:
        data = json.loads(text)
    except ValueError:
        items = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except ValueError:
                return []
        data = items
    if isinstance(data, dict):
        for key in ("pages", "rows", "items", "results", "data", "urls"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list) or not data:
        return []
    if all(isinstance(x, str) for x in data):
        return [[x] for x in data]
    keys = []
    for item in data:
        if isinstance(item, dict):
            for k in item:
                if k not in keys:
                    keys.append(k)
    if not keys:
        return []
    return [keys] + [[str(item.get(k, "")) for k in keys]
                     for item in data if isinstance(item, dict)]


def _read_xml_locs(text: str) -> list:
    locs = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", text)
    return [[u] for u in locs]


def read_table(path: str) -> tuple:
    """
    Любой из живых форматов → (строки, кодировка).

    Порядок проверок идёт от подписи файла к расширению, а не наоборот:
    выгрузку из Ahrefs люди регулярно сохраняют как `.csv`, будучи xlsx.
    """
    if not os.path.exists(path):
        raise SourceError(tr("Файл не найден: {a0}", a0=path))
    if os.path.isdir(path):
        raise SourceError(tr("{a0} — это каталог, а нужен файл выгрузки.", a0=path))

    with open(path, "rb") as fh:
        head = fh.read(4)
    if head[:2] == b"PK":
        return _read_xlsx(path), "xlsx"

    text, encoding = read_text(path)
    stripped = text.lstrip()
    lower = path.lower()

    if stripped[:1] in "[{" or lower.endswith((".json", ".ndjson", ".jsonl")):
        rows = _read_json(text)
        if rows:
            return rows, encoding
    if stripped[:1] == "<" or lower.endswith(".xml"):
        rows = _read_xml_locs(text)
        if rows:
            return rows, encoding

    first = text.splitlines()[0] if text.strip() else ""
    if not any(ch in first for ch in ",;\t|"):
        return _read_lines(text), encoding

    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(io.StringIO(text, newline=""), dialect)), encoding


# ── чей это файл ──────────────────────────────────────────────────────────────

def identify(path: str, header: list) -> tuple:
    """
    Возвращает (имя, вид, уверенно ли).

    Имя файла — сильный признак: человек сам назвал файл `ahrefs-pages.csv`.
    Заголовки — слабый: у панели вебмастера и у стороннего сервиса они
    совпадают почти дословно. При ничьей честный ответ — «не знаю»:
    выдуманная метка сливает две выгрузки в одну и убивает сравнение,
    ради которого отчёт и строится.
    """
    name = os.path.basename(path).lower()
    for tool, meta in TOOLS.items():
        if any(hint in name for hint in meta["file"]):
            return tool, meta["kind"], True

    lowered = {str(h or "").strip().lower() for h in (header or [])}
    scores = {}
    for tool, meta in TOOLS.items():
        # Универсальные слова не голосуют: «url» и «page» есть в любой выгрузке,
        # и на живом JSON из двух полей `url, status` они уверенно назначали
        # файл краулером Sitebulb. Решают только различающие заголовки.
        hints = tuple(h for h in meta["header"] if h not in GENERIC_HEADERS)
        if not hints:
            continue
        score = sum(1 for h in lowered if any(hint in h for hint in hints))
        # Точное совпадение редкого заголовка весит больше общего вхождения.
        score += sum(1 for hint in hints if hint in lowered)
        if score:
            scores[tool] = score
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked or ranked[0][1] < 2:
        return "", "", False
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return "", "", False
    return ranked[0][0], TOOLS[ranked[0][0]]["kind"], False


def kind_of(name: str) -> str:
    """Вид источника по его имени. Незнакомое имя — просто список адресов."""
    meta = TOOLS.get((name or "").lower())
    return meta["kind"] if meta else LIST


def title_of(name: str) -> str:
    meta = TOOLS.get((name or "").lower())
    return meta["title"] if meta else name


def parse_spec(spec: str) -> tuple:
    """
    `google=exports/gsc.csv` -> ("google", "exports/gsc.csv")
    `ahrefs=pages.xlsx`      -> ("ahrefs", "pages.xlsx")
    `exports/bing.csv`       -> ("", "exports/bing.csv") — определим сами
    """
    if "=" in spec:
        name, _, path = spec.partition("=")
        name = name.strip().lower()
        if name and not os.path.exists(name):     # защита от путей вида C:=...
            return name, path.strip()
    return "", spec.strip()


def describe(names: list) -> list:
    """Что каждый переданный источник на самом деле доказывает."""
    lines, seen = [], set()
    for name in names:
        kind = kind_of(name)
        if kind in seen:
            continue
        seen.add(kind)
        lines.append(f"{KIND_TITLE[kind]}: {KIND_PROVES[kind]}")
    return lines


def index_grade(names: list) -> str:
    """
    Какой подписью честно назвать шаг воронки при таком наборе источников.
    """
    kinds = {kind_of(n) for n in names if n}
    if not kinds:
        return ""
    if kinds == {INDEX}:
        return tr("Хотя бы в одном индексе")
    if kinds <= {INDEX, ANALYTICS}:
        return tr("Известно поисковику или было посещено")
    if kinds == {CRAWL}:
        return tr("Найдено краулером (это обход, а не индекс)")
    if kinds == {THIRDPARTY}:
        return tr("Известно стороннему сервису (не индекс поисковика)")
    return tr("Есть хотя бы в одном источнике")
