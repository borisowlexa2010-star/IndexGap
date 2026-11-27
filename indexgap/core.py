# -*- coding: utf-8 -*-
"""
Загрузка и разбор страниц конвейера. Только стандартная библиотека.

Понимает два вида входа:
  * каталог с .html — то, что реально уедет на прод;
  * каталог с .md   — исходники до сборки (frontmatter + текст).

Из каждой страницы вытаскивается ровно то, что нужно проверкам:
URL, title, description, canonical, robots, текст без разметки и внутренние ссылки.

Два правила, на которых держится всё остальное:

  * **URL страницы и ссылка на неё должны сходиться.** Поэтому сравнение идёт
    не по строке, а по ключу `url_key`: снимается процент-кодирование,
    расширение, `index.html` и хвостовой слеш. Без этого сайт из плоских
    html-файлов целиком объявляется сиротами.
  * **Файл может быть не в UTF-8.** Блокнот, Excel и экспорт из панелей
    отдают cp1251 и UTF-16. Молча прочитать их «с заменой» — значит выдать
    неверный вердикт, поэтому кодировка определяется, а не предполагается.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from array import array
from collections import Counter, defaultdict
from html import unescape as html_unescape
from html.parser import HTMLParser
from urllib.parse import (urljoin, urldefrag, urlsplit, urlunsplit,
                          quote, unquote)

from .i18n import tr
from . import __version__

# Без заголовка urllib шлёт `Python-urllib/3.x`, и многие WAF режут такой агент
# по умолчанию: sitemap живого сайта сообщества отдавал пакету 403, а curl — 200. Под
# браузер пакет не маскируется — сайт вправе знать, кто пришёл, и отказать.
USER_AGENT = f"indexgap/{__version__} (+https://github.com/borisowlexa2010-star/IndexGap)"


def request(url: str, **kwargs):
    """urllib.request.Request, который представляется именем пакета."""
    import urllib.request
    headers = dict(kwargs.pop("headers", None) or {})
    headers.setdefault("User-Agent", USER_AGENT)
    return urllib.request.Request(url, headers=headers, **kwargs)

# Содержимое этих тегов не является текстом страницы и не содержит ссылок,
# по которым ходит краулер. `template` и `noscript` тоже: ссылка внутри
# шаблона не существует, пока её не отрендерит скрипт.
SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}

# Что может стоять в <head>. Любой другой открывающий тег начинает <body>, даже
# если самого <body> нет: HTML5 разрешает его опускать, и минификаторы опускают.
HEAD_TAGS = {"html", "head", "base", "basefont", "bgsound", "link", "meta",
             "noframes", "script", "style", "template", "title", "noscript"}

# Инлайновые теги не разрывают слово: «Виза<b>free</b>» — одно слово.
# Ссылок и подписей здесь нет намеренно: два соседних <a> — это два разных
# пункта, и склеивать их в «словослово» нельзя.
INLINE_TAGS = {"b", "i", "em", "strong", "code", "small", "sub", "sup",
               "mark", "u", "s", "abbr", "var", "kbd", "font", "big", "tt"}

# Теги без закрывающей пары: они не открывают основной блок и не меняют глубину.
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}

# Имена мета-тегов, которые значат одно и то же.
META_ALIASES = {
    "article:published_time": "datepublished",
    "article:modified_time": "datemodified",
    "og:updated_time": "datemodified",
    "date": "datepublished",
    "pubdate": "datepublished",
    "last-modified": "datemodified",
    "article:author": "author",
    "og:site_name": "publisher",
}

# Разделы, которые считаются основным содержимым. Если такой на странице есть,
# меню и подвал в текст не попадают — иначе «одинаковое начало текста»
# срабатывает на каждой странице любого сайта с навигацией.
MAIN_TAGS = {"main", "article"}

# Служебные файлы самого пакета: разбирать их как страницы сайта нельзя.
# Каталог нарядов и метка отчёта: своё пакет страницами не считает. Иначе
# после `brief --write` каждая команда начиналась с жалобы на собственные
# файлы, а отчёт, сохранённый в каталог сайта, становился сиротой.
OWN_DIRS = {"indexgap-briefs"}
REPORT_MARK = "<!-- indexgap-report -->"

OWN_FILES = {"indexgap-report.html", "indexgap-report.json", "indexgap-check.html",
             "indexgap-check.json", "indexgap-doctor.html", "indexgap-doctor.json",
             "indexgap-diff.html", "indexgap-diff.json"}

# Каталоги сборки пропускаются: иначе `indexgap check .` в обычном репозитории
# статического генератора разбирает и исходники, и собранный сайт, и каждая
# страница оказывается собственным почти-дублем.
# Служебное на любой глубине: это никогда не раздел сайта.
ALWAYS_SKIP = {"node_modules", ".git", ".svn", "__pycache__", ".next", ".nuxt",
               ".venv", "venv", ".output", ".vercel", ".astro"}
# Куда генераторы кладут сборку. Пропускаются только в корне проекта с
# исходниками: внутри готового сайта `vendor`, `coverage`, `build`, `public` —
# обычные слова, и раньше такие разделы исчезали молча.
BUILD_DIRS = {"vendor", "public", "_site", "dist", "build", "out", "target",
              "coverage"}
SKIP_DIRS = ALWAYS_SKIP | BUILD_DIRS
# По чему видно, что перед нами проект с исходниками, а не готовый сайт.
SOURCE_MARKERS = ("package.json", "pyproject.toml", "Gemfile", "go.mod",
                  "Cargo.toml", "composer.json", "hugo.toml", "hugo.yaml",
                  "config.toml", "_config.yml", "astro.config.mjs", "Makefile",
                  ".git")
# Репозиторий — ещё не генератор: сайт на чистом HTML с GitHub Pages лежит в
# корне репозитория, и `/team/` при `team.html` там — 404.
_REPO_ONLY_MARKERS = (".git", "Makefile")

DEFAULT_EXTS = (".html", ".htm", ".md", ".markdown")


class SourceError(Exception):
    """Файл невозможно прочитать. Сообщение адресовано человеку, не разработчику."""


# Потолок на всё, что читается целиком в память: sitemap, выгрузка, лист книги.
# Протокол sitemap разрешает 50 МБ; вдвое больше — запас, а не приглашение.
# Без потолка архив в сто килобайт разворачивался в сотни мегабайт.
MAX_INPUT_BYTES = 100 * 1024 * 1024


def too_big(size: int) -> bool:
    return size > MAX_INPUT_BYTES


def gunzip(data: bytes) -> bytes:
    """Распаковка с потолком. Бросает SourceError, а не трейсбек zlib."""
    import gzip
    import io
    import zlib
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as fh:
            out = fh.read(MAX_INPUT_BYTES + 1)
    except (OSError, EOFError, zlib.error) as exc:
        raise SourceError(tr("не удалось распаковать gzip ({a0})", a0=exc))
    if too_big(len(out)):
        raise SourceError(tr("после распаковки больше {a0} МБ — читать не стал",
                             a0=MAX_INPUT_BYTES // (1024 * 1024)))
    return out


def parse_xml(data):
    """
    XML без объявления типа документа.

    Ни sitemap, ни лист xlsx в DTD не нуждаются, а раздувание сущностей живёт
    именно там: на Python 3.9 со старым expat файл в 494 байта давал строку
    в сто миллионов символов. Проще не читать такой документ вовсе.
    """
    from xml.etree import ElementTree
    if isinstance(data, str):
        data = data.encode("utf-8")
    probe = data[:65536].replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in probe or b"<!ENTITY" in probe:
        raise SourceError(tr("в XML объявлен DOCTYPE — такой файл не читается: "
                             "ни sitemap, ни выгрузке он не нужен"))
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise SourceError(tr("это не похоже на XML ({a0})", a0=exc))


# Иероглифы и кана: слово — это знак, пробелов между словами нет.
_CJK = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
# Знаки, которые входят в слово, но буквой не считаются: огласовки арабского и
# иврита, матры и вирама индийских письменностей, соединители. `\w` их не
# берёт, и «थाईलैंड» распадалось на четыре куска — счётчик слов на хинди и
# бенгали завышался вдвое, а сравнение страниц шло по обломкам.
# Знаки, которые Python не считает буквами, а письменность — частью слова.
# Тайские, лаосские, кхмерские и бирманские гласные и тоны: без них
# «กรุงเทพ» резалось на «กร» и «งเทพ».
_MARKS = ("\u0300-\u036f\u0591-\u05c7\u064b-\u065f\u0670\u06d6-\u06ed"
          "\u0900-\u0963\u0966-\u0dff\u0e00-\u0eff\u0f00-\u0fff\u1000-\u109f"
          "\u1780-\u17ff\u200c\u200d")
_TOKEN = re.compile(f"[{_CJK}]|(?:(?![{_CJK}])[\\w{_MARKS}])+", re.UNICODE)


def tokenize(text: str) -> list:
    """
    Слова текста. Для письменностей с пробелами — слова целиком, вместе с
    диакритикой; для иероглифики — по знаку: фраза без пробелов была одним
    «словом», и две одинаковые китайские страницы не сравнивались вовсе.
    """
    # Слова интернируются: словарь сайта мал, а копий слов — миллионы.
    return list(map(sys.intern, _TOKEN.findall((text or "").lower())))


def is_dense(words: list) -> bool:
    """Преобладает ли в тексте иероглифика (слово — один знак)."""
    if not words:
        return False
    sample = words[:400]
    return sum(1 for w in sample if len(w) == 1 and "\u3040" <= w <= "\ufaff") * 2 > len(sample)


# \u2500\u2500 \u0410\u0431\u0437\u0430\u0446\u044b \u043a\u0430\u043a \u043a\u0443\u0441\u043a\u0438 \u0442\u0435\u043a\u0441\u0442\u0430 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
#
# \u0410\u0431\u0437\u0430\u0446\u044b \u2014 \u043f\u043e\u0447\u0442\u0438 \u0442\u043e\u0442 \u0436\u0435 \u043e\u0441\u043d\u043e\u0432\u043d\u043e\u0439 \u0442\u0435\u043a\u0441\u0442 \u0432\u0442\u043e\u0440\u043e\u0439 \u0440\u0430\u0437: \u043d\u0430 \u0441\u0430\u0439\u0442\u0435 \u0432 \u0442\u0440\u0438 \u0442\u044b\u0441\u044f\u0447\u0438
# \u0441\u0442\u0440\u0430\u043d\u0438\u0446 \u044d\u0442\u043e \u0441\u043e\u0442\u043d\u044f-\u043f\u043e\u043b\u0442\u043e\u0440\u044b \u043c\u0435\u0433\u0430\u0431\u0430\u0439\u0442. \u041f\u043e\u044d\u0442\u043e\u043c\u0443 \u0430\u0431\u0437\u0430\u0446 \u0445\u0440\u0430\u043d\u0438\u0442\u0441\u044f \u043a\u0430\u043a \u043a\u0443\u0441\u043a\u0438
# `text`, \u0430 \u0441\u0442\u0440\u043e\u043a\u043e\u0439 \u2014 \u0442\u043e\u043b\u044c\u043a\u043e \u0442\u043e\u0442, \u0447\u0442\u043e \u0432 \u0442\u0435\u043a\u0441\u0442\u0435 \u043d\u0435 \u043d\u0430\u0448\u0451\u043b\u0441\u044f. \u0420\u0430\u0437\u043d\u0438\u0446\u0430 \u0431\u044b\u0432\u0430\u0435\u0442
# \u043e\u0434\u043d\u0430: \u0430\u0431\u0437\u0430\u0446 \u0441\u043a\u043b\u0435\u0438\u0432\u0430\u0435\u0442 \u043a\u0443\u0441\u043a\u0438 \u0440\u0430\u0437\u043c\u0435\u0442\u043a\u0438 \u0447\u0435\u0440\u0435\u0437 \u043f\u0440\u043e\u0431\u0435\u043b, \u0430 \u0442\u0435\u043a\u0441\u0442 \u2014 \u0432\u043f\u0440\u0438\u0442\u044b\u043a
# (`link</a>, more` \u2014 \u0432 \u0442\u0435\u043a\u0441\u0442\u0435 \u00ablink, more\u00bb, \u0432 \u0430\u0431\u0437\u0430\u0446\u0435 \u00ablink , more\u00bb).
# \u0421\u0431\u043e\u0440\u043a\u0430 \u0442\u043e\u0447\u043d\u0430 \u043f\u043e \u043f\u043e\u0441\u0442\u0440\u043e\u0435\u043d\u0438\u044e: \u043a\u0443\u0441\u043a\u0438 \u0440\u0430\u0432\u043d\u044b \u043e\u0442\u0440\u0435\u0437\u043a\u0430\u043c \u0430\u0431\u0437\u0430\u0446\u0430, \u043c\u0435\u0436\u0434\u0443 \u043d\u0438\u043c\u0438 \u2014 \u0435\u0433\u043e
# \u0436\u0435 \u043f\u0440\u043e\u0431\u0435\u043b\u044b.

def _span_walk(p: str, text: str, j: int):
    """\u0410\u0431\u0437\u0430\u0446 `p` \u043a\u0430\u043a \u043a\u0443\u0441\u043a\u0438 `text` \u0441 \u043f\u043e\u0437\u0438\u0446\u0438\u0438 `j`: [\u043d\u0430\u0447\u0430\u043b\u043e, \u043a\u043e\u043d\u0435\u0446, ...] \u0438\u043b\u0438 None."""
    out = []
    i, n = 0, len(p)
    while True:
        if text.startswith(p[i:], j):
            size = n - i
        else:
            # \u0421\u0430\u043c\u043e\u0435 \u0434\u043b\u0438\u043d\u043d\u043e\u0435 \u043e\u0431\u0449\u0435\u0435 \u043d\u0430\u0447\u0430\u043b\u043e: startswith \u043c\u043e\u043d\u043e\u0442\u043e\u043d\u0435\u043d \u043f\u043e \u0434\u043b\u0438\u043d\u0435.
            lo, hi = 0, n - i
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if text.startswith(p[i:i + mid], j):
                    lo = mid
                else:
                    hi = mid
            size = lo
        if not size:
            return None
        out += (j, j + size)
        i += size
        j += size
        if i == n:
            return out
        if p[i] != " ":
            return None
        i += 1


def _span_find(p: str, text: str, pos: int):
    # \u0418\u0449\u0435\u0442\u0441\u044f \u043f\u0435\u0440\u0432\u043e\u0435 \u0441\u043b\u043e\u0432\u043e, \u0430 \u043d\u0435 \u0430\u0431\u0437\u0430\u0446 \u0446\u0435\u043b\u0438\u043a\u043e\u043c: \u0430\u0431\u0437\u0430\u0446 \u0441\u043e \u0441\u043a\u043b\u0435\u0439\u043a\u043e\u0439 \u0432 \u0442\u0435\u043a\u0441\u0442\u0435
    # \u043d\u0435 \u043d\u0430\u0439\u0434\u0451\u0442\u0441\u044f, \u0438 \u043f\u043e\u0438\u0441\u043a \u0434\u0432\u0430\u0436\u0434\u044b \u043f\u0440\u043e\u0448\u0451\u043b \u0431\u044b \u0432\u0435\u0441\u044c \u0442\u0435\u043a\u0441\u0442 \u0432\u043f\u0443\u0441\u0442\u0443\u044e.
    head = p.split(" ", 1)[0]
    for start in (pos, 0) if pos else (0,):
        j = text.find(head, start)
        # \u041f\u0435\u0440\u0432\u043e\u0435 \u0441\u043b\u043e\u0432\u043e \u0432\u0441\u0442\u0440\u0435\u0447\u0430\u0435\u0442\u0441\u044f \u0438 \u0440\u0430\u043d\u044c\u0448\u0435 \u0430\u0431\u0437\u0430\u0446\u0430; \u0434\u0430\u043b\u044c\u0448\u0435 \u043f\u0430\u0440\u044b \u043f\u043e\u043f\u044b\u0442\u043e\u043a \u043d\u0435 \u0438\u0449\u0435\u043c.
        for _ in range(4):
            if j < 0:
                break
            found = _span_walk(p, text, j)
            if found:
                return found
            j = text.find(head, j + 1)
    return None


def _pack_paragraphs(text: str, paragraphs) -> tuple:
    """(text, \u043a\u0443\u0441\u043a\u0438, \u0441\u0442\u0440\u043e\u043a\u0438): \u043d\u0430 \u0430\u0431\u0437\u0430\u0446 \u2014 \u0447\u0438\u0441\u043b\u043e \u043a\u0443\u0441\u043a\u043e\u0432 \u0438 \u0438\u0445 \u0433\u0440\u0430\u043d\u0438\u0446\u044b; 0 \u2014 \u0441\u0442\u0440\u043e\u043a\u0430."""
    spans = array("L")
    loose = []
    pos = 0
    for p in paragraphs:
        found = _span_find(p, text, pos) if p and text else None
        if found is None:
            spans.append(0)
            spans.append(len(loose))
            loose.append(p)
            continue
        spans.append(len(found) // 2)
        spans.extend(found)
        pos = found[-1]
    return text, spans, loose


def _unpack_paragraphs(packed) -> list:
    text, spans, loose = packed
    out = []
    k, end = 0, len(spans)
    while k < end:
        count = spans[k]
        if not count:
            out.append(loose[spans[k + 1]])
            k += 2
            continue
        if count == 1:
            out.append(text[spans[k + 1]:spans[k + 2]])
        else:
            out.append(" ".join(text[spans[x]:spans[x + 1]]
                                for x in range(k + 1, k + 1 + 2 * count, 2)))
        k += 1 + 2 * count
    return out


@dataclass
class Page:
    path: str                      # путь к файлу на диске
    url: str                       # абсолютный URL на проде
    title: str = ""
    description: str = ""
    canonical: str = ""            # абсолютный, уже приведённый к URL страницы
    robots: str = ""
    text: str = ""                 # основной текст без разметки, без меню и подвала
    chrome: str = ""               # то, что осталось за пределами основного текста
    framed: str = ""               # без <main>: текст внутри <header>, <footer>, <nav>, <aside>
    links: list = field(default_factory=list)   # внутренние ссылки (абсолютные URL)
    lang: str = ""
    meta: dict = field(default_factory=dict)   # фронтматтер целиком, если он был
    headings: list = field(default_factory=list)   # (уровень, текст) в порядке следования
    anchors: list = field(default_factory=list)    # тексты внутренних ссылок
    raw: str = ""                                  # исходник как есть
    encoding: str = "utf-8"                        # в какой кодировке файл прочитан
    notes: list = field(default_factory=list)      # то, что разбор хочет сказать вслух
    jsonld: list = field(default_factory=list)     # сырые блоки application/ld+json
    paragraphs: list = field(default_factory=list) # абзацы основного текста
    blocks: dict = field(default_factory=dict)     # счётчики li/table/img и т.п.
    alternates: list = None                        # hreflang: (код, href); None — не собирались
    alternates_in_body: int = 0                    # hreflang-ссылок в <body>: не считаются
    outline: list = None                           # заголовки без шаблона: вне <aside>, <footer>, <nav>
    slots: list = None                             # следы незаполненного шаблона: (вид, образец)
    alts: list = field(default_factory=list)       # непустые alt картинок: (текст, src)
    # Текст, который читатель видит: без блоков с `hidden` и `display:none`.
    # None — скрытых блоков нет, видно всё, что в text и chrome.
    shown: str = None
    # Цены микроданных и RDFa с машинным значением: (поле, значение). Только
    # те, где значение задано атрибутом (`content`, `value`), а не текстом
    # элемента: текст элемента и так виден. Только внутри `itemscope`,
    # `typeof` или `vocab`: вне элемента-сущности поисковик их не читает.
    microdata: list = field(default_factory=list)
    # Служебные блоки основного текста: крошки, подпись автора, оглавление.
    # Абзацами они не становятся, но в text остаются.
    service: list = field(default_factory=list)

    @property
    def key(self) -> str:
        """Ключ для сравнения с любой ссылкой на эту страницу."""
        return url_key(self.url)

    @property
    def words(self) -> list:
        # Слова считаются один раз: за прогон их спрашивали десятки тысяч раз,
        # и каждый раз текст разбирался заново. Новый текст — новый разбор.
        cached = self.__dict__.get("_words")
        if cached is None or cached[0] is not self.text:
            cached = (self.text, tokenize(self.text))
            self.__dict__["_words"] = cached
        return cached[1]

    @property
    def word_count(self) -> int:
        return len(self.words)

    @property
    def noindex(self) -> bool:
        """`none` — это синоним `noindex, nofollow`, и Google его понимает."""
        directives = re.split(r"[,\s]+", (self.robots or "").lower())
        return "noindex" in directives or "none" in directives

    @property
    def nofollow(self) -> bool:
        """Ссылки страницы краулер не проходит: `nofollow` или `none` в robots."""
        directives = re.split(r"[,\s]+", (self.robots or "").lower())
        return "nofollow" in directives or "none" in directives

    @property
    def nosnippet(self) -> bool:
        """Без права на сниппет страница не попадёт в ответы ИИ-поиска."""
        value = (self.robots or "").lower()
        if "nosnippet" in re.split(r"[,\s]+", value):
            return True
        return bool(re.search(r"max-snippet\s*:\s*0(?!\d)", value))

    @property
    def content_hash(self) -> str:
        """
        Меняется тогда и только тогда, когда меняется то, что видит поисковик.

        Считается по основному тексту, заголовку и описанию — но не по меню
        и подвалу: иначе правка одного пункта навигации помечает изменившимся
        весь сайт и отправляет его в IndexNow целиком.
        """
        payload = "\x00".join([
            (self.title or "").strip(),
            (self.description or "").strip(),
            # Хэш держится на прежнем, простом разборе слов. Разбор для
            # сравнения страниц стал точнее, но менять вместе с ним хэш нельзя:
            # обновление пакета сдвинуло бы `lastmod` у каждой страницы на
            # хинди и китайском и отправило бы их в IndexNow заново.
            " ".join(re.findall(r"\w+", (self.text or "").lower(), flags=re.UNICODE)),
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# Поле `paragraphs` остаётся полем dataclass (конструктор, сравнение, repr),
# но хранится сжатым: см. `_pack_paragraphs`. Чтение собирает новый список —
# менять его на месте бесполезно, только присваивать. Сжатое держит ссылку
# на свой текст: замена `text` абзацы не сдвигает, а pickle пишет текст один раз.
def _get_paragraphs(self) -> list:
    packed = self.__dict__.get("_para")
    return _unpack_paragraphs(packed) if packed else []


def _set_paragraphs(self, value):
    value = list(value or ())
    self.__dict__["_para"] = (_pack_paragraphs(self.__dict__.get("text") or "", value)
                              if value else None)


Page.paragraphs = property(_get_paragraphs, _set_paragraphs)


# ── URL ───────────────────────────────────────────────────────────────────────

_EXT_RE = re.compile(r"\.(html?|md|markdown)$", re.I)
_BARE_INDEX = re.compile(r"(^|/)index$", re.I)
_INDEX_RE = re.compile(r"(^|/)index\.(html?|md|markdown)$", re.I)
# Hugo: `_index.md` — страница раздела (`content/posts/_index.md` — /posts/),
# в корне — главная. Адреса `/_index/` на сайте нет.
_HUGO_INDEX = re.compile(r"(^|/)_index\.(md|markdown)$", re.I)


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


@functools.lru_cache(maxsize=1 << 18)
def url_key(url: str) -> str:
    """
    Приводит адрес к форме, в которой ссылка и страница сравнимы.

    `/about.html`, `/about/`, `/about`, `/about/index.html` и `/%D0%BE`
    в процент-кодировании — это один и тот же адрес. Сравнение по сырой
    строке даёт «сироту» на каждой странице обычного статического сайта.
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        # `https://x.org][1` — недописанная ссылка Markdown: `urlsplit` видит
        # в ней IPv6 и бросает ValueError. Одна такая ссылка роняла прогон
        # на 47 тысяч страниц.
        return ""
    path = unicodedata.normalize("NFC", unquote(parts.path or "/"))
    # `{{base}}/{{slug}}` в шаблоне даёт `/guides//visa/`. Сервер такую страницу
    # отдаёт, а сравнение по сырой строке объявляло её сиротой.
    path = re.sub(r"/{2,}", "/", path)
    # Управляющие символы остаются закодированными. Адрес приходит и из чужих
    # выгрузок, а ключ печатается: `%0a::error file=…` после раскодирования
    # становился отдельной строкой вывода — командой для GitHub Actions.
    if _CONTROL.search(path):
        path = _CONTROL.sub(lambda m: "%%%02X" % ord(m.group()), path)
    path = _INDEX_RE.sub(r"\1", path)
    path = _EXT_RE.sub("", path)
    # `/resource/index` без расширения — та же страница: VitePress с
    # cleanUrls ссылается так на каждой странице, и вышло 307 «битых» ссылок.
    if len(path) > 1:
        path = path.rstrip("/")
    path = _BARE_INDEX.sub(r"\1", path)
    if len(path) > 1:
        path = path.rstrip("/")
    if not path:
        path = "/"
    host = (parts.netloc or "").lower()
    # Кириллический домен и его punycode — один хост: ссылка на
    # `xn--e1afmkfd.xn--p1ai` с сайта `пример.рф` считалась внешней.
    if not host.isascii():
        try:
            name, sep, port = host.partition(":")
            host = name.encode("idna").decode("ascii") + sep + port
        except UnicodeError:
            pass
    # Порт по умолчанию — это тот же адрес: `example.com:443` и `example.com`
    # различались, и страница молча выпадала из sitemap по «чужому» canonical.
    for scheme, port in (("https", ":443"), ("http", ":80")):
        if host.endswith(port) and (not parts.scheme or parts.scheme == scheme):
            host = host[: -len(port)]
    if host.startswith("www."):
        host = host[4:]
    query = parts.query
    return urlunsplit(("", host, path, query, ""))


@functools.lru_cache(maxsize=1 << 18)
def normalize_url(url: str, directory: bool = None) -> str:
    """
    Каноническая форма для вывода.

    `directory=True` — адрес заведомо каталожный (мы сами сняли расширение),
    и слеш ставится всегда. Иначе решаем по последнему сегменту. Без явного
    флага slug вида `v2.0` или `gost-12.4.011` терял слеш, и в одном sitemap
    оказывались две формы адреса — гарантированный 301 прямо из карты сайта.
    """
    parts = urlsplit(url)
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    last = path.rsplit("/", 1)[-1]
    if last and (directory or (directory is None and "." not in last)):
        path += "/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def path_to_url(path: str, root: str, base_url: str) -> str:
    """out/guides/sg-arrival-card/index.html -> https://site.com/guides/sg-arrival-card/"""
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    # macOS пишет имена файлов в NFD, ссылки на сайте — в NFC. Адрес один.
    rel = unicodedata.normalize("NFC", rel)
    rel = _INDEX_RE.sub(r"\1", rel)
    rel = _HUGO_INDEX.sub(r"\1", rel)
    rel = _EXT_RE.sub("", rel)
    if rel in (".", ""):
        rel = ""
    # Пробелы и кириллица в имени файла обязаны уехать в URL закодированными,
    # иначе sitemap невалиден, а ссылка на страницу с ней не сойдётся.
    # Байт не в UTF-8 в имени каталога (`caf\xe9`) приходит из os.walk
    # суррогатом: строгий quote ронял весь прогон. Он уезжает в URL как %E9.
    rel = "/".join(quote(seg, safe="~-._", errors="surrogateescape") for seg in rel.split("/"))
    url = urljoin(base_url.rstrip("/") + "/", rel)
    return normalize_url(url, directory=True)


def _file_url(path: str, root: str, base_url: str) -> str:
    """Адрес самого файла, с именем и расширением: от него считаются ссылки."""
    rel = unicodedata.normalize("NFC", os.path.relpath(path, root).replace(os.sep, "/"))
    rel = "/".join(quote(seg, safe="~-._", errors="surrogateescape") for seg in rel.split("/"))
    return urljoin(base_url.rstrip("/") + "/", rel)


def check_site_url(site: str) -> str:
    """
    Адрес сайта нужен целиком, со схемой. `example.com` молча даёт URL вида
    `example.com/page/`, невалидный sitemap и сломанный подсчёт внутренних ссылок.
    """
    site = (site or "").strip()
    if not site:
        raise SourceError(tr("Не указан адрес сайта. Добавь --site https://example.com"))
    try:
        # Непарная «[» (`http://[::1`) — ValueError, не SourceError: команда
        # падала трассировкой вместо понятной строки.
        parts = urlsplit(site)
        parts.port
    except ValueError:
        parts = None
    if parts is None or parts.scheme not in ("http", "https") or not parts.netloc:
        guess = site.split("//")[-1].strip("/")
        raise SourceError(
            tr("--site {a0} — так не годится: нужен полный адрес со схемой.\n    Попробуй: --site https://{a1}", a0=site, a1=guess))
    if parts.query or parts.fragment or "?" in site or "#" in site:
        # `https://demo.example/?x=1` склеивался с путями страниц в
        # `<loc>https://demo.example/?x=1/</loc>` — невалидный sitemap.
        raise SourceError(
            tr("--site {a0} — так не годится: в адресе сайта не бывает «?» и «#».\n    Попробуй: --site {a1}",
               a0=site, a1=urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))))
    # Пробел и кириллица в пути базы шли в <loc> как есть, а пути страниц
    # уже кодируются. Готовые %-последовательности не трогаются.
    # `--site https://x/docs/index.html` — адрес главной файлом: имя файла
    # становилось каталогом, и страницы получали `/docs/index.html/a/`.
    path = quote(_INDEX_RE.sub(r"\1", parts.path), safe="/%~-._!$&'()*+,;=:@")
    site = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    return site.rstrip("/") + "/"


# ── чтение файлов ─────────────────────────────────────────────────────────────

BOMS = ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe\x00\x00", "utf-32"),
        (b"\x00\x00\xfe\xff", "utf-32"), (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"))

# Порядок важен: cp1251 «читается» почти из чего угодно, поэтому идёт последним.
FALLBACK_ENCODINGS = ("utf-8", "cp1251", "cp1252")

UTF8_NAMES = {"utf-8", "utf8", "utf_8", "u8", "utf-8-sig", "utf_8_sig"}


def _canonical_encoding(name: str) -> str:
    """`utf8`, `utf_8` и `u8` — это UTF-8. Иначе пакет ругался на корректный файл."""
    try:
        import codecs
        return codecs.lookup(name).name
    except (LookupError, ImportError):
        return name


def is_utf8(name: str) -> bool:
    return (name or "").lower().replace("_", "-") in {
        n.replace("_", "-") for n in UTF8_NAMES}


# Метки кодировок так, как их понимает браузер (WHATWG), а не Python:
# `iso-8859-1` и `us-ascii` в браузере — windows-1252, а `utf-16` в мета-теге
# значит UTF-8 (страница, которая смогла прочитать свой мета-тег, не UTF-16).
_LABELS = {"iso-8859-1": "cp1252", "iso8859-1": "cp1252", "latin1": "cp1252",
           "latin-1": "cp1252", "l1": "cp1252", "us-ascii": "cp1252", "ascii": "cp1252",
           "windows-1252": "cp1252", "x-sjis": "cp932", "shift-jis": "cp932",
           "shift_jis": "cp932", "sjis": "cp932", "windows-31j": "cp932",
           "windows-874": "cp874", "x-cp1251": "cp1251", "utf-16": "utf-8",
           "utf-16le": "utf-8", "utf-16be": "utf-8", "utf-16-le": "utf-8",
           "utf-16-be": "utf-8", "x-mac-cyrillic": "mac_cyrillic",
           "x-mac-ukrainian": "mac_cyrillic"}
_META_TAG = re.compile(rb"<meta\b[^>]{0,500}>", re.I)
_HIGH = re.compile(rb"[\x80-\xff]")
_LETTER_RUN = re.compile(rb"[\xc0-\xff]+")
_ATTR = re.compile(rb"""([\w:-]+)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")
_CHARSET_IN = re.compile(rb"charset\s*=\s*[\"']?\s*([\w.:-]+)", re.I)


def _declared_charset(data: bytes) -> str:
    """
    Кодировка из `<meta charset>` или `<meta http-equiv="content-type">` —
    только из них. Раньше бралось любое `charset=` внутри мета-тега, включая
    description «How to set charset=iso-8859-1» и закомментированный тег.
    """
    head = data[:4096]
    while True:                                   # комментарии вон, без регулярки
        at = head.find(b"<!--")
        if at < 0:
            break
        end = head.find(b"-->", at + 4)
        head = head[:at] + (head[end + 3:] if end >= 0 else b"")
    for tag in _META_TAG.findall(head):
        attrs = {k.lower(): v.strip(b"\"'") for k, v in _ATTR.findall(tag)}
        value = attrs.get(b"charset")
        if value is None and attrs.get(b"http-equiv", b"").lower() == b"content-type":
            found = _CHARSET_IN.search(attrs.get(b"content", b""))
            value = found.group(1) if found else None
        if value:
            name = value.decode("ascii", "ignore").strip().lower()
            return _LABELS.get(name, name)
    return ""


def _mostly_utf8(data: bytes) -> bool:
    """UTF-8, кроме считанных байтов: меньше 0,1% или до восьми штук."""
    bad = len(data.decode("utf-8", errors="replace")) - len(data.decode("utf-8", errors="ignore"))
    if not bad:
        return True
    good = len(_HIGH.findall(data)) - bad
    return good > 0 and (bad <= 8 or bad / len(data) < 0.001)


def _utf8_majority(data: bytes) -> bool:
    """
    Объявлен UTF-8, и верных многобайтовых знаков больше, чем битых байтов:
    подвал в cp1251 на UTF-8-странице. Браузер слушается объявления и
    заменяет только битые байты; чтение всей страницы как cp1251 давало
    мусор вместо каждой буквы. Страница целиком в cp1251 верных
    последовательностей UTF-8 почти не содержит и сюда не попадает.
    """
    bad = len(data.decode("utf-8", errors="replace")) - len(data.decode("utf-8", errors="ignore"))
    return len(_HIGH.findall(data)) - bad > 2 * bad


def _few_replaced(data: bytes, encoding: str):
    """Текст с заменой битых мест — если их считанные единицы, иначе None."""
    try:
        text = data.decode(encoding, errors="replace")
    except LookupError:
        return None
    bad = text.count("\ufffd") - data.decode(encoding, errors="ignore").count("\ufffd")
    return text if bad <= 8 or bad / max(len(text), 1) < 0.001 else None


def _bomless_utf16(data: bytes) -> str:
    """UTF-16 без BOM: в начале файла каждый второй байт — ноль."""
    head = data[:512]
    if len(head) < 16:
        return ""
    even = head[0::2].count(0) / len(head[0::2])
    odd = head[1::2].count(0) / len(head[1::2])
    if odd > 0.4 and even < 0.05:
        return "utf-16-le"
    if even > 0.4 and odd < 0.05:
        return "utf-16-be"
    return ""


def _cyrillic_or_latin(data: bytes) -> str:
    """
    cp1251 или cp1252 без объявления. В cp1251 байты 0xC0–0xFF — буквы
    кириллицы, и они идут подряд: слово из них и состоит. Во французском или
    немецком тексте такой байт стоит один среди латиницы: «détaillé».
    Раньше cp1251 пробовался первым и читался из чего угодно — до cp1252
    очередь не доходила никогда, и «café» становилось «cafй».
    """
    runs = _LETTER_RUN.findall(data)
    high = sum(len(r) for r in runs)
    paired = high - len(runs)
    if not high:
        return "cp1252"
    if paired / high <= 0.4:
        return "cp1252"
    # KOI8-R тоже даёт сплошные «буквенные» байты, и читался как cp1251:
    # «бТЕОДБ ЛЧБТФЙТЩ» вместо «Аренда квартиры». В cp1251 строчные — 0xE0–0xFF,
    # в KOI8-R они в 0xC0–0xDF. Обычный текст почти весь из строчных, поэтому
    # KOI8-R — только когда «строчных» по cp1251 явно меньшинство.
    lower = sum(1 for r in runs for b in r if b >= 0xE0)
    if high >= 20 and lower / high < 0.25:
        return "koi8_r"
    return "cp1251"



def read_text(path: str) -> tuple:
    """
    Читает текстовый файл, определяя кодировку. Возвращает (текст, кодировка).

    Молча читать чужую кодировку «с заменой» нельзя: cp1251-страница
    превращается в мусор, счётчик слов даёт ноль, и пакет объявляет
    нормальную страницу тонкой. Лучше честно сказать, что файл не в UTF-8.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise SourceError(tr("{a0}: файл не читается ({a1}).", a0=path, a1=exc.strerror or exc))

    for bom, encoding in BOMS:
        if data.startswith(bom):
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError:
                if encoding != "utf-8-sig":
                    # Лишний последний байт (оборванная загрузка, LF от
                    # редактора) — браузер покажет UTF-16 с одним знаком
                    # замены. Раньше файл читался как cp1251 с нулями внутри
                    # и выпадал из проверок как «кусок шаблона».
                    text = _few_replaced(data, encoding)
                    if text is not None:
                        return text, encoding
                break

    utf16 = _bomless_utf16(data)
    if utf16:
        try:
            return data.decode(utf16), utf16
        except UnicodeDecodeError:
            text = _few_replaced(data, utf16)
            if text is not None:
                return text, utf16

    # Строгий UTF-8 с не-ASCII — это UTF-8, что бы ни было объявлено: текст в
    # cp1251 строгой проверки UTF-8 практически не проходит, а устаревший
    # `<meta charset="windows-1251">` на перекодированном сайте встречается.
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    declared = _declared_charset(data)
    if declared and is_utf8(declared) or not declared and _mostly_utf8(data):
        # Один случайный байт — `\xa9` в подвале — не повод читать всю страницу
        # как cp1251: браузер покажет UTF-8 с одним знаком замены.
        if _mostly_utf8(data) or declared and _utf8_majority(data):
            return data.decode("utf-8", errors="replace"), "utf-8"
    if declared and not is_utf8(declared):
        for errors in ("strict", "replace"):
            try:
                return data.decode(declared, errors=errors), _canonical_encoding(declared)
            except (UnicodeError, LookupError):
                # `<meta charset="undefined">` — такой кодек в Python есть, и он
                # бросает голый UnicodeError: объявленная ерунда роняла весь прогон.
                break

    for encoding in (_cyrillic_or_latin(data), "cp1252", "cp1251"):
        try:
            return data.decode(encoding), _canonical_encoding(encoding)
        except (UnicodeError, LookupError):
            continue
    raise SourceError(
        tr("{a0}: не удалось определить кодировку. Пересохрани файл в UTF-8.", a0=path))


def open_text(path: str):
    """Обёртка для построчного чтения (CSV): подбирает кодировку заранее."""
    text, encoding = read_text(path)
    return text, encoding


# ── HTML ──────────────────────────────────────────────────────────────────────

# Поля цены, которые сверяются с текстом. Рейтинги в микроданных почти всегда
# стоят текстом элемента (`<span itemprop="ratingValue">4.8</span>`), а не
# атрибутом; цена атрибутом — норма WooCommerce и тем Shopify.
_MICRODATA_PRICES = {"price": "price", "lowprice": "lowPrice", "highprice": "highPrice"}
# Автор и даты в микроданных и RDFa на обычных элементах: `<span
# itemprop="author">`, `<time itemprop="startDate" datetime="…">`. Значение
# ложится в meta под тем же ключом, что дал бы `<meta itemprop>`.
_MICRODATA_META = {"author", "creator", "publisher", "datepublished", "datemodified",
                   "datecreated", "startdate", "enddate"}


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.canonical = ""
        self.canonicals = []       # все непустые canonical в <head>
        self.canonicals_in_body = []   # canonical в <body> поисковик не читает
        self.robots = ""
        self.lang = ""
        self.base = ""
        self.hrefs = []
        # `rel="nofollow"`: по ним краулер не идёт, но ссылка есть — и
        # человек по битой попадает на 404.
        self.nofollow_hrefs = []
        self.headings = []
        # Те же заголовки без врезок, подвала и меню. `no-question-headings`
        # считал колонки подвала и «Keep reading» заголовками статьи: на
        # a live events site это 40% подзаголовков медианной страницы.
        self.outline = []
        self._chrome_stack = []
        # Шапка, подвал, меню и врезки страницы без <main>: их текст остаётся
        # в основном, но `trimmed_words` должен отличить подвал сайта от
        # общего хвоста шаблона, а другого признака у него нет.
        self._frame_stack = []
        self._framed = []
        # Видимый текст без кода — для поиска швов шаблона. Собирается тем же
        # проходом: второй разбор исходника стоил пятую часть времени загрузки.
        self._code_stack = []
        self.visible = []
        self._br_run = False       # последним в тексте был <br>, а после него — ничего
        self.anchors = []
        self.jsonld = []
        self.alternates = []       # (код hreflang как написан, href)
        # hreflang в <body> поисковик не читает: такие ссылки не считаются
        # альтернативами, а только пересчитываются для находки.
        self.alternates_in_body = 0
        self._in_body = False
        self.alts = []
        self.microdata = []        # (поле, значение) цен микроданных и RDFa
        self._scope_stack = []     # глубины открытых itemscope / typeof / vocab
        # RDFa: открытые `vocab` и `prefix` — (глубина, словарь schema.org ли;
        # префикс → schema.org ли).
        self._vocab_stack = []
        self._prefix_stack = []
        # Свойства, значение которых — текст элемента: [глубина, ключ, куски, id скрытых].
        self._props = []
        self._hidden_prices = []   # (поле, текст, id скрытых) — цена текстом скрытого элемента
        self.blocks = {"li": 0, "table": 0, "img": 0, "img_no_alt": 0, "img_empty_alt": 0,
                       "script": 0, "p": 0}
        self.meta = {}             # author, datePublished и прочее из <meta>
        self._chunks = []          # (текст, приклеивать ли к предыдущему)
        self._main_chunks = []
        self._paragraphs = []
        self._para_buf = []
        self._skip_depth = 0
        self._in_title = False
        self._title_done = False
        self._foreign = 0          # сколько из пропускаемых блоков — <svg>
        self._in_heading = 0
        self._heading_buf = ""
        self._in_anchor = False
        self._anchor_buf = ""
        # Стек тегов, открывших основной блок. Раньше глубина росла и для
        # `role="main"` на любом теге, а падала только для <main>/<article>,
        # поэтому подвал навсегда оставался «основным текстом», а хеш страницы
        # менялся от правки меню — то есть починка хеша не работала.
        self._main_stack = []
        self._depth = 0
        self._saw_main = False
        self._in_ld = False
        self._ld_buf = ""
        self._glue = False         # следующий кусок текста примыкает к предыдущему
        # Глубины открытых служебных блоков внутри текста: <nav>, крошки,
        # подпись автора, оглавление. Текст их остаётся в странице, но абзацем
        # не становится.
        self._aside_stack = []
        # Глубины открытых <table> и <pre>: их текст — данные, а не проза.
        # И глубины <p>, открытых внутри таблицы: при вёрстке таблицами в
        # ячейке лежит обычный абзац, и он абзацем остаётся.
        self._data_stack = []
        self._prose_stack = []
        self._after_dt = False     # последним в <dl> был <dt>, а не <dd>
        # Открытые элементы по именам. Глубина — длина этого стека, а не счётчик
        # «открыл минус закрыл»: <img> и <br> не закрываются вовсе, <p> и <li>
        # закрывать не обязательно, и счётчик уезжал на единицу с каждым таким
        # тегом — подвал попадал в текст страницы и в её хэш.
        self._open = []
        # Сколько элементов каждого имени открыто. Без него каждый лишний
        # закрывающий тег просматривал весь стек: 240 КБ `</span>` разбирались
        # 77 секунд.
        self._open_count = Counter()
        # Скрытые блоки: `hidden` и `display:none` / `visibility:hidden` в
        # style. Текст их остаётся в text — по нему работают все проверки, —
        # но сверка разметки с видимым ведётся без него. Стек — (глубина, id).
        self._hidden_stack = []
        self._hidden_ids = ()
        # visibility:hidden наследуется, но потомок с visibility:visible снова
        # виден. Глубины таких потомков и глубины скрытых только visibility.
        self._reveal_stack = []
        self._vis_only = set()
        self._any_hidden = False
        # Весь текст по порядку: (кусок, приклеивать ли, id скрытых предков).
        self._shown_chunks = []
        # id, которыми управляют кнопки и ссылки: вкладки и раскрывашки,
        # скрытые до щелчка. Google считает их содержимое видимым.
        self._controls = set()
        # Открытые <template>: True — декларативный теневой корень
        # (`shadowrootmode`), его браузер рисует без скриптов, False — инертный.
        self._templates = []
        # Элемент с сырым текстом, закрытый слешем: `<iframe … />`. Браузер
        # слеш не замечает, и содержимое тянется до `</iframe>`.
        self._raw_open = ""

    # -- служебное ------------------------------------------------------------

    @property
    def _in_main(self) -> bool:
        return bool(self._main_stack)

    def _emit(self, text: str):
        target = self._main_chunks if self._in_main else self._chunks
        target.append((text, self._glue))
        self._shown_chunks.append((text, self._glue, self._hidden_ids))
        if self._hidden_ids:
            self._any_hidden = True
        if self._frame_stack:
            self._framed.append((text, self._glue))
        # Абзацы собираются только внутри основного блока: иначе первым абзацем
        # страницы оказывался пункт меню, и проверка прямого ответа выносила
        # вердикт по хлебным крошкам.
        if self._in_main or not self._saw_main:
            kind = _PROSE
            if self._aside_stack:
                kind = _SERVICE
            elif self._data_stack and not (
                    self._prose_stack and self._prose_stack[-1] > self._data_stack[-1]):
                kind = _DATA
            self._para_buf.append((text, self._in_main, kind))
        self._glue = True

    def _flush_paragraph(self):
        buf, self._para_buf = self._para_buf, []
        # split() режет по тем же пробелам, что и \s, — и впятеро быстрее.
        text = " ".join(" ".join(t for t, _, _ in buf).split())
        if text:
            self._paragraphs.append((text, any(m for _, m, _ in buf),
                                     max(k for _, _, k in buf)))

    def _close_to(self, index: int):
        """Закрывает всё открытое выше `index` и то, что на этом держалось."""
        for name in self._open[index:]:
            self._open_count[name] -= 1
        del self._open[index:]
        self._depth = len(self._open)
        while self._main_stack and self._main_stack[-1][1] > self._depth:
            self._main_stack.pop()
        while self._chrome_stack and self._chrome_stack[-1] > self._depth:
            self._chrome_stack.pop()
        while self._frame_stack and self._frame_stack[-1] > self._depth:
            self._frame_stack.pop()
        while self._code_stack and self._code_stack[-1] > self._depth:
            self._code_stack.pop()
        if self._hidden_stack and self._hidden_stack[-1][0] > self._depth:
            while self._hidden_stack and self._hidden_stack[-1][0] > self._depth:
                self._vis_only.discard(self._hidden_stack.pop()[0])
            self._update_hidden()
        if self._reveal_stack and self._reveal_stack[-1] > self._depth:
            while self._reveal_stack and self._reveal_stack[-1] > self._depth:
                self._reveal_stack.pop()
            self._update_hidden()
        while self._scope_stack and self._scope_stack[-1] > self._depth:
            self._scope_stack.pop()
        while self._vocab_stack and self._vocab_stack[-1][0] > self._depth:
            self._vocab_stack.pop()
        while self._prefix_stack and self._prefix_stack[-1][0] > self._depth:
            self._prefix_stack.pop()
        while self._props and self._props[-1][0] > self._depth:
            self._end_prop(self._props.pop())
        if self._aside_stack and self._aside_stack[-1] > self._depth:
            self._flush_paragraph()
            while self._aside_stack and self._aside_stack[-1] > self._depth:
                self._aside_stack.pop()
        if self._data_stack:
            while self._prose_stack and self._prose_stack[-1] > self._depth:
                self._prose_stack.pop()
            if self._data_stack[-1] > self._depth:
                self._flush_paragraph()
                while self._data_stack and self._data_stack[-1] > self._depth:
                    self._data_stack.pop()

    def _update_hidden(self):
        top = self._reveal_stack[-1] if self._reveal_stack else 0
        self._hidden_ids = tuple(i for d, i in self._hidden_stack if d > top)

    def _schema_names(self, a: dict) -> list:
        """
        Имена свойств schema.org из `itemprop` и `property`, в нижнем регистре.
        RDFa-имя без префикса принадлежит словарю ближайшего `vocab`: под
        `vocab="http://purl.org/goodrelations/v1#"` `price` — не schema.org.
        Префикс разрешается через `prefix="s: https://schema.org/"`.
        """
        out = []
        for attr in ("itemprop", "property"):
            for name in a.get(attr, "").split():
                key = name.lower()
                if "/" in key:
                    # Полное имя свойства — только словаря schema.org.
                    if "schema.org/" not in key:
                        continue
                    key = key.rsplit("/", 1)[-1]
                elif ":" in key:
                    # `schema:price` — да, `og:price:amount` и `product:price` — нет.
                    prefix, _, key = key.partition(":")
                    if prefix != "schema":
                        declared = next((m[prefix] for _, m in reversed(self._prefix_stack)
                                         if prefix in m), False)
                        if attr != "property" or not declared:
                            continue
                elif attr == "property" and self._vocab_stack and not self._vocab_stack[-1][1]:
                    continue
                out.append(key)
        return out

    def _microdata_price(self, tag: str, a: dict):
        """
        Цена предложения в микроданных или RDFa, если её значение задано
        атрибутом: `<meta itemprop="price" content="999">`,
        `<span property="schema:price" content="16.99">`. Значение атрибута
        видно только поисковику — его и есть смысл сверять с текстом. Цена
        текстом элемента сверяется, только если сам элемент скрыт: её тоже
        видит один поисковик.
        """
        if "itemscope" in a:
            return                 # `itemprop` на сущности — ссылка на объект, не число
        names = self._schema_names(a)
        if "content" in a:
            value = a["content"]
        elif tag in ("data", "meter") and "value" in a:
            value = a["value"]
        else:
            if self._hidden_ids and tag not in VOID_TAGS:
                for key in names:
                    field_name = _MICRODATA_PRICES.get(key)
                    if field_name:
                        self._props.append([self._depth, field_name, [], self._hidden_ids])
                        return
            return
        value = (value or "").strip()
        if not value:
            return
        for key in names:
            field_name = _MICRODATA_PRICES.get(key)
            if field_name:
                self.microdata.append((field_name, value))
                return

    def _microdata_meta(self, tag: str, a: dict):
        """Автор и даты микроданных и RDFa на обычных элементах — в meta."""
        # Свойство сущности, заданное атрибутом: `<div itemprop="publisher"
        # itemscope><meta itemprop="name" content="…">` — у издателя есть имя.
        content = (a.get("content") or "").strip()
        for prop in self._props:
            if content and isinstance(prop[1], tuple) and len(prop[2]) < 20:
                prop[2].append(content)
        if tag == "meta":
            return                 # `<meta itemprop>` читает разбор мета-тегов
        keys = [k for k in self._schema_names(a) if k in _MICRODATA_META]
        if not keys:
            return
        if "content" in a:
            value = a["content"]
        elif tag == "time" and "datetime" in a:
            value = a["datetime"]
        elif tag in ("link", "a") and a.get("href") and "itemscope" not in a:
            value = a["href"]
        elif tag not in VOID_TAGS:
            # Значение — текст элемента; у сущности (`itemscope`) — текст её
            # свойств, `<span itemprop="name">`.
            self._props.append([self._depth, tuple(keys), [], ()])
            return
        else:
            return
        value = (value or "").strip()
        if value:
            for key in keys:
                self.meta.setdefault(key, value)

    def _end_prop(self, prop):
        depth, key, chunks, ids = prop
        text = _clean(" ".join(chunks))[:200]
        if not text:
            return
        if isinstance(key, tuple):
            for name in key:
                self.meta.setdefault(name, text)
        else:
            self._hidden_prices.append((key, text, ids))

    def close(self):
        super().close()
        while self._props:
            self._end_prop(self._props.pop())

    @property
    def hidden_prices(self) -> list:
        """Цены текстом скрытых элементов, кроме вкладок и раскрывашек."""
        controls = self._controls
        return [(key, text) for key, text, ids in self._hidden_prices
                if not all(i and i in controls for i in ids)]

    def _imply_end(self, tag: str):
        """
        Необязательные закрывающие теги: новый <p> закрывает открытый <p>,
        новый <li> — предыдущий <li>. Минификаторы их и не пишут. Без этого
        незакрытый `<p class="byline">` оставался открытым до конца родителя
        и уносил с собой все абзацы после себя.
        """
        closes = _IMPLIED_END.get(tag)
        if not closes or not any(self._open_count[name] for name in closes):
            return
        for index in range(len(self._open) - 1, -1, -1):
            name = self._open[index]
            if name in closes:
                self._close_to(index)
                return
            if name not in INLINE_TAGS and name not in ("a", "span"):
                return

    # -- разбор ---------------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        # Повторённый атрибут: браузер берёт первый. Последний делал из
        # `<meta name="description" name="robots">` закрытую страницу.
        a = {}
        for k, v in attrs:
            a.setdefault(k.lower(), v or "")
        if tag == "template":
            shadow = (not self._skip_depth
                      and a.get("shadowrootmode", "").strip().lower() in ("open", "closed"))
            self._templates.append(shadow)
            if not shadow:
                self._skip_depth += 1
                return
        # JSON-LD внутри <template>, <noscript> или <svg> поисковик не читает.
        if (tag == "script" and "ld+json" in a.get("type", "").lower()
                and not self._skip_depth):
            self._in_ld = True
            self._ld_buf = ""
            self._skip_depth += 1
            return
        if tag in SKIP_TAGS and tag != "template":
            if tag == "svg" and not self._skip_depth:
                self._in_body = True       # <svg> в <head> закрывает его, как <img>
            self._skip_depth += 1
            if tag == "script":
                self.blocks["script"] += 1
            elif tag == "svg":
                self._foreign += 1
            return
        # Незакрытый <svg> прятал всю страницу. По спецификации HTML абзац,
        # заголовок или список выводят из «чужого» содержимого SVG.
        if (self._skip_depth and self._foreign >= self._skip_depth
                and tag in _BREAKOUT):
            self._skip_depth = self._foreign = 0
        # Внутри пропускаемого блока не существует ни ссылок, ни мета-тегов:
        # ссылка в <template> не ведёт никуда, пока её не отрендерит скрипт.
        if self._skip_depth:
            return
        if tag == "body" or tag not in HEAD_TAGS:
            self._in_body = True

        if tag not in INLINE_TAGS:
            self._glue = False

        for name in ("aria-controls", "data-target", "data-bs-target", "href"):
            value = a.get(name)
            if value:
                if name == "aria-controls":
                    self._controls.update(value.split())
                elif value.startswith("#") and len(value) > 1:
                    self._controls.add(value[1:])

        if tag not in VOID_TAGS:
            self._imply_end(tag)
            # `<body style="display:none">` — защита от мигания до загрузки
            # стилей: скрипт показывает страницу сразу, и скрыта она не вся.
            hides = (tag not in ("html", "body") and not self._open_count["details"]
                     and _hides(a))
            self._open.append(tag)
            self._open_count[tag] += 1
            self._depth = len(self._open)
            if hides:
                self._hidden_stack.append((self._depth, a.get("id", "").strip()))
                if "hidden" not in a and not _STYLE_NONE.search(a.get("style", "")):
                    self._vis_only.add(self._depth)
                self._update_hidden()
            elif self._hidden_ids and _STYLE_VISIBLE.search(a.get("style", "")) and all(
                    d in self._vis_only for d, _ in self._hidden_stack
                    if d > (self._reveal_stack[-1] if self._reveal_stack else 0)):
                self._reveal_stack.append(self._depth)
                self._update_hidden()
        if tag not in VOID_TAGS and (tag in MAIN_TAGS
                                     or a.get("role", "").lower() == "main"):
            self._main_stack.append((tag, self._depth))
            self._saw_main = True
        if tag not in VOID_TAGS and _is_aside(tag, a):
            self._flush_paragraph()
            self._aside_stack.append(self._depth)
        if tag in _CODE_TAGS:
            self._code_stack.append(self._depth)
        if tag not in VOID_TAGS and (tag in _CHROME_TAGS
                                     or a.get("role", "").lower() in _CHROME_ROLES):
            self._chrome_stack.append(self._depth)
        if tag not in VOID_TAGS and "vocab" in a:
            self._vocab_stack.append((self._depth, "schema.org" in a["vocab"].lower()))
        if tag not in VOID_TAGS and a.get("prefix"):
            parts = a["prefix"].split()
            self._prefix_stack.append((self._depth, {
                p[:-1].lower(): "schema.org" in u.lower()
                for p, u in zip(parts[::2], parts[1::2]) if p.endswith(":")}))
        if self._scope_stack and ("itemprop" in a or "property" in a):
            self._microdata_price(tag, a)
            self._microdata_meta(tag, a)
        if tag not in VOID_TAGS and ("itemscope" in a or "typeof" in a or "vocab" in a):
            self._scope_stack.append(self._depth)
        if tag not in VOID_TAGS and (tag in _FRAME_TAGS
                                     or a.get("role", "").lower() in _FRAME_ROLES):
            self._frame_stack.append(self._depth)
        # Два <br> подряд — граница абзаца: так верстают тексты, собранные
        # из CMS без <p>. Один <br> — перенос строки внутри абзаца.
        if tag == "br":
            if self._br_run:
                self._flush_paragraph()
            self._br_run = True
        else:
            self._br_run = False
        if tag in _OWN_BLOCKS:
            self._flush_paragraph()
        # Границы абзаца, которых раньше не было. Таблица от подписи до
        # последней ячейки и весь <dl> были одним «абзацем»: на живом сайте событий
        # `long-paragraph` стоял на 43 страницах из 87, а прозой из 55 блоков
        # был один.
        if tag in _DATA_TAGS:
            self._flush_paragraph()
            self._data_stack.append(self._depth)
        elif tag in _TABLE_PARTS:
            self._flush_paragraph()
        elif tag == "p" and self._data_stack:
            self._prose_stack.append(self._depth)
        elif tag == "dl":
            self._flush_paragraph()
            self._after_dt = False
        elif tag == "dt":
            # Термин и его определение — один блок, как пункт списка. Два
            # <dt> подряд делят одно определение и блок не разрывают.
            if not self._after_dt:
                self._flush_paragraph()
            self._after_dt = True
        elif tag == "dd":
            self._after_dt = False

        # Счётчики структуры считаются по основному блоку: список в меню
        # не делает страницу структурированной.
        if self._in_main or not self._saw_main:
            # Пункт меню до <main> — не список статьи.
            if tag == "li" and not self._chrome_stack and not self._aside_stack:
                self.blocks["li"] += 1
            elif tag == "table" and a.get("role", "").lower() not in ("presentation", "none"):
                # Таблица вёрстки — не таблица данных.
                self.blocks["table"] += 1
            elif tag == "dt" and not self._chrome_stack and not self._aside_stack:
                # Список терминов — тоже список.
                self.blocks["dl"] = self.blocks.get("dl", 0) + 1
            elif tag == "p":
                self.blocks["p"] += 1
        # Картинки — и после закрытого блока: одна врезка <article> (отзыв,
        # промо) прятала от проверки alt всё, что шло за ней. Шапка, подвал,
        # меню и боковые колонки — по-прежнему нет.
        if tag == "img" and (self._in_main or not self._saw_main
                             or not (self._frame_stack or self._aside_stack)):
                self.blocks["img"] += 1
                # Пустой alt="" — по WCAG пометка декоративной картинки, а не
                # её отсутствие. Раньше они считались одним и тем же.
                # role="presentation"/"none" и aria-hidden axe тоже считает
                # декоративными.
                if "alt" not in a and not (
                        a.get("role", "").strip().lower() in ("presentation", "none")
                        or a.get("aria-hidden", "").strip().lower() == "true"):
                    self.blocks["img_no_alt"] += 1
                elif "alt" not in a:
                    self.blocks["img_empty_alt"] += 1
                elif not a["alt"].strip():
                    self.blocks["img_empty_alt"] += 1
                else:
                    self.alts.append((a["alt"].strip(), a.get("src") or ""))
        if tag == "p":
            self._flush_paragraph()

        if tag == "html" and a.get("lang"):
            self.lang = a["lang"]
        elif tag == "base" and a.get("href") and not self.base:
            self.base = a["href"].strip()
        elif tag == "title" and not self._title_done:
            # Второй <title> в теле страницы браузер не читает.
            self._in_title = True
        elif tag == "time" and a.get("datetime"):
            self.meta.setdefault("datemodified", a["datetime"].strip())
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or a.get("itemprop") or "").lower()
            content = (a.get("content") or "").strip()
            if name == "description":
                # itemprop="description" в теле — описание товара или отзыва
                # из микроразметки, а не страницы. Второй пустой тег (тема и
                # SEO-плагин выводят по одному) заполненный не стирает.
                if (a.get("name") or a.get("property")) and content:
                    self.description = content
            elif name in ("robots", "googlebot"):
                # Поисковик читает только name=: `property="robots"` и
                # `itemprop="robots"` — не директива.
                if (a.get("name") or "").lower() == name:
                    self.robots = (self.robots + "," + content).strip(",")
            elif name and content:
                # author, article:published_time, article:modified_time и прочее:
                # раньше они были невидимы, и на каждой HTML-странице выдавались
                # «нет даты» и «нет автора» — 402 ложные находки на 201 странице.
                self.meta.setdefault(META_ALIASES.get(name, name), content)
        elif tag == "link":
            rel = a.get("rel", "").lower()
            if "canonical" in rel:
                href = a.get("href", "").strip()
                if self._in_body:
                    # canonical в <body> поисковик не читает, как и hreflang.
                    self.canonicals_in_body.append(href)
                elif href:
                    self.canonicals.append(href)
                    self.canonical = self.canonical or href
            # Альтернативы hreflang собираются здесь же, за тот же проход.
            # Раньше их читал отдельный разбор того же документа, и не один
            # раз: на каталоге в четыре тысячи страниц это было сорок секунд
            # из шестидесяти восьми.
            if "alternate" in rel.split() and a.get("hreflang"):
                if self._in_body:
                    self.alternates_in_body += 1
                else:
                    self.alternates.append((a["hreflang"].strip(), a.get("href", "").strip()))
        elif tag in _HEADING_TAGS:
            self._flush_paragraph()
            self._in_heading = int(tag[1])
            self._heading_buf = ""
            self._para_buf = []
        elif tag == "a" and a.get("href"):
            rel = a.get("rel", "").lower()
            if "nofollow" not in rel:
                self.hrefs.append(a["href"].strip())
                self._in_anchor = True
                self._anchor_buf = ""
            else:
                self.nofollow_hrefs.append(a["href"].strip())

    def handle_startendtag(self, tag, attrs):
        # `<path/>` внутри пропускаемого <svg> ничего не открывал: starttag
        # вышел раньше, чем дошёл до стека. Закрывать за него нечего — раньше
        # он закрывал <main>, и текст после иконки пропадал со страницы.
        skipping = bool(self._skip_depth)
        if not skipping and tag in _RAW_TEXT_TAGS:
            # `<script src=… />` вне SVG: слеш в HTML ничего не закрывает, и
            # всё до `</script>` — текст скрипта, даже если это вся страница.
            self.handle_starttag(tag, attrs)
            if tag in ("iframe", "textarea", "xmp"):
                self._raw_open = tag
                self._skip_depth += 1
            self.set_cdata_mode(tag)
            return
        self.handle_starttag(tag, attrs)
        if tag == "template":
            if self._templates and self._templates.pop():
                if self._open:
                    self._close_to(len(self._open) - 1)
                return
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            if tag == "svg":
                self._foreign = max(0, self._foreign - 1)
        elif not skipping and tag not in VOID_TAGS and self._open:
            self._close_to(len(self._open) - 1)

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self._in_ld = False
            if self._ld_buf.strip():
                self.jsonld.append(self._ld_buf.strip())
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._raw_open and tag == self._raw_open:
            self._raw_open = ""
            self._skip_depth = max(0, self._skip_depth - 1)
            if self._open_count[tag]:
                for index in range(len(self._open) - 1, -1, -1):
                    if self._open[index] == tag:
                        self._close_to(index)
                        break
            return
        if tag == "template":
            if not self._templates or not self._templates.pop():
                self._skip_depth = max(0, self._skip_depth - 1)
                return
        elif tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            if tag == "svg":
                self._foreign = max(0, self._foreign - 1)
            return
        if self._skip_depth:
            return
        if tag in VOID_TAGS:
            return
        # Закрывается ближайший открытый элемент с этим именем и всё, что
        # осталось незакрытым внутри него. Закрывающий тег без пары не значит
        # ничего — как и в браузере.
        if self._open_count[tag]:
            for index in range(len(self._open) - 1, -1, -1):
                if self._open[index] == tag:
                    self._close_to(index)
                    break
        if tag not in INLINE_TAGS:
            self._glue = False
        if tag == "title":
            if self._in_title:
                self._title_done = True
            self._in_title = False
        elif tag in _HEADING_TAGS and self._in_heading:
            text = _clean(self._heading_buf)
            if text:
                self.headings.append((self._in_heading, text))
                if not self._chrome_stack:
                    self.outline.append((self._in_heading, text))
            self._in_heading = 0
            # Заголовок не абзац: раньше он становился отдельным «абзацем»
            # и занимал место прямого ответа.
            self._para_buf = []
        elif tag == "a" and self._in_anchor:
            self.anchors.append(_clean(self._anchor_buf))
            self._in_anchor = False
        elif tag == "caption":
            # Подпись таблицы — её заголовок. Абзацем она не бывает никогда:
            # иначе на странице без прозы прямой ответ искали бы в подписи.
            self._para_buf = []
        elif tag in ("p", "div", "section", "li", "td", "th", "dl") or tag in _OWN_BLOCKS:
            self._flush_paragraph()

    def parse_html_declaration(self, i):
        # `<![CDATA[` вне SVG и MathML — фиктивный комментарий до первого `>`,
        # а не секция до `]]>`: мета-тег за ним живой.
        if not self._foreign and self.rawdata.startswith("<![CDATA[", i):
            j = self.rawdata.find(">", i + 9)
            return -1 if j < 0 else j + 1
        return super().parse_html_declaration(i)

    def handle_data(self, data):
        if self._in_ld:
            self._ld_buf += data
            return
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
            return
        if self._in_heading:
            self._heading_buf += data
        if self._in_anchor:
            self._anchor_buf += data
        if not data.strip():
            self._glue = False
            return
        self._br_run = False
        if not self._code_stack:
            self.visible.append(data)
        # Пробел до или после куска означает границу слова.
        lead = data[:1].isspace()
        text = data.strip()
        if lead:
            self._glue = False
        # Центы верхним индексом — «$19<sup>99</sup>»: это $19.99, а не $1999.
        if (self._glue and self._open and self._open[-1] == "sup"
                and re.fullmatch(r"\d{2}", text)):
            chunks = self._main_chunks if self._in_main else self._chunks
            if chunks and chunks[-1][0][-1:].isdigit() \
                    and not re.search(r"[.,]\d{1,2}$", chunks[-1][0]):
                text = "." + text
        self._emit(text)
        for prop in self._props:
            if len(prop[2]) < 20:
                prop[2].append(text)
        if data[-1:].isspace():
            self._glue = False

    # -- результат ------------------------------------------------------------

    @staticmethod
    def _join(chunks) -> str:
        out = []
        for text, glue in chunks:
            if out and glue:
                out[-1] += text
            else:
                out.append(text)
        return _clean(" ".join(out))

    @property
    def main_text(self) -> str:
        if self._saw_main and self._main_chunks:
            return self._join(self._main_chunks)
        return self._join(self._chunks + self._main_chunks)

    @property
    def chrome_text(self) -> str:
        if self._saw_main and self._main_chunks:
            return self._join(self._chunks)
        return ""

    @property
    def shown_text(self):
        """Видимый текст страницы; None — скрытых блоков нет."""
        if not self._any_hidden:
            return None
        controls = self._controls
        shown = [(text, glue) for text, glue, ids in self._shown_chunks
                 if not ids or all(i and i in controls for i in ids)]
        # Всё скрытое оказалось вкладками: отдельная копия текста не нужна.
        if len(shown) == len(self._shown_chunks):
            return None
        return self._join(shown)

    @property
    def framed_text(self) -> str:
        if self._saw_main and self._main_chunks:
            return ""
        return self._join(self._framed)

    @property
    def service_blocks(self) -> list:
        self._flush_paragraph()
        found = self._paragraphs
        if self._saw_main and any(in_main for _, in_main, _ in found):
            found = [p for p in found if p[1]]
        return [text for text, _, kind in found if kind == _SERVICE]

    @property
    def paragraphs(self) -> list:
        self._flush_paragraph()
        found = self._paragraphs
        if self._saw_main and any(in_main for _, in_main, _ in found):
            found = [p for p in found if p[1]]
        # Служебные блоки не абзацы — но если кроме них на странице ничего
        # нет, это не служебный блок, а обёртка: кое-где в <nav> завёрнут весь
        # текст. Ноль абзацев на полной странице хуже, чем крошки первым.
        # С таблицами и кодом так же: при прозе их нет вовсе, без прозы
        # блоками служат ячейки — каждая отдельно.
        for limit in (_PROSE, _DATA):
            body = [text for text, _, kind in found if kind <= limit]
            if body:
                return body
        return [text for text, _, _ in found]


# Служебные блоки внутри основного текста. На живом сайте событий крошки, подпись и
# оглавление стоят в <main> до ответа, и первым абзацем 35 страниц из 39
# становилось «Home / Attendee Retention».
#
# Имя сверяется с целым классом или с его хвостом (`article-byline`), но не
# с началом и не с серединой: `has-toc` на <body>, `with-breadcrumbs` на
# <article> и `toc-content article-body` на обёртке — это страницы, у которых
# есть оглавление, а не оглавление.
_ASIDE_NAMES = ("breadcrumb", "breadcrumbs", "byline", "toc",
                "table-of-contents", "post-meta", "article-meta")
_ASIDE_NOT = ("has", "with", "without", "no", "is", "show", "hide")
_ASIDE_HINT = re.compile(r"breadcrumb|byline|toc|table-of-contents|-meta|_meta", re.I)
_ASIDE_NEVER = {"html", "body", "main", "article"}

# Чем является блок текста: абзацем, данными (таблица, код) или служебным.
_PROSE, _DATA, _SERVICE = 0, 1, 2
_DATA_TAGS = {"table", "pre"}
# Шаблон вокруг статьи: врезки, подвал, меню. Их заголовки — не разделы текста.
_CHROME_TAGS = {"aside", "footer", "nav"}
_CODE_TAGS = {"code", "pre", "kbd", "samp", "textarea"}
_CHROME_ROLES = {"complementary", "contentinfo", "navigation"}
_FRAME_TAGS = _CHROME_TAGS | {"header"}
_FRAME_ROLES = _CHROME_ROLES | {"banner"}
_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
# Элементы с сырым текстом: их содержимое — не разметка до закрывающего тега.
_RAW_TEXT_TAGS = {"script", "style", "iframe", "textarea", "title", "xmp"}

_BREAKOUT = {"b", "big", "blockquote", "body", "br", "center", "code", "dd", "div",
             "dl", "dt", "em", "embed", "h1", "h2", "h3", "h4", "h5", "h6", "head",
             "hr", "i", "img", "li", "listing", "menu", "meta", "nobr", "ol", "p",
             "pre", "ruby", "s", "small", "span", "strong", "strike", "sub", "sup",
             "table", "tt", "u", "ul", "var"}
# Блоки, которые абзац заканчивают и сами им становятся: подпись к рисунку
# склеивалась с текстом до и после, цитата — тоже.
_OWN_BLOCKS = {"figcaption", "blockquote"}
_TABLE_PARTS = {"caption", "thead", "tbody", "tfoot", "tr", "td", "th"}

# Какой открытый элемент закрывает новый тег, если закрывающего не написали.
_BLOCKS = ("address", "article", "aside", "blockquote", "details", "div", "dl",
           "fieldset", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5",
           "h6", "header", "main", "nav", "ol", "p", "pre", "section", "table",
           "ul")
_IMPLIED_END = {name: {"p"} for name in _BLOCKS}
_IMPLIED_END.update({"li": {"li"}, "dt": {"dt", "dd"}, "dd": {"dt", "dd"},
                     "tr": {"tr", "td", "th"}, "td": {"td", "th"},
                     "th": {"td", "th"}, "option": {"option"}})


# Скрыто до щелчка или до скрипта — а значит, видно. `hidden="until-found"`
# раскрывается поиском по странице; `role="tabpanel"`, `aria-labelledby` и
# `data-state` (Radix, Headless UI) — неактивная вкладка или свёрнутая
# панель; `S:0`, `P:0` — потоковый рендер React: скрипт переносит блок на
# место сразу после загрузки.
_STYLE_HIDDEN = re.compile(r"(?<![\w-])(?:display\s*:\s*none|visibility\s*:\s*hidden)(?![\w-])", re.I)
_STYLE_NONE = re.compile(r"(?<![\w-])display\s*:\s*none(?![\w-])", re.I)
_STYLE_VISIBLE = re.compile(r"(?<![\w-])visibility\s*:\s*visible(?![\w-])", re.I)
_STREAMED_ID = re.compile(r"^[SP]:\d+$")


def _hides(attrs: dict) -> bool:
    """Прячет ли элемент своё содержимое от читателя — без щелчка и скрипта."""
    if "hidden" in attrs:
        if attrs["hidden"].strip().lower() == "until-found":
            return False
    elif not ("style" in attrs and _STYLE_HIDDEN.search(attrs["style"])):
        return False
    if attrs.get("role", "").lower() == "tabpanel" or "aria-labelledby" in attrs \
            or "data-state" in attrs:
        return False
    return not _STREAMED_ID.match(attrs.get("id", "").strip())


def _is_aside(tag: str, attrs: dict) -> bool:
    # Врезка <aside> — не ответ: «Related reading…» становилась первым
    # абзацем и прятала разгон.
    if tag in ("nav", "aside") or attrs.get("role", "").lower() == "navigation":
        return True
    if tag in _ASIDE_NEVER:
        return False
    classes = attrs.get("class", "")
    # Вызывается на каждом теге страницы, а служебных среди них единицы.
    if not classes or not _ASIDE_HINT.search(classes):
        return False
    for token in classes.lower().split():
        for name in _ASIDE_NAMES:
            if token == name:
                return True
            if token.endswith(name) and token[-len(name) - 1] in "-_":
                head = re.split(r"[-_]+", token[:-len(name)].strip("-_"))
                if not set(head) & set(_ASIDE_NOT):
                    return True
    return False


def _clean(text: str) -> str:
    """Нормализация пробелов вместе с неразрывными: NBSP — тоже пробел."""
    # str.split() режет ровно по этим знакам (NBSP и узкие пробелы — тоже
    # пробелы для isspace), а работает впятеро быстрее re.sub.
    return " ".join((text or "").split())


# ── Markdown ──────────────────────────────────────────────────────────────────

# Пустой блок (`---` и сразу `---`) закрывается первым же вариантом: без него
# выражение искало закрытие дальше и съедало текст до первой черты `---`.
FRONTMATTER = re.compile(
    r"^\ufeff?\s*-{3,}[ \t]*\r?\n(?:(?=-{3,}[ \t]*(?:\r?\n|$))|(.*?)\r?\n)"
    r"-{3,}[ \t]*(?:\r?\n|$)", re.S)
# TOML-шапка Hugo: `+++` … `+++`.
FRONTMATTER_TOML = re.compile(
    r"^\ufeff?\s*\+{3}[ \t]*\r?\n(?:(?=\+{3}[ \t]*(?:\r?\n|$))|(.*?)\r?\n)"
    r"\+{3}[ \t]*(?:\r?\n|$)", re.S)
FRONTMATTER_OPEN = re.compile(r"^\ufeff?\s*-{3,}[ \t]*\r?\n")
# Длины ограничены намеренно. Без границ каждое из этих выражений на
# подобранном вводе — сорок килобайт открывающих скобок, незакрытых блоков
# кода или пустых строк — работало за квадрат и подвешивало разбор одной
# страницы на десятки секунд. Настоящая разметка в границы укладывается.
MD_LINK = re.compile(r"(?<!!)\[([^\[\]\n]{0,1000})\]\(([^)\s]{1,2000})")
MD_HEADING = re.compile(r"^(#{1,4})[ \t]+([^\n]+?)[ \t]*$", re.M)
_FENCE_LINE = re.compile(r"^[ \t]*(```|~~~)")


def _strip_fences(md: str) -> str:
    """
    Заголовок внутри блока кода — это комментарий, а не заголовок страницы.

    Блоки вырезаются построчно. Незакрытый блок тянется до конца текста — как
    его и покажет любой рендер.
    """
    if "```" not in md and "~~~" not in md:
        return md
    out, fence = [], ""
    for line in md.split("\n"):
        mark = _FENCE_LINE.match(line)
        if fence:
            if mark and mark.group(1) == fence:
                fence = ""
                out.append("")
            continue
        if mark:
            fence = mark.group(1)
            continue
        out.append(line)
    return "\n".join(out)


_MD_REF_DEF = re.compile(
    r"^[ \t]{0,3}\[([^\[\]\n]{1,300})\]:[ \t]*<?([^\s>]{1,2000})>?", re.M)
_MD_REF_USE = re.compile(r"(?<!!)\[([^\[\]\n]{1,300})\](?:\[([^\[\]\n]{0,300})\])?(?![(:\[])")
_MD_INLINE = re.compile(
    r"(?<!!)\[([^\[\]\n]{0,1000})\]\(\s*<?((?:[^()\s<>]|\([^()\s]{0,500}\)){1,2000})>?")
_MD_AUTO = re.compile(r"<(https?://[^\s<>]{1,2000})>")
_MD_HTML_A = re.compile(r"<a\b[^<>]{0,1000}?\bhref\s*=\s*[\"']([^\"'<>]{1,2000})[\"']", re.I)


def _md_links(body: str) -> list:
    """
    Ссылки из Markdown: (текст, адрес).

    Не только `[текст](адрес)`. README больших проектов ссылается сносками —
    `[C++][cpp]` и `[cpp]: cppguide.html` внизу; бывают автоссылки `<https://…>`
    и обычный `<a href>`. Ничего из этого не читалось, и страницы,
    перечисленные на главной, оказывались сиротами. Ссылка внутри `кода` —
    пример, а не ссылка.
    """
    text = re.sub(r"`[^`\n]{0,2000}`", " ", body)
    found = [(label, href) for label, href in _MD_INLINE.findall(text)]
    refs = {name.strip().lower(): href for name, href in _MD_REF_DEF.findall(text)}
    if refs:
        plain = _MD_REF_DEF.sub("", text)
        for label, ref in _MD_REF_USE.findall(plain):
            href = refs.get((ref or label).strip().lower())
            if href:
                found.append((label, href))
    found += [(href, href) for href in _MD_AUTO.findall(text)]
    found += [("", href) for href in _MD_HTML_A.findall(text)]
    return found


def drop_spans(text: str, spans) -> str:
    """
    Вырезает куски между открывающей и закрывающей меткой: `<!--` … `-->`,
    `<pre` … `</pre>`. Без учёта регистра и за один проход на каждую пару.

    Выражение вида `<pre\b.*?</pre>` на тексте, где блок открыт и не закрыт,
    от каждого открытия идёт до конца — и так столько раз, сколько открытий.
    Здесь незакрытый блок останавливает поиск этой пары.
    """
    if not text:
        return text
    lowered = text.lower()
    cuts = []
    for opener, closer in spans:
        start = 0
        while True:
            at = lowered.find(opener, start)
            if at < 0:
                break
            follows = lowered[at + len(opener):at + len(opener) + 1]
            if opener[-1].isalpha() and (follows.isalnum() or follows == "-"):
                start = at + len(opener)          # `<pre` внутри `<preview>`
                continue
            end = lowered.find(closer, at + len(opener))
            if end < 0:
                break
            cuts.append((at, end + len(closer)))
            start = end + len(closer)
    if not cuts:
        return text
    cuts.sort()
    out, position = [], 0
    for at, end in cuts:
        if at < position:
            continue
        out.append(text[position:at])
        out.append(" ")
        position = end
    out.append(text[position:])
    return "".join(out)


# Следы недописанной страницы и то, где их искать не нужно.
BRIEF_MARKERS = ("БРИФ ДЛЯ АГЕНТА", "BRIEF FOR THE AGENT", "<!-- TODO", "TODO:")
# Метки заготовки, которые ставит сам пакет. Голый `TODO:` — слабее: это может
# быть и пометка автора, и текст о том, как писать такие пометки.
OWN_BRIEF_MARKERS = BRIEF_MARKERS[:2]
NOT_PROSE = (("<script", "</script>"), ("<style", "</style>"), ("<pre", "</pre>"),
             ("<code", "</code>"))
# Где разметка — не разметка: её показывают, выключили или держат про запас.
NOT_LIVE = (("<!--", "-->"), ("<noscript", "</noscript>"), ("<pre", "</pre>"),
            ("<code", "</code>"), ("<textarea", "</textarea>"))
# Мета-тег внутри скрипта (строка JavaScript) или инертного <template> браузер
# не исполняет: для мета-переадресации это тоже не живая разметка.
INERT = (("<script", "</script>"), ("<template", "</template>"))
# Где <pre> и <code> — не примеры кода на странице: в комментарии, в строке
# скрипта, в инертном шаблоне.
NOT_SHOWN = (("<!--", "-->"),) + INERT
# Значение атрибута с разметкой внутри — `srcdoc` у <iframe>, `data-*`: мета-тег
# в нём принадлежит чужому документу или вовсе строка, а не живая разметка.
_MARKUP_ATTRIBUTE = re.compile(
    r"""\s[\w:.-]+\s*=\s*(?:"[^"<>]{0,2000}<[^"]{0,20000}"|'[^'<>]{0,2000}<[^']{0,20000}')""")


def drop_markup_attributes(text: str) -> str:
    """Стирает значения атрибутов, в которых есть `<`."""
    if "=" not in text:
        return text
    return _MARKUP_ATTRIBUTE.sub(" x=''", text)
EMPTY_MOUNT = re.compile(
    r"<div[^<>]{0,300}\bid\s*=\s*[\"']?(?:root|app|__next|__nuxt|svelte|q-app)[\"']?"
    r"[^<>]{0,300}>\s*</div>", re.I)
_HTML_OPEN = re.compile(r"<html\b[^<>]{0,2000}>", re.I)
_REFRESH_META = re.compile(r"<meta\b[^<>]{0,2000}>", re.I)
_TIME_TAG = re.compile(r"<time\b[^<>]{0,500}>", re.I)
_NEXT_SCRIPT = re.compile(r"NEXT_REDIRECT[^<]{0,300}")
_CODE_TAG = re.compile(r"<(?:pre|code)", re.I)
_ATTRIBUTE = re.compile(r"""\s[\w:.-]+\s*=\s*(?:"[^"]*"|'[^']*')""")


def brief_prose(raw: str) -> str:
    """
    Где искать следы брифа: без кода, скриптов и атрибутов. `TODO:` в примере
    кода — заметка разработчика; кнопка «копировать» Starlight держит весь
    пример с его `TODO:` в `data-code` (devtut: 17 ложных находок из 21).
    """
    prose = _strip_fences(drop_spans(raw or "", NOT_PROSE))
    return _ATTRIBUTE.sub("", prose) if "TODO" in prose else prose


# ── следы незаполненного шаблона ─────────────────────────────────────────────

# Видимый текст — без кода, скриптов, комментариев и заготовок: `{{city}}`
# в `<code>` — пример, в `<template>` — заготовка для скрипта, а не шов.
NOT_VISIBLE = NOT_PROSE + (("<!--", "-->"), ("<noscript", "</noscript>"),
                           ("<template", "</template>"), ("<textarea", "</textarea>"),
                           ("<svg", "</svg>"), ("<head", "</head>"))
_TAG = re.compile(r"<[^<>]{0,5000}>")
SLOT_TEMPLATE = re.compile(
    r"\{\{[^{}\n]{1,80}\}\}"                       # {{city}}, {{ city.name }}
    r"|\{%[^%\n]{1,80}%\}"                          # {% if city %}
    r"|\$\{[A-Za-z_][\w.]{0,40}\}"                   # ${city}
    # {city}: но не \frac{a}{b}, x^{n} и не {1, 2, 3}
    # {city}: не меньше двух знаков — `{C}` и `{x}` это множества и переменные
    # в математике (evan-moon.github.io), а не поля шаблона.
    r"|(?<![\w\\^_{}$])\{[A-Za-z_][\w.]{1,40}\}(?!\})"
    r"|(?<![\w%])%[A-Z][A-Z0-9_]{1,30}%(?![\w%])")     # %CITY%
SLOT_LEFTOVER = re.compile(r"\[object Object\]|\$\s?NaN\b|\bNaN\s?%|[$€£₽]\s?undefined\b")
SLOT_LOREM = re.compile(r"\blorem ipsum\b", re.I)
SLOT_BRACKET = re.compile(r"\[([A-Za-zА-Яа-яЁё_][\w ]{0,30})\]")
LLM_PHRASES = re.compile(
    r"\bas an ai(?: language)? model\b|\bas a large language model\b"
    r"|\b(?:certainly|sure)! here(?: is|'s)\b|\bi hope this helps\b"
    r"|\bhere is a rewritten\b|\bi cannot fulfill\b"
    r"|как языковая модель|как ии-модель|конечно! вот\b|надеюсь, это поможет", re.I)
_WINDOWS_ENV = {"APPDATA", "LOCALAPPDATA", "USERPROFILE", "TEMP", "TMP", "PROGRAMFILES",
                "PROGRAMDATA", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PATH", "PATHEXT",
                "HOMEPATH", "HOMEDRIVE", "COMPUTERNAME", "USERNAME", "USERDOMAIN", "COMSPEC",
                "ALLUSERSPROFILE", "PUBLIC", "OS", "PROCESSOR_ARCHITECTURE", "ERRORLEVEL",
                "CD", "DATE", "TIME", "RANDOM", "JAVA_HOME", "PYTHONPATH"}
_LLM_HINTS = ("language model", "as an ai", "certainly!", "sure!", "hope this helps",
              "rewritten", "cannot fulfill", "языковая модель", "ии-модель", "конечно!",
              "надеюсь, это поможет")
# Вторые байты UTF-8 0x80–0xBF в cp1251: «Аренда» → «РђСЂРµРЅРґР°». Пара
# «Р/С + знак» встречается и в обычном тексте («ТАСС»), поэтому нужны две
# подряд. Неразрывный пробел и мягкий перенос из набора убраны.
_CP1251_TAIL = ("\u0402\u0403\u201a\u0453\u201e\u2026\u2020\u2021\u20ac\u2030\u0409\u2039"
                "\u040a\u040c\u040b\u040f\u0452\u2018\u2019\u201c\u201d\u2022\u2013\u2014"
                "\u2122\u0459\u203a\u045a\u045c\u045b\u045f\u040e\u045e\u0408\u00a4\u0490"
                "\u00a6\u00a7\u0401\u00a9\u0404\u00ab\u00ac\u00ae\u0407\u00b0\u00b1\u0406"
                "\u0456\u0491\u00b5\u00b6\u00b7\u0451\u2116\u0454\u00bb\u0458\u0405\u0455"
                "\u0457")
MOJIBAKE = re.compile(r"â€[\u0080-\u00bf\u2018-\u201e\u2122\u0153\u02dc]|Ã[\u0080-\u00bf]"
                      # «Ã„rzte», «Ãœbersicht», «Ã‰tudiants»: cp1252 кладёт эти
                      # вторые байты выше U+00FF. Кавычки и многоточие — только
                      # перед буквой: «AMANHÃ”» — португальский текст в кавычках.
                      r"|Ã[\u20ac\u201a\u0192\u201e\u2020\u2021\u02c6\u2030\u0160\u2039\u0152"
                      r"\u017d\u2022\u2013\u2014\u02dc\u2122\u0161\u203a\u0153\u017e\u0178]"
                      r"|[ÃÅ][\u2018\u2019\u201c\u201d\u2026](?=[^\W\d_])"
                      r"|Ð[\u0080-\u00bf]Ð|Ñ[\u0080-\u008f]"
                      r"|(?:[РС][" + _CP1251_TAIL + r"]){2}")


def visible_text(raw: str) -> str:
    """Текст, который видит читатель: без кода, скриптов, <head> и комментариев."""
    return html_unescape(_TAG.sub(" ", drop_spans(raw or "", NOT_VISIBLE)))


def find_slots(text: str, markdown: bool = False) -> list:
    """
    Следы незаполненного шаблона в тексте: [(вид, образец)], не больше трёх
    образцов на вид (полей шаблона и скобок — двенадцати: они предмет
    находки, и четвёртое новое поле базовая линия должна видеть). В исходнике Markdown `{{ }}` и `{% %}` — синтаксис Hugo
    и Jekyll, а не шов: их там не ищем.
    """
    text = (text or "").replace("\u2019", "'")
    lowered = text.lower()
    found = []
    # Дешёвая проверка подстроки до выражения: на обычной странице искать
    # нечего, а регулярки с re.I по всему тексту стоили 9 мс на страницу.
    kinds = [("leftover", SLOT_LEFTOVER, ("[object", "nan", "undefined")),
             ("lorem", SLOT_LOREM, ("lorem",)),
             ("llm", LLM_PHRASES, _LLM_HINTS),
             ("mojibake", MOJIBAKE, ("ã", "â€", "ð", "ñ", "å", "рѕ", "рµ", "р°", "рё",
                                     "с‚", "сђ"))]
    if not markdown:
        kinds.insert(0, ("template", SLOT_TEMPLATE, ("{", "%")))
        kinds.append(("bracket", SLOT_BRACKET, ("[",)))
    for kind, pattern, hints in kinds:
        if not any(h in lowered for h in hints):
            continue
        samples = []
        for m in pattern.finditer(text):
            if kind == "mojibake":
                sample = text[max(0, m.start() - 6):m.end() + 4].strip()
            elif kind == "llm":
                sample = text[m.start():m.end() + 40].split("\n")[0].strip()
            else:
                sample = m.group(0)
            # %LOCALAPPDATA%, %USERPROFILE% — переменные окружения Windows в
            # тексте о безопасности или настройке, а не поля шаблона.
            if kind == "template" and sample.startswith("%") and sample.strip("%") in _WINDOWS_ENV:
                continue
            if sample not in samples:
                samples.append(sample)
            if len(samples) >= (12 if kind in ("bracket", "template") else 3):
                break
        found += [(kind, sample) for sample in samples]
    return found


def essence(raw: str) -> str:
    """
    То немногое, что проверки читают из исходника страницы.

    Исходник держался в памяти целиком: на каталоге из 4 273 страниц по 400 КБ
    это 3,4 ГБ из 4,4. Проверкам от него нужны открывающий <html> (AMP),
    мета-переадресация и команда редиректа Next.js, теги <time>, пустой узел
    под приложение и следы недописанной страницы. Всё остальное уже разобрано
    в поля страницы.

    Переадресация берётся только из живой разметки: тег внутри <noscript> или
    комментария здесь не сохраняется — иначе, вырванный из окружения, он
    выглядел бы настоящим.
    """
    if len(raw) < 4096:
        return raw
    parts = []
    opener = _HTML_OPEN.search(raw)
    if opener:
        parts.append(opener.group(0))
    lowered_hint = "equiv" in raw or "EQUIV" in raw or "Equiv" in raw
    if lowered_hint or "NEXT_REDIRECT" in raw:
        live = drop_spans(raw, NOT_LIVE)
        if lowered_hint:
            parts += [m for m in _REFRESH_META.findall(
                drop_spans(drop_markup_attributes(live), INERT))
                      if "equiv" in m.lower()]
        parts += [f"<script>{m}</script>" for m in _NEXT_SCRIPT.findall(live)]
    # <time> тоже только живой: закомментированный, вырванный из комментария,
    # выглядел бы настоящей датой.
    if _TIME_TAG.search(raw):
        parts += _TIME_TAG.findall(drop_spans(raw, NOT_LIVE + INERT))
    mount = EMPTY_MOUNT.search(raw)
    if mount:
        parts.append(mount.group(0))
    if any(marker in raw for marker in BRIEF_MARKERS):
        prose = brief_prose(raw)
        parts += [marker for marker in BRIEF_MARKERS if marker in prose]
    # Есть ли на странице примеры кода: от этого зависит, шов `{FOLDER_NAME}`
    # или нотация автора.
    if _CODE_TAG.search(raw, 0, 400_000) and _CODE_TAG.search(
            drop_spans(raw[:400_000], NOT_SHOWN)):
        parts.append("<pre></pre>")
    return "\n".join(parts)


def _strip_markdown(md: str) -> str:
    md = _strip_fences(md)
    md = re.sub(r"`[^`\n]{0,2000}`", " ", md)
    md = re.sub(r"!\[[^\[\]\n]{0,1000}\]\([^)\n]{0,2000}\)", " ", md)
    md = re.sub(r"\[([^\[\]\n]{0,1000})\]\([^)\n]{0,2000}\)", r"\1", md)
    md = drop_spans(md, (("<!--", "-->"),))
    md = re.sub(r"<[^<>]{1,5000}>", " ", md)  # сырой HTML внутри markdown
    md = re.sub(r"^[#>\-\*\+ \t]+", " ", md, flags=re.M)
    md = re.sub(r"[*_~]", "", md)
    return _clean(md)


_MD_LIST_ITEM = re.compile(r"^[ \t]*(?:[-*+]|(\d{1,9})[.)])[ \t]+")
_MD_QUOTE = re.compile(r"^(?:[ \t]{0,3}>)+[ \t]?")
_MD_HEADING_LINE = re.compile(r"^[ \t]{0,3}#{1,6}(?:[ \t]|$)")


def _md_list_items(body: str) -> int:
    """
    Пункты списков, нумерованных тоже. Нумерованный список начинается с
    единицы, как в CommonMark: «2019. год» посреди абзаца пунктом не считается.
    """
    count = 0
    for block in re.split(r"\n[ \t]*\n", body):
        listed = False
        for line in block.split("\n"):
            mark = _MD_LIST_ITEM.match(_MD_QUOTE.sub("", line))
            if mark and (listed or mark.group(1) in (None, "1")):
                count += 1
                listed = True
    return count


def _md_table_rule(line: str) -> bool:
    """Строка `|---|:---:|` под шапкой таблицы. Без `|` это просто линия."""
    if "|" not in line:
        return False
    return all(re.fullmatch(r":?-+:?", cell.strip())
               for cell in line.strip().strip("|").split("|"))


def _md_cells(row: str) -> list:
    return [_strip_markdown(cell) for cell in row.strip().strip("|").split("|")]


def _md_items(lines: list) -> list:
    """
    Делит блок на пункты списка. Строки без маркера продолжают пункт.

    Номер посреди абзаца — чаще перенос на «2019. », чем пункт: абзац
    прерывает только список, начатый с единицы. Так же считает CommonMark.
    """
    items, listed = [], False
    for line in lines:
        mark = _MD_LIST_ITEM.match(line)
        if mark and (listed or not items or mark.group(1) in (None, "1")):
            items.append([line[mark.end():]])
            listed = True
        elif items:
            items[-1].append(line)
        else:
            items.append([line])
    return ["\n".join(item) for item in items]


def _md_blocks(body: str) -> tuple:
    """Блоки прозы и отдельно ячейки таблиц: (абзацы и пункты, ячейки)."""
    prose, cells = [], []
    for block in re.split(r"\n[ \t]*\n", body):
        # Цитата — та же проза и те же таблицы, только с `>` в начале строк.
        lines = [_MD_QUOTE.sub("", line) for line in block.strip().split("\n")]
        # Текст сразу под заголовком, без пустой строки, — абзац. Раньше блок,
        # начатый с `#`, выбрасывался целиком вместе с ним.
        lines = [line for line in lines if not _MD_HEADING_LINE.match(line)]
        if not any(line.strip() for line in lines):
            continue
        rule = next((i for i in range(1, len(lines))
                     if "|" in lines[i - 1] and _md_table_rule(lines[i])), 0)
        if rule:
            for row in lines[rule - 1:rule] + lines[rule + 1:]:
                cells += _md_cells(row)
            lines = lines[:rule - 1]
        prose += [_strip_markdown(item) for item in _md_items(lines)]
    return [p for p in prose if p], [c for c in cells if c]


# Таблицу в Markdown пишут и тегами: в исходниках сайта событий все таблицы такие.
_MD_HTML_DATA = (("<table", "</table>"), ("<pre", "</pre>"))


def _md_paragraphs(md: str) -> list:
    """
    Абзацы Markdown — в том же смысле, что и в HTML: пункт списка — отдельный
    блок, таблица — не абзац. Раньше блоком было всё между пустыми строками,
    и таблица или список в тридцать строк считались одним длинным абзацем.
    Когда прозы нет вовсе, блоками служат ячейки таблицы, а если нет и их —
    то, что на странице есть.
    """
    body = drop_spans(_strip_fences(md), (("<!--", "-->"),))
    prose, cells = _md_blocks(drop_spans(body, _MD_HTML_DATA))
    return prose or cells or _md_blocks(body)[0]


def _unquote_value(value: str) -> str:
    value = value.strip()
    for ch in ('"', "'"):
        if len(value) >= 2 and value.startswith(ch) and value.endswith(ch):
            return value[1:-1]
    return value


def _yaml_scalar(value: str) -> str:
    """
    Однострочное значение YAML: кавычки и комментарий после них.

    `draft: true # flip before launch` раньше давал значение «true # flip…»,
    черновик не узнавался и уходил в sitemap и IndexNow. `title: "A: B" # SEO`
    давал заголовок с кавычками и комментарием.
    """
    value = value.strip()
    if value[:1] == '"':
        out, i = [], 1
        while i < len(value):
            ch = value[i]
            if ch == "\\" and i + 1 < len(value):
                out.append(value[i + 1])
                i += 2
                continue
            if ch == '"':
                return "".join(out)
            out.append(ch)
            i += 1
        return value
    if value[:1] == "'":
        out, i = [], 1
        while i < len(value):
            if value[i] == "'":
                if value[i + 1:i + 2] == "'":       # '' — это одна кавычка
                    out.append("'")
                    i += 2
                    continue
                return "".join(out)
            out.append(value[i])
            i += 1
        return value
    # Комментарий начинается с « #»; «C#» и «#42» без пробела перед — текст.
    return re.split(r"\s#", value, maxsplit=1)[0].strip() if " #" in value or "\t#" in value else value


def _parse_toml_frontmatter(block: str) -> dict:
    """
    Верхний уровень TOML: `ключ = значение`. Таблицы (`[params]`) и всё, что
    внутри них, пропускаются — как вложенные ключи в YAML.
    """
    out, nested = {}, False
    for line in block.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("["):
            nested = True
            continue
        if nested or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.strip()
        if value[:1] in ("\"", "'"):
            quote_char = value[0]
            end = value.find(quote_char, 1)
            value = value[1:end] if end > 0 else value[1:]
        else:
            value = value.split("#", 1)[0].strip()
        out[key.strip().strip("\"'").lower()] = _clean(value)
    return out


def _parse_frontmatter(block: str) -> dict:
    """
    Минимальный YAML: `ключ: значение` **верхнего уровня**.

    Вложенные ключи игнорируются намеренно. Раньше `seo:\\n  title: …`
    затирал настоящий title страницы, и проверялся не тот заголовок.
    Блочные значения (`|` и `>`) собираются из следующих отступленных строк.
    """
    out = {}
    lines = block.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1] in (" ", "\t", "-"):      # вложенный уровень или элемент списка
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if value in ("|", ">", "|-", ">-", "|+", ">+"):
            buf = []
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
                buf.append(lines[i].strip())
                i += 1
            value = " ".join(x for x in buf if x)
        elif not value:
            # Различаем три случая с пустым значением: список, вложенный объект
            # и перенос длинного значения на следующую строку. Последний —
            # валидный YAML, который дампер делает сам, а пакет объявлял
            # такую страницу «без title».
            wrapped, items, nested = [], [], False
            while i < len(lines) and (not lines[i].strip()
                                      or lines[i][:1] in (" ", "\t", "-")):
                nxt = lines[i]
                i += 1
                stripped = nxt.strip()
                if not stripped:
                    continue
                if stripped == "-" or stripped.startswith("- "):
                    items.append(stripped[1:].strip())
                    continue
                if nxt[:1] == "-" or ":" in stripped.split(" ")[0]:
                    nested = True         # вложенный объект — не значение
                    continue
                wrapped.append(stripped)
            # Список из одного элемента — `keyword:\n  - leipzig` — это его
            # значение; длинный список и вложенный объект — не значение.
            if len(items) == 1 and not nested and not wrapped:
                wrapped = [_yaml_scalar(items[0])]
            elif items or nested:
                wrapped = []
            if not wrapped:
                continue
            value = " ".join(wrapped)
        else:
            value = _yaml_scalar(value)
            # `keyword: [munich]` — тот же список из одного элемента.
            if value[:1] == "[" and value[-1:] == "]" and "," not in value and "[" not in value[1:]:
                value = _yaml_scalar(value[1:-1])
        value = _clean(_unquote_value(value))
        if value:
            out[key] = value
    return out


# ── страница ──────────────────────────────────────────────────────────────────

_SAFE_PATH = re.compile(r"^/(?!/)[^\s:{}%?#<>\"']*$")


def _source_url(path: str, root: str, base_url: str, meta: dict, as_index: bool) -> str:
    """
    Адрес исходника Markdown, если его задаёт не имя файла: `_index.md`
    Hugo — страница раздела, `permalink:` (Jekyll, Eleventy) и `url:` (Hugo) —
    адрес целиком, `slug:` (Hugo) — последний сегмент. Иначе пусто.
    """
    base = base_url.rstrip("/") + "/"
    # Jekyll (`_config.yml`) адрес из `url:` шапки не берёт — только `permalink:`.
    jekyll = os.path.isfile(os.path.join(root, "_config.yml"))
    for key in ("permalink",) if jekyll else ("permalink", "url"):
        value = (meta.get(key) or "").strip()
        if _SAFE_PATH.match(value):
            return normalize_url(urljoin(base, quote(value.lstrip("/"), safe="/~-._")))
    name = os.path.basename(path).lower()
    url = ""
    if name in ("_index.md", "_index.markdown"):
        url = path_to_url(os.path.join(os.path.dirname(path), "index.md"), root, base_url)
    slug = (meta.get("slug") or "").strip()
    # В Jekyll `slug` меняет адрес только записей блога — их адрес строит
    # `_jekyll_post_url`.
    if (slug and not url and not as_index
            and re.fullmatch(r"[^\s/:{}%?#<>\"']+", slug) and not jekyll):
        own = path_to_url(path, root, base_url).rstrip("/")
        if own + "/" != base:
            url = normalize_url(own.rsplit("/", 1)[0] + "/" + quote(slug, safe="~-._"),
                                directory=True)
    return url


def load_page(path: str, root: str, base_url: str, as_index: bool = False) -> Page:
    raw, encoding = read_text(path)
    notes = []
    declared = _declared_charset(raw[:4096].encode("ascii", "ignore"))
    if not is_utf8(encoding) and is_utf8(declared) and not encoding.startswith("utf-"):
        # Объявлен UTF-8, а байты в другой кодировке: браузер и краулер
        # слушаются объявления и вместо каждой буквы показывают «�».
        notes.append(tr("в <meta charset> объявлен UTF-8, а файл в {a0}: браузер и поисковик "
                        "покажут вместо букв знаки «�». Пересохрани файл в UTF-8",
                        a0=encoding))
    elif not is_utf8(encoding):
        notes.append(tr("файл прочитан как {a0}, а не UTF-8", a0=encoding))
    elif (declared and not is_utf8(declared) and not encoding.startswith("utf-16")
          and not raw.isascii()):
        # Устаревший `<meta charset="windows-1251">` на UTF-8-файле: без
        # charset в заголовке Content-Type браузер покажет «РђСЂРµРЅРґР°».
        notes.append(tr("в <meta charset> объявлен {a0}, а файл в UTF-8: если сервер не "
                        "присылает charset в Content-Type, браузер покажет кракозябры. "
                        "Исправь объявление на utf-8", a0=declared))
    if "\ufffd" in raw and is_utf8(encoding):
        notes.append(tr("в файле {a0} байт(а) не в UTF-8 — на их месте знак замены; "
                        "остальной текст прочитан как UTF-8", a0=raw.count("\ufffd")))

    url = path_to_url(os.path.join(os.path.dirname(path), "index.md") if as_index else path,
                      root, base_url)
    # Хост сравнивается в том же виде, что и адреса: без www, без порта по
    # умолчанию, в punycode. Иначе `example.com:443/c/` — внешняя ссылка.
    host = urlsplit(url_key(base_url)).netloc

    if path.lower().endswith((".md", ".markdown")):
        # CRLF и CR — тот же перевод строки. Первый прогон на Windows показал,
        # что `\r\n\r\n` не считалось пустой строкой: весь файл был одним блоком.
        raw = raw.replace("\r\n", "\n").replace("\r", "\n")
        meta, body = {}, raw
        m = FRONTMATTER.match(raw)
        toml = None if m else FRONTMATTER_TOML.match(raw)
        if m:
            meta = _parse_frontmatter(m.group(1) or "")
            body = raw[m.end():]
        elif toml:
            meta = _parse_toml_frontmatter(toml.group(1) or "")
            body = raw[toml.end():]
        elif FRONTMATTER_OPEN.match(raw):
            notes.append(tr("фронтматтер открыт, но не закрыт: строка `---` в конце блока"))
        elif raw.lstrip()[:3] == "---":
            notes.append(tr("фронтматтер не распознан"))
        matches = _md_links(_strip_fences(body))
        hrefs = [href for _, href in matches]
        nofollow_hrefs = []
        md_anchors = [text.strip() for text, _ in matches]
        md_headings = [(len(h), _clean(t)) for h, t in MD_HEADING.findall(_strip_fences(body))]
        base_href = ""
        text = _strip_markdown(body)
        # Без шапки заголовком страницы становится первый заголовок текста —
        # так делает GitHub Pages. При шапке без title это не действует:
        # там отсутствие title — находка.
        if not m and not toml and md_headings and md_headings[0][0] == 1:
            meta = {"title": md_headings[0][1]}
        # Картинки — вне блоков кода (там примеры синтаксиса), со ссылочной
        # формой `![alt][ref]` и с сырым <img> без alt.
        shown = _strip_fences(body)
        raw_imgs = re.findall(r"<img\b[^>]*>", shown, re.I)
        declared = _source_url(path, root, base_url, meta, as_index)
        if declared:
            url = declared
        page = Page(
            path=path, url=url,
            title=_clean(meta.get("title", "")),
            description=_clean(meta.get("description", "")),
            canonical=meta.get("canonical", ""),
            robots=meta.get("robots", ""),
            lang=meta.get("lang", ""),
            text=text,
            meta=meta,
            headings=md_headings,
            anchors=md_anchors,
            raw=raw,
            encoding=encoding,
            notes=notes,
            paragraphs=_md_paragraphs(body),
            alts=[(m.group(1).strip(), m.group(2) or "") for m in
                  re.finditer(r"!\[([^\[\]\n]{0,1000})\](?:\(([^)\s]*)|\[[^\]\n]*\])", shown)
                  if m.group(1).strip()],
            slots=find_slots(text, markdown=True),
            blocks={"li": _md_list_items(_strip_fences(body)),
                    "table": len(re.findall(r"^[ \t>]*\|[^\n]+\|[ \t]*$", body, re.M)) and 1 or 0,
                    "img": len(re.findall(r"!\[[^\[\]\n]{0,1000}\][(\[]", shown)) + len(raw_imgs),
                    "img_no_alt": sum(1 for t in raw_imgs if not re.search(
                        r"\salt(?:\s*=|[\s/>])", t, re.I)),
                    # В Markdown alt есть всегда: `![](x.png)` — пустой, а не
                    # отсутствующий.
                    "img_empty_alt": len(re.findall(r"!\[[ \t]*\][(\[]", shown)),
                    "script": 0, "p": 0},
        )
    else:
        ex = _Extractor()
        ex.feed(raw)
        ex.close()
        hrefs = ex.hrefs
        nofollow_hrefs = ex.nofollow_hrefs
        base_href = ex.base
        page = Page(
            path=path, url=url,
            title=_clean(ex.title),
            description=_clean(ex.description),
            canonical=ex.canonical,
            robots=ex.robots,
            lang=ex.lang,
            meta=ex.meta,
            text=ex.main_text,
            chrome=ex.chrome_text,
            framed=ex.framed_text,
            headings=ex.headings,
            outline=ex.outline,
            slots=find_slots(" ".join(ex.visible)),
            anchors=ex.anchors,
            raw=raw,
            encoding=encoding,
            notes=notes,
            jsonld=ex.jsonld,
            alternates=ex.alternates,
            alternates_in_body=ex.alternates_in_body,
            paragraphs=ex.paragraphs,
            blocks=ex.blocks,
            alts=ex.alts,
            shown=ex.shown_text,
            microdata=ex.microdata + ex.hidden_prices,
            service=ex.service_blocks,
        )
        page.__dict__["_canonicals"] = (ex.canonicals, ex.canonicals_in_body)

    # Canonical приводится к абсолютному виду тем же базовым адресом, что
    # и ссылки. Относительный `<base href>` раньше оставлял canonical
    # относительным, и самоссылающийся canonical объявлялся «чужим».
    #
    # Относительная ссылка считается от места, где лежит файл, а не от адреса,
    # под которым страницу удобно сравнивать: `contact.html` на `about.html` —
    # это `/contact.html`, а не `/about/contact.html`. Иначе плоский сайт
    # (Sphinx, mdBook, MkDocs) получал сироту на каждой такой ссылке.
    location = _file_url(path, root, base_url)
    markdown = path.lower().endswith((".md", ".markdown"))
    try:
        base_for_links = urljoin(location, base_href) if base_href else location
    except ValueError:
        base_for_links = location
    in_head, in_body = page.__dict__.pop("_canonicals", ((), ()))
    if len(in_head) > 1:
        # Разные canonical на одной странице поисковик не учитывает вовсе:
        # раньше молча побеждал последний.
        written = set()
        for href in in_head:
            try:
                written.add(urldefrag(urljoin(base_for_links, href))[0])
            except ValueError:
                written.add(href)
        if len(written) > 1:
            page.notes.append(tr("на странице {a0} разных canonical: {a1} — поисковик не учтёт "
                                 "ни один. Оставь один в <head>",
                                 a0=len(written), a1=", ".join(sorted(written)[:3])))
            page.canonical = ""
    if in_body and [h for h in in_body if h]:
        page.notes.append(tr("canonical в <body> ({a0}) поисковик не читает — перенеси его "
                             "в <head>", a0=next(h for h in in_body if h)))
    if page.canonical:
        # Записан ли canonical полным адресом. Относительный достраивается от
        # --site, и его схема и хост — это --site, а не то, как пишет сам сайт.
        try:
            written = urlsplit(page.canonical)
            page.__dict__["_canonical_absolute"] = bool(written.scheme and written.netloc)
            # `//www.host/a/` (или относительный при `<base href="//www.host/">`)
            # называет хост явно, а схему берёт у запроса: сверяется только хост.
            based = urlsplit(base_href) if base_href and not written.netloc else None
            if based is not None and based.netloc:
                page.__dict__["_canonical_absolute"] = bool(based.scheme)
            page.__dict__["_canonical_host_only"] = bool(
                (written.netloc and not written.scheme)
                or (based is not None and based.netloc and not based.scheme))
        except ValueError:
            pass
        try:
            page.canonical = urljoin(base_for_links, page.canonical)
        except ValueError:
            page.notes.append(tr("canonical не разбирается как адрес: {a0}", a0=page.canonical))
            page.canonical = ""
    if page.canonical:
        # Адрес страницы — тот, который она сама объявляет, если это она же:
        # `about.html` с canonical на `/about.html` отдаётся именно так, а
        # `/about/` на GitHub Pages, S3 и обычном nginx — это 404, и раньше
        # в sitemap уезжал он.
        own = urlsplit(page.canonical)
        if url_key(page.canonical) == page.key and not own.query:
            page.__dict__["_url_declared"] = True
            # Путь из canonical берётся в той же форме, что и из имени файла:
            # без `//` и с процент-кодированием. Сырой `/rent/köln/` или
            # `/rent/new york/` уезжал в <loc> как есть — sitemap невалиден.
            # Уже закодированное (`%C3%B6`) и разрешённые в пути знаки
            # остаются как объявлены.
            own_path = re.sub(r"/{2,}", "/", own.path or "/")
            own_path = quote(unicodedata.normalize("NFC", own_path),
                             safe="/~-._!$&'()*+,;=:@%")
            # `ko%CC%88ln` — NFD в %-кодах: `url_key` сводит его к файлу
            # `köln` (NFC), но хостинг, который сравнивает байты, ответит 404.
            # Адресом остаётся форма файла.
            decoded = unquote(own_path)
            if unicodedata.normalize("NFC", decoded) != decoded:
                own_path = urlsplit(page.url).path
            if own_path != urlsplit(page.url).path:
                site_parts = urlsplit(page.url)
                page.url = urlunsplit((site_parts.scheme, site_parts.netloc, own_path, "", ""))
    seen = set()
    forms = []
    written_forms = set()
    foreign = []
    for href in hrefs:
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            continue
        base = base_for_links
        # В Markdown живут две привычки. MkDocs и GitHub ссылаются на соседний
        # файл — `[b](b.md)`; Hugo и Jekyll пишут ссылку от адреса, по которому
        # страница выйдет, — `[b](../b/)`. Различает их расширение в ссылке.
        try:
            if markdown and not base_href and not _EXT_RE.search(urlsplit(href).path):
                base = url
            absolute, _ = urldefrag(urljoin(base, href))
            other = urlsplit(url_key(absolute)).netloc
            if other != host:
                # Помним немного чужих адресов: если сайт ссылается на себя
                # под другим именем хоста, все страницы выглядят сиротами.
                if other and len(foreign) < 30:
                    foreign.append(url_key(absolute))
                continue
        except ValueError:
            continue
        raw_path = urlsplit(absolute).path
        form = ("index" if _INDEX_RE.search(raw_path) else
                "file" if _EXT_RE.search(raw_path) else
                "slash" if raw_path.endswith("/") else "bare")
        absolute = normalize_url(absolute)
        key = url_key(absolute)
        if key != page.key and key not in seen:
            seen.add(key)
            page.links.append(absolute)
            forms.append((key, form, unquote(raw_path)))
        elif key != page.key and (key, unquote(raw_path)) not in written_forms:
            # Та же страница в другой записи: меню ведёт на `/about/`, а текст —
            # на `/about.html`. Вторая форма тоже проверяется на 404.
            forms.append((key, form, unquote(raw_path)))
        written_forms.add((key, unquote(raw_path)))
    page.__dict__["_link_forms"] = forms
    unfollowed = []
    for href in nofollow_hrefs:
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            continue
        try:
            absolute, _ = urldefrag(urljoin(base_for_links, href))
            if urlsplit(url_key(absolute)).netloc != host:
                continue
        except ValueError:
            continue
        absolute = normalize_url(absolute)
        key = url_key(absolute)
        if key != page.key and key not in seen:
            seen.add(key)
            unfollowed.append(absolute)
    if unfollowed:
        page.__dict__["_nofollow_links"] = unfollowed
    if foreign:
        page.__dict__["_foreign_links"] = foreign

    return page


# ── X-Robots-Tag из файлов хостинга ──────────────────────────────────────────

def _group_end(pattern: str, i: int) -> int:
    """Индекс закрывающей скобки группы, открытой в `pattern[i]`, или -1."""
    depth, n, in_class = 0, i, False
    while n < len(pattern):
        ch = pattern[n]
        if ch == "\\":
            n += 2
            continue
        if in_class:
            in_class = ch != "]"
        elif ch == "[":
            in_class = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if not depth:
                return n
        n += 1
    return -1


def _route_regex(pattern: str):
    """
    `/glossary/*` (Netlify) или `/glossary/(.*)`, `/:slug*` (Vercel) → выражение.

    Vercel пишет `source` на языке path-to-regexp: `:slug` — сегмент,
    `:slug*` — хвост, `:id(\\d+)` и `((?!blog).*)` — группы с выражением,
    `{/:page}?` — необязательная часть, `\\.` — буквальная точка. Раньше
    группы становились буквальным текстом и правило не совпадало ни с чем.
    Шаблон, который не разобрать, даёт None: правило пропускается, а не
    закрывает или открывает всё подряд.
    """
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        if ch == "(":
            close = _group_end(pattern, i)
            if close < 0:
                return None
            out.append("(?:" + pattern[i + 1:close].replace("(?<", "(?P<")
                       .replace("(?P<=", "(?<=").replace("(?P<!", "(?<!") + ")")
            i = close + 1
            continue
        if ch == ")":
            return None
        if ch == "{":
            out.append("(?:")
        elif ch == "}":
            out.append(")")
        elif ch in "?+" and pattern[i - 1:i] in (")", "}"):
            out.append(ch)
        elif ch == "*" and pattern[i - 1:i] in (")", "}"):
            out.append("*")
        elif ch == "*":
            out.append(".*")
        elif ch == ":":
            m = re.match(r":\w+", pattern[i:])
            if not m:
                out.append(re.escape(ch))
                i += 1
                continue
            i += len(m.group(0))
            if pattern.startswith("(", i):
                continue                  # выражение сегмента — следующая группа
            mod = pattern[i:i + 1]
            if mod in ("*", "+"):
                out.append(".*" if mod == "*" else ".+")
                i += 1
            elif mod == "?":
                out.append("[^/]*")
                i += 1
            else:
                out.append("[^/]+")
            continue
        else:
            out.append(re.escape(ch))
        i += 1
    try:
        return re.compile("".join(out) + "$")
    except (re.error, OverflowError, RecursionError):
        return None


_TOML_FOR = re.compile(r"""^\s*for\s*=\s*["']([^"']+)["']""", re.M)
# Ключ — в начале строки (`[headers.values]`) или во встроенной таблице
# (`values = { "X-Robots-Tag" = "noindex" }`). Строки-комментарии снимаются
# до поиска: `# X-Robots-Tag = "noindex"` закрывал весь сайт.
# Ключ `values.X-Robots-Tag` прямо в `[[headers]]` и литерал в тройных
# кавычках — тот же TOML.
_TOML_TAG = re.compile(r"""(?:^|[{,])\s*(?:values\s*\.\s*)?["']?X-Robots-Tag["']?\s*=\s*"""
                       r"""["']{1,3}([^"']+)["']""",
                       re.I | re.M)
_TOML_HEADERS = re.compile(r"^\s*\[\[\s*headers\s*\]\]", re.M)


# Директивы со значением через двоеточие: `max-image-preview:large` — это не
# имя бота, и директивы после неё раньше приписывались «боту max-image-preview».
_VALUED_DIRECTIVES = ("max-snippet", "max-image-preview", "max-video-preview",
                      "unavailable_after")


def _closes(value: str) -> bool:
    """
    Закрывает ли значение X-Robots-Tag страницу для Google. Директива с
    именем бота (`bingbot: noindex`, `googlebot-news: noindex`) действует
    только на него.
    """
    agent = ""
    for token in re.split(r"[,\s]+", (value or "").lower()):
        if token.partition(":")[0] in _VALUED_DIRECTIVES:
            continue
        if token.endswith(":") and len(token) > 1:
            agent = token[:-1]
            continue
        if ":" in token:
            agent, _, token = token.partition(":")
        if token in ("noindex", "none") and agent in ("", "googlebot"):
            return True
    return False


def _hides_snippet(value: str) -> bool:
    """`nosnippet` или `max-snippet: 0` в X-Robots-Tag — для всех или для Google."""
    agent = ""
    tokens = re.split(r"[,\s]+", (value or "").lower())
    for i, token in enumerate(tokens):
        if (token.partition(":")[0] in _VALUED_DIRECTIVES
                and not token.startswith("max-snippet")):
            continue
        if token.endswith(":") and len(token) > 1 and token != "max-snippet:":
            agent = token[:-1]
            continue
        if token.startswith("max-snippet"):
            number = token.partition(":")[2] or (tokens[i + 1] if i + 1 < len(tokens) else "")
            if number.strip() == "0" and agent in ("", "googlebot"):
                return True
            continue
        if ":" in token:
            agent, _, token = token.partition(":")
        if token == "nosnippet" and agent in ("", "googlebot"):
            return True
    return False


def _same_host(a: str, b: str) -> bool:
    # `www.` здесь не снимается: правило хостинга для www-зеркала (часто —
    # его noindex) к голому домену не относится, это разные хосты запроса.
    a, b = (a or "").lower().split(":")[0], (b or "").lower().split(":")[0]
    return bool(a) and a.rstrip(".") == b.rstrip(".")


def _vercel_applies(entry: dict, host: str) -> bool:
    """
    Условное правило vercel.json (`has` / `missing`) действует не на каждый
    запрос. Условие по хосту проверяется по адресу сайта; любое другое —
    заголовок, cookie, параметр — у обычного обхода не выполняется, и правило
    к нему не применяется.
    """
    for kind in ("has", "missing"):
        for cond in entry.get(kind) or ():
            if not isinstance(cond, dict):
                return False
            if cond.get("type") != "host":
                if kind == "has":
                    return False
                continue                  # «нет такого заголовка» у обхода выполнено
            hit = _same_host(str(cond.get("value", "")), host)
            if hit != (kind == "has"):
                return False
    return True


def header_noindex_rules(root: str, host: str = "", test=None) -> list:
    """
    Правила X-Robots-Tag: noindex из `_headers` (Netlify, Cloudflare Pages),
    `netlify.toml` и `vercel.json` — в сборке и уровнем выше.

    Тот же noindex, отданный заголовком, был невидим: 88 страниц глоссария
    закрывались из `_headers`, а отчёт показывал их открытыми.

    Каждое правило — (выражение, файл, шаблон, закрывает ли). Правило с чужим
    хостом (`https://:project.pages.dev/*` — рецепт Cloudflare для превью)
    к сайту не относится; `! X-Robots-Tag` в `_headers` снимает заголовок —
    это правило «открывает».

    `test` — какое значение заголовка считать срабатыванием (по умолчанию
    noindex; `_hides_snippet` — запрет сниппета).
    """
    test = test or _closes
    rules = []
    near = [root, os.path.dirname(os.path.abspath(root))]
    headers = os.path.join(root, "_headers")
    if os.path.isfile(headers):
        try:
            text, _ = read_text(headers)
        except SourceError:
            text = ""
        current = None
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not line[:1].isspace():
                current = line.strip()
                if "://" in current and not _same_host(urlsplit(current).netloc, host):
                    current = None        # правило другого хоста
                continue
            if not current:
                continue
            path = urlsplit(current).path if "://" in current else current
            stripped = line.strip()
            if stripped.startswith("!"):
                if stripped[1:].strip().lower() == "x-robots-tag":
                    rules.append((_route_regex(path), "_headers", current, False))
                continue
            name, _, value = stripped.partition(":")
            if name.strip().lower() == "x-robots-tag" and test(value):
                rules.append((_route_regex(path), "_headers", current, True))
    for folder in near:
        toml = os.path.join(folder, "netlify.toml")
        if not os.path.isfile(toml):
            continue
        try:
            text, _ = read_text(toml)
        except SourceError:
            text = ""
        text = "\n".join(x for x in text.splitlines() if not x.lstrip().startswith("#"))
        for block in _TOML_HEADERS.split(text)[1:]:
            block = block.split("[[", 1)[0]
            where, tag = _TOML_FOR.search(block), _TOML_TAG.search(block)
            if where and tag and test(tag.group(1)):
                rules.append((_route_regex(where.group(1)), "netlify.toml",
                              where.group(1), True))
        break
    for folder in near:
        vercel = os.path.join(folder, "vercel.json")
        if not os.path.isfile(vercel):
            continue
        try:
            data = json.loads(read_text(vercel)[0])
        except (SourceError, ValueError, RecursionError):
            data = {}
        for entry in (data.get("headers") if isinstance(data, dict) else None) or []:
            if not isinstance(entry, dict) or not isinstance(entry.get("source"), str):
                continue
            if not _vercel_applies(entry, host):
                continue
            for header in entry.get("headers") or []:
                if (isinstance(header, dict)
                        and str(header.get("key", "")).lower() == "x-robots-tag"
                        and test(str(header.get("value", "")))):
                    rules.append((_route_regex(entry["source"]), "vercel.json",
                                  entry["source"], True))
        break
    return rules


def _apply_header_rules(pages: list, root: str, base_url: str, problems: list) -> None:
    _apply_snippet_rules(pages, root, base_url)
    rules = header_noindex_rules(root, urlsplit(base_url).netloc)
    for regex, source, pattern, closes in rules:
        if regex is None and closes:
            problems.append(tr("{a0}: шаблон {a1} не разобран — какие страницы закрывает "
                               "его X-Robots-Tag: noindex, не проверялось",
                               a0=source, a1=pattern))
    rules = [rule for rule in rules if rule[0] is not None]
    if not any(closes for *_, closes in rules):
        return
    base = urlsplit(base_url).path.rstrip("/")
    hits = Counter()
    for page in pages:
        path = urlsplit(page.url).path
        if base and path.startswith(base + "/"):
            path = path[len(base):]
        # Правило пишут и буквами (`/город/*`), и %-кодами: сверяются обе формы.
        forms = {path, unicodedata.normalize("NFC", unquote(path))}
        matches = lambda regex: any(regex.match(p) or regex.match(p.rstrip("/")) for p in forms)
        reopened = {source for regex, source, _, closes in rules
                    if not closes and matches(regex)}
        for regex, source, pattern, closes in rules:
            if closes and source not in reopened and matches(regex):
                if not page.noindex:
                    page.robots = (page.robots + ",noindex").strip(",")
                    page.__dict__["_noindex_header"] = "%s, %s" % (source, pattern)
                hits[(source, pattern)] += 1
                break
    for (source, pattern), n in sorted(hits.items()):
        problems.append(tr("{a0} закрывает от индекса {a1} страниц(ы) заголовком "
                           "X-Robots-Tag: noindex — правило {a2}", a0=source, a1=n, a2=pattern))


def _header_path(page, base: str) -> str:
    path = urlsplit(page.url).path
    if base and path.startswith(base + "/"):
        path = path[len(base):]
    return path


def _apply_snippet_rules(pages: list, root: str, base_url: str) -> None:
    """
    `X-Robots-Tag: nosnippet` (или `max-snippet:0`) из `_headers`, `netlify.toml`
    и `vercel.json` действует так же, как мета-тег: раньше он не переносился
    на страницы, и запрет сниппета, отданный заголовком, был невидим.

    Так же переносится `nofollow` (и `none`): ссылки страницы, закрытые
    заголовком, краулер не проходит, а раньше граф шёл по ним, как по открытым.
    """
    _apply_directive(pages, root, base_url, _hides_snippet, "nosnippet",
                     lambda page: page.nosnippet)
    _apply_directive(pages, root, base_url, _unfollows, "nofollow",
                     lambda page: page.nofollow)


def _unfollows(value: str) -> bool:
    """`nofollow` или `none` в X-Robots-Tag — для всех или для Google."""
    agent = ""
    for token in re.split(r"[,\s]+", (value or "").lower()):
        if token.partition(":")[0] in _VALUED_DIRECTIVES:
            continue
        if token.endswith(":") and len(token) > 1:
            agent = token[:-1]
            continue
        if ":" in token:
            agent, _, token = token.partition(":")
        if token in ("nofollow", "none") and agent in ("", "googlebot"):
            return True
    return False


def _apply_directive(pages: list, root: str, base_url: str, test, directive: str,
                     already) -> None:
    rules = [rule for rule in header_noindex_rules(root, urlsplit(base_url).netloc, test)
             if rule[0] is not None]
    if not any(on for *_, on in rules):
        return
    base = urlsplit(base_url).path.rstrip("/")
    for page in pages:
        path = _header_path(page, base)
        # Правило пишут и буквами (`/город/*`), и %-кодами: сверяются обе формы.
        forms = {path, unicodedata.normalize("NFC", unquote(path))}
        matches = lambda regex: any(regex.match(p) or regex.match(p.rstrip("/")) for p in forms)
        reopened = {source for regex, source, _, on in rules if not on and matches(regex)}
        if any(on and source not in reopened and matches(regex)
               for regex, source, _, on in rules) and not already(page):
            page.robots = (page.robots + "," + directive).strip(",")


_TOML_FROM = re.compile(r"""^\s*from\s*=\s*["']([^"']+)["']""", re.M)
_TOML_STATUS = re.compile(r"""^\s*status\s*=\s*["']?(\d{3})""", re.M)


def host_redirect_rules(root: str) -> tuple:
    """
    Перенаправления хостинга: (выражения путей, переписывает ли хостинг формы
    адресов сам).

    `_redirects` (Netlify, Cloudflare Pages), `[[redirects]]` в netlify.toml,
    `redirects` и `rewrites` в vercel.json — в сборке и уровнем выше. Путь,
    который правило ловит, отдаётся, даже если такого файла нет. `cleanUrls`
    и `trailingSlash` в vercel.json меняют формы всех адресов разом.
    """
    rules, rewrites_forms = [], False

    def add(pattern, status=""):
        pattern = urlsplit(pattern).path if "://" in pattern else pattern
        regex = _route_regex(pattern) if pattern.startswith("/") else None
        # Перезапись 200 на любой адрес (`/* /index.html 200`) — запасной вход
        # SPA, а не редирект: по `/about/` хостинг отдаёт главную с кодом 200.
        # Это мягкий 404, и неверная форма ссылки остаётся находкой.
        if regex and str(status).startswith("200") and regex.match("/indexgap-probe/any/depth"):
            return
        # Правило с ответом 404/410 путь не отдаёт, а закрывает.
        if str(status)[:1] in ("4", "5"):
            return
        if regex:
            rules.append(regex)

    def text_of(path):
        try:
            return read_text(path)[0] if os.path.isfile(path) else ""
        except SourceError:
            return ""

    for line in text_of(os.path.join(root, "_redirects")).splitlines():
        fields = line.split("#", 1)[0].split()
        # Условное правило (`Country=de`, `Role=admin`, параметр запроса)
        # срабатывает не на каждый запрос: путь им не отдаётся.
        if len(fields) >= 2 and not any("=" in f for f in fields[1:]):
            status = next((f for f in fields[1:] if re.match(r"^\d{3}!?$", f)), "301")
            add(fields[0], status)
    near = [root, os.path.dirname(os.path.abspath(root))]
    for folder in near:
        text = text_of(os.path.join(folder, "netlify.toml"))
        if text:
            text = "\n".join(x for x in text.splitlines() if not x.lstrip().startswith("#"))
            for block in text.split("[[redirects]]")[1:]:
                block = block.split("[[", 1)[0]
                found = _TOML_FROM.search(block)
                if found and not re.search(r"^\s*conditions\s*=|^\s*\[redirects\.conditions\]",
                                           block, re.M):
                    status = _TOML_STATUS.search(block)
                    add(found.group(1), status.group(1) if status else "301")
            break
    for folder in near:
        text = text_of(os.path.join(folder, "vercel.json"))
        if not text:
            continue
        try:
            data = json.loads(text)
        except (ValueError, RecursionError):
            data = {}
        if isinstance(data, dict):
            rewrites_forms = bool(data.get("cleanUrls")) or isinstance(data.get("trailingSlash"), bool)
            for section in ("redirects", "rewrites"):
                for entry in data.get(section) or ():
                    if (isinstance(entry, dict) and isinstance(entry.get("source"), str)
                            and not entry.get("has")):
                        add(entry["source"], "200" if section == "rewrites" else "301")
        break
    return rules, rewrites_forms


def _settle_flat_urls(pages: list, root: str, base_url: str) -> None:
    """
    Адрес плоской страницы `filter.html` — в той форме, в какой на неё
    ссылается сам сайт.

    Раньше каждая такая страница без canonical получала `/filter/`, и он же
    уезжал в sitemap. На GitHub Pages, S3 и обычном nginx это 404: pkgdown,
    Pelican, mdBook и Sphinx отдают `filter.html`. Next.js-экспорт кладёт
    `about.html`, а ссылается на `/about` — тогда адрес `/about`. Если ссылок
    нет, берётся `filter.html`: он работает на любом статическом хостинге.
    Ссылки `/filter/` за адрес не голосуют: этой формы хостинг не отдаёт.

    Здесь же отмечаются ссылки в такой форме — `/faq/` при `faq.html` и
    `/about.html` при `about/index.html` (`_wrong_forms` страницы): `url_key`
    сводит их к той же странице, а живой хостинг отвечает 404. Ссылка, которую
    ловит правило перенаправления хостинга, не отмечается.
    """
    votes = defaultdict(Counter)
    written = []
    for page in pages:
        forms = page.__dict__.pop("_link_forms", ())
        written.append((page, forms))
        voted = set()
        for key, form, _written in forms:
            # Голосует первая запись ссылки на страницу, как и раньше.
            if key not in voted:
                voted.add(key)
                votes[key][form] += 1
    redirects, host_rewrites = host_redirect_rules(root)
    kinds, flat, files = {}, [], {}
    for page in pages:
        name = os.path.basename(page.path or "").lower()
        kind = None
        if name.endswith((".html", ".htm")) and not page.__dict__.get("_url_declared"):
            kind = "folder" if name.startswith("index.") else "flat"
        if kind == "flat":
            flat.append(page)
        # `a.html` рядом с `a/index.html`: какую форму отдаст хостинг, не понять.
        key = page.key
        kinds[key] = kind if kinds.get(key, kind) == kind else None
        files[key] = os.path.basename(page.path or "")
    order = {"file": 0, "bare": 1, "slash": 2, "index": 3}
    usable = order if host_rewrites else {"file": 0, "bare": 1}
    # Сборку `.next/server` отдаёт сервер Next.js по маршрутам: `/pricing`,
    # а `/pricing.html` — 404.
    by_route = bool(re.search(r"/\.next/server/(app|pages)$",
                              os.path.abspath(root).replace(os.sep, "/").rstrip("/")))
    locale = _next_default_locale(root) if by_route else ""
    for page in flat:
        counted = {f: n for f, n in (votes.get(page.key) or {}).items() if f in usable}
        form = (min(counted, key=lambda f: (-counted[f], order[f])) if counted
                else "bare" if by_route else "file")
        if form in ("slash", "index"):
            continue
        file_url = _file_url(page.path, root, base_url)
        if locale:
            rel = os.path.relpath(page.path, root).replace(os.sep, "/")
            if rel.lower() in (locale + ".html", locale + ".htm"):
                page.url = base_url.rstrip("/") + "/"
                continue
            if rel.startswith(locale + "/"):
                file_url = _file_url(os.path.join(root, rel[len(locale) + 1:]), root, base_url)
        if form == "bare":
            file_url = _EXT_RE.sub("", file_url)
        parts = urlsplit(file_url)
        page.url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    _mark_canonical_forms(pages, root, base_url, redirects, host_rewrites)
    if host_rewrites:
        return
    base = urlsplit(base_url).path.rstrip("/")
    always = {("folder", "file"), ("flat", "slash"), ("flat", "index")}
    for page, forms in written:
        wrong = []
        html = (page.path or "").lower().endswith((".html", ".htm"))
        for key, form, path in forms:
            # `/faq/?x=1` — та же форма адреса, что и `/faq/`.
            key = key.split("?", 1)[0]
            kind = kinds.get(key)
            # `/b/index.md`, `/c.htm` при `c.html`, `/d/INDEX.HTML`: `url_key`
            # сводит их к странице, а хостинг отдаёт файл только под его
            # точным именем. Ссылки из Markdown не трогаем: генератор
            # переписывает `b.md` сам.
            exact = (html and form in ("file", "index")
                     and (kind, form) in (("folder", "index"), ("flat", "file"))
                     and path.rsplit("/", 1)[-1] != files.get(key))
            if (kind, form) not in always and not exact:
                continue
            local = path[len(base):] if base and path.startswith(base + "/") else path
            if not any(regex.match(local) for regex in redirects):
                wrong.append((key, path))
        if wrong:
            page.__dict__["_wrong_forms"] = wrong


def _read_jekyll_config(root: str) -> str:
    try:
        with open(os.path.join(root, "_config.yml"), encoding="utf-8", errors="replace") as fh:
            return fh.read(200_000)
    except OSError:
        return ""


def _jekyll_hidden(name: str, config: str) -> bool:
    """
    Каталог, который Jekyll не публикует: `_layouts`, `_includes`, `_drafts`,
    `_data` и прочие `_`-каталоги. `_posts` публикуется под адресами по дате,
    коллекция из `collections:` конфига — тоже; их не трогаем.
    """
    if not name.startswith("_") or name == "_posts":
        return False
    return not re.search(r"^[ \t]+-?[ \t]*" + re.escape(name[1:]) + r"[ \t]*:?[ \t]*$",
                         config, re.M)


_JEKYLL_POST = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(.+)\.(?:md|markdown|html?)$", re.I)
_JEKYLL_STYLES = {
    "date": "/:categories/:year/:month/:day/:title:output_ext",
    "pretty": "/:categories/:year/:month/:day/:title/",
    "none": "/:categories/:title:output_ext",
}


def _jekyll_post_url(page, root: str, base_url: str, config: str) -> None:
    """
    `_posts/2024-01-05-hello.md` — запись блога Jekyll: адрес строится по
    `permalink` конфига (по умолчанию `/2024/01/05/hello.html`), а не по пути.
    """
    rel = os.path.relpath(page.path, root).replace(os.sep, "/")
    parts = rel.split("/")
    if "_posts" not in parts[:-1]:
        return
    found = _JEKYLL_POST.match(parts[-1])
    meta = page.meta or {}
    if not found or _SAFE_PATH.match((meta.get("permalink") or "").strip()):
        return
    style = re.search(r"^permalink[ \t]*:[ \t]*['\"]?([^'\"\s#]+)", config, re.M)
    template = style.group(1) if style else "date"
    template = _JEKYLL_STYLES.get(template, template)
    if not template.startswith("/") or re.search(r":(?!categories|year|month|day|title"
                                                 r"|output_ext|slug)\w", template):
        return                             # стиль, который здесь не разобрать
    categories = [p for p in parts[:parts.index("_posts")]]
    head = FRONTMATTER.match(page.raw or "")
    if head and head.group(1):
        block = head.group(1)
        line = re.search(r"^categor(?:y|ies)[ \t]*:(.*)$", block, re.M | re.I)
        if line:
            value = line.group(1).strip()
            if value:
                categories += [c for c in re.split(r"[\s,\[\]'\"]+", value) if c]
            else:
                rest = block[line.end():]
                for item in re.finditer(r"^[ \t]*-[ \t]*['\"]?([^'\"\n]+?)['\"]?[ \t]*$|^\S",
                                        rest, re.M):
                    if not item.group(1):
                        break
                    categories.append(item.group(1).strip())
    seen = []
    for c in categories:
        c = c.lower()
        if c not in seen:
            seen.append(c)
    year, month, day, title = found.groups()
    title = (meta.get("slug") or "").strip() or title
    path = template
    for key, value in (("categories", "/".join(seen)), ("output_ext", ".html"),
                       ("year", year), ("month", month), ("day", day),
                       ("title", title), ("slug", title)):
        path = path.replace(":" + key, value)
    path = re.sub(r"/{2,}", "/", path)
    page.url = normalize_url(urljoin(base_url.rstrip("/") + "/",
                                     quote(path.lstrip("/"), safe="/~-._")))


def _next_default_locale(root: str) -> str:
    """
    Язык по умолчанию сборки `.next/server/pages` с i18n: его страницы
    (`en.html`, `en/about.html`) Next.js отдаёт без префикса — `/`, `/about`.
    Берётся из `.next/routes-manifest.json`.
    """
    if os.path.basename(os.path.abspath(root)) != "pages":
        return ""
    up = os.path.dirname(os.path.dirname(os.path.abspath(root)))
    try:
        with open(os.path.join(up, "routes-manifest.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError, RecursionError):
        return ""
    i18n = data.get("i18n") if isinstance(data, dict) else None
    locale = i18n.get("defaultLocale") if isinstance(i18n, dict) else None
    if isinstance(locale, str) and re.fullmatch(r"[A-Za-z0-9-]{2,20}", locale):
        return locale
    return ""


def _host_serves_any_form(root: str) -> tuple:
    """
    (сводит ли хостинг формы адресов сам, отдаёт ли он `/a` без редиректа
    на `/a/`) — то, что не видно по раскладке файлов.

    Сборка `.next/server/app` — это не файлы для статического хостинга: её
    отдаёт сервер Next.js по своим маршрутам, и `about.html` там выходит по
    `/about/`, если в конфиге `trailingSlash: true`. Каталог, скачанный
    `indexgap fetch`, исходники (Jekyll, Eleventy) и `firebase.json` с
    `cleanUrls` или `trailingSlash` — тоже не та раскладка, которую отдаст
    хостинг. Vercel и Azure Static Web Apps без настроек отдают
    `a/index.html` и по `/a`, без редиректа.
    """
    real = os.path.abspath(root).replace(os.sep, "/").rstrip("/")
    up = os.path.dirname(os.path.dirname(os.path.abspath(root)))
    if (re.search(r"/\.next/server/(app|pages)$", real)
            or os.path.isfile(os.path.join(up, "routes-manifest.json"))
            or os.path.isfile(os.path.join(root, FETCH_MANIFEST))
            or any(os.path.exists(os.path.join(root, m)) for m in SOURCE_MARKERS
                   if m not in _REPO_ONLY_MARKERS)):
        # Один `.git` — не исходники: checkout ветки gh-pages и есть то, что
        # отдаёт хостинг.
        return True, True
    near = [root, os.path.dirname(os.path.abspath(root))]
    for folder in near:
        try:
            with open(os.path.join(folder, "firebase.json"), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError, RecursionError):
            continue
        hosting = data.get("hosting") if isinstance(data, dict) else None
        for entry in hosting if isinstance(hosting, list) else [hosting]:
            if isinstance(entry, dict) and ("cleanUrls" in entry or "trailingSlash" in entry):
                return True, True
        break
    bare = any(os.path.isfile(os.path.join(folder, name)) for folder in near
               for name in ("vercel.json", "staticwebapp.config.json"))
    return False, bare


def _mark_canonical_forms(pages: list, root: str, base_url: str,
                          redirects: list, host_rewrites: bool) -> None:
    """
    Отмечает страницы, чей canonical объявляет её же адрес, но в форме,
    которой раскладка файлов не отдаёт (`_canonical_form` страницы).

    Свой canonical страница сохраняет: адрес из него уезжает в sitemap и
    hreflang, а ссылки в той же форме не отмечаются, — так и задумано, на
    хостинге, который эту форму отдаёт, всё сходится. Но `about.html` с
    canonical `/about/` и `a/index.html` с canonical `/a.html` — это 404 на
    GitHub Pages, S3 и nginx, а `a/index.html` с canonical `/a` — редирект
    на `/a/`. Раньше такое проходило молча.

    Не отмечается то, что хостинг сводит сам: `cleanUrls` и `trailingSlash`
    в vercel.json, правило перенаправления, которое ловит этот путь, и
    раскладки, по которым форму не узнать (`_host_serves_any_form`).
    """
    if host_rewrites:
        return
    declared = [p for p in pages if p.__dict__.get("_url_declared")
                and (p.path or "").lower().endswith((".html", ".htm"))]
    if not declared:
        return
    any_form, bare_ok = _host_serves_any_form(root)
    if any_form:
        return
    base = urlsplit(base_url).path.rstrip("/")
    for page in declared:
        path = urlsplit(page.url).path or "/"
        local = path[len(base):] if base and path.startswith(base + "/") else path
        if local in ("", "/") or local == base:
            continue
        name = os.path.basename(page.path).lower()
        last = local.rstrip("/").rsplit("/", 1)[-1].lower()
        if name.startswith("index."):
            # `a/index.html`: отдаётся по /a/ и /a/index.html — но не по
            # /a/index.htm и не по /a/index.md.
            if local.endswith("/") or last == name:
                continue
            if last.startswith("index.") and not _EXT_RE.search(last):
                continue
            form = "file" if _EXT_RE.search(last) else "bare"
            if form == "bare" and bare_ok:
                continue
        else:
            # `about.html`: отдаётся по /about.html и /about.
            if local.endswith("/"):
                form = "slash"
            elif last.startswith("index.") and _EXT_RE.search(last):
                form = "index"
            elif _EXT_RE.search(last) and last != name:
                form = "file"             # /about.htm при about.html
            else:
                continue
        if any(regex.match(local) for regex in redirects):
            continue
        # Форма, которую раскладка отдаёт: /a/ для папки, /about.html для файла.
        served = urlsplit(_file_url(page.path, root, base_url)).path
        if name.startswith("index."):
            served = served.rsplit("/", 1)[0] + "/"
        page.__dict__["_canonical_form"] = (form, served)


FETCH_MANIFEST = "fetch.json"
FETCH_GENERATOR = "indexgap fetch"


def _apply_fetch_manifest(pages: list, root: str, base_url: str) -> None:
    """
    Каталог, скачанный `indexgap fetch`: адрес страницы — тот, с которого она
    пришла, а не тот, что угадывается по имени файла.

    По имени угадывается не всё: `/flat` и `/flat.html` лежат одним файлом
    `flat.html`, а `/page.php` — файлом `page.php.html`. Ключи сходятся и без
    манифеста; точную форму адреса знает только он.
    """
    path = os.path.join(root, FETCH_MANIFEST)
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError, RecursionError):
        return
    if not isinstance(data, dict) or data.get("generator") != FETCH_GENERATOR:
        return
    where = {}
    for entry in data.get("pages") or ():
        if (isinstance(entry, dict) and isinstance(entry.get("file"), str)
                and isinstance(entry.get("final_url"), str)):
            where[unicodedata.normalize("NFC", entry["file"])] = entry["final_url"]
    if not where:
        return
    site = urlsplit(base_url)
    for page in pages:
        rel = unicodedata.normalize(
            "NFC", os.path.relpath(page.path, root).replace(os.sep, "/"))
        url = where.get(rel)
        if url:
            page.url = urlunsplit((site.scheme, site.netloc, urlsplit(url).path or "/", "", ""))


def load_pages(root: str, base_url: str, exts=DEFAULT_EXTS, jobs: int = 1) -> tuple:
    """
    Возвращает (страницы, проблемы). Проблемы — это файлы, которые не прочитались,
    и страницы с совпавшими URL. Раньше первый же битый симлинк ронял весь прогон,
    а два файла с одинаковым URL молча давали дубль в sitemap.
    """
    pages, problems, by_key, loaded, fragments = [], [], {}, [], []
    todo, maybe_error = [], set()
    source_repo = any(os.path.exists(os.path.join(root, m)) for m in SOURCE_MARKERS)
    # Исходники для GitHub Pages: `.md` без шапки там собирается в страницу,
    # а README.md становится главной, если своей главной в каталоге нет.
    jekyll = os.path.isfile(os.path.join(root, "_config.yml"))
    jekyll_config = _read_jekyll_config(root) if jekyll else ""
    def unreadable(exc):
        if not os.path.isdir(root):
            return                  # нет самого каталога — об этом скажут выше
        # Каталог без прав на чтение или со слишком длинным путём раньше
        # пропадал молча: «разобрано страниц: 1» — и ни слова о том, что ещё.
        problems.append(tr("{a0}: каталог не прочитан ({a1}) — страницы в нём не проверялись",
                           a0=getattr(exc, "filename", "") or root,
                           a1=getattr(exc, "strerror", "") or exc))

    # Каталог-симлинк сервер отдаёт как обычный, а обход его молча пропускал:
    # страницы в нём не проверялись, ссылки на них считались битыми. Идём по
    # ссылкам наружу; ссылку внутрь сборки (её страницы и так обойдены) и на
    # каталог выше (петля) не трогаем.
    real_root = os.path.realpath(root)
    walked = {real_root}

    def follow(dirpath, name):
        path = os.path.join(dirpath, name)
        if not os.path.islink(path):
            return True
        real = os.path.realpath(path)
        if (real in walked or real.startswith(real_root + os.sep)
                or real_root.startswith(real.rstrip(os.sep) + os.sep)):
            return False
        walked.add(real)
        return True

    for dirpath, dirnames, filenames in os.walk(root, onerror=unreadable, followlinks=True):
        dirnames[:] = [d for d in dirnames if follow(dirpath, d)]
        skip = set(ALWAYS_SKIP)
        if dirpath == root and source_repo:
            skip |= BUILD_DIRS
            for name in sorted(d for d in dirnames if d in BUILD_DIRS):
                if _has_pages(os.path.join(root, name), exts):
                    problems.append(tr(
                        "каталог {a0}/ пропущен как сборочный. Если проверять "
                        "нужно собранный сайт — передай его каталог явно.", a0=name))
        # Порядок обхода — по имени: readdir отдаёт каталоги в порядке
        # файловой системы, и список «первых пяти» менялся от машины к машине.
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d not in skip and d not in OWN_DIRS
                             and not (jekyll and _jekyll_hidden(d, jekyll_config)))
        for name in sorted(filenames):
            if name.startswith(".") or name.lower() in OWN_FILES:
                continue
            if jekyll and name.startswith("_"):
                continue                   # Jekyll не публикует `_`-файлы
            if not name.lower().endswith(exts):
                continue
            path = os.path.join(dirpath, name)
            # Страница ошибки — не страница сайта: на неё никто не ссылается,
            # она короткая, и в sitemap ей не место. Её выдаёт почти любой
            # генератор, и каждая получала «сироту» и «тонкую».
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            top_error = _TOP_ERROR.match(rel)
            if (_ERROR_FILE.search(rel) or _DYNAMIC_ROUTE.search(rel)
                    or (top_error and "/" not in rel[:top_error.start(1)])):
                continue
            # `en/404.html` — служебная в корне языка, но `api/404/` — может
            # быть и раздел: решают ссылки.
            if top_error or (_ERROR_PAGE.search(rel) and not _numbered_sibling(path)):
                # `status/404/index.html` в глубине сборки — это может быть
                # статья про код ответа, а не страница ошибки. Её судьбу
                # решают ссылки: на страницу ошибки сайт не ссылается.
                maybe_error.add(path)
            # GitHub Pages собирает Jekyll и без _config.yml; README.md —
            # главная и у Docsify, MkDocs, GitBook. В проекте с исходниками
            # другого генератора — нет.
            readme_home = ((jekyll or not source_repo) and name.lower() == "readme.md"
                           and not any(f.lower().startswith("index.") for f in filenames))
            todo.append((path, root, base_url, readme_home))
    for kind, path, value in _parse_all(todo, jobs):
        if kind == "page" and jekyll:
            _jekyll_post_url(value, root, base_url, jekyll_config)
        if kind == "error":
            problems.append(value)
        elif kind == "fragment":
            fragments.append(path)
        elif kind == "page":
            # Строки, пришедшие из разных процессов, — разные объекты.
            value.anchors = list(map(sys.intern, value.anchors))
            loaded.append(value)
    if maybe_error:
        linked = {url_key(link) for page in loaded if page.path not in maybe_error
                  for link in page.links}
        dropped = sorted(page.url for page in loaded if page.path in maybe_error
                         and page.key not in linked
                         and re.search(r"/index\.html?$", page.path.replace(os.sep, "/"), re.I))
        loaded = [page for page in loaded
                  if page.path not in maybe_error or page.key in linked]
        # Статья `/http/404/` без входящих ссылок неотличима от страницы
        # ошибки — но молча пропадать ей нельзя: в sitemap её не будет, а
        # сирота — ровно то, что sitemap должен вывести к поисковику.
        if dropped:
            problems.append(tr(
                "{a0} страниц(ы) в каталоге с именем кода ответа (…/404/) никто не "
                "ссылается — сочтены страницами ошибки, не проверялись и в sitemap не "
                "попадут: {a1}. Если это статьи — поставь на них ссылку",
                a0=len(dropped), a1=", ".join(dropped[:3]) + (" …" if len(dropped) > 3 else "")))
    # Сырой markdown убирается до разбора совпавших адресов: иначе двойник
    # `guide.md` побеждал `guide.html` по числу ссылок, потом выбрасывался как
    # сырой файл — и страница пропадала вовсе.
    loaded, raw_md = (loaded, []) if jekyll else _drop_raw_markdown(loaded, root)
    _settle_flat_urls(loaded, root, base_url)
    _apply_fetch_manifest(loaded, root, base_url)
    _apply_header_rules(loaded, root, base_url, problems)
    if fragments:
        problems.append(tr(
            "{a0} файл(ов) HTML — куски шаблонов без <html> и <title>, а не страницы; "
            "не проверялись: {a1}", a0=len(fragments),
            a1=", ".join(os.path.relpath(p, root).replace(os.sep, "/") for p in fragments[:5])))
    position = {}
    for page in loaded:
        other = by_key.get(page.key)
        if other is None:
            by_key[page.key] = page
            position[page.key] = len(pages)
            pages.append(page)
            continue
        # Из двух файлов с одним адресом берём содержательный, а не тот,
        # что раньше встретился в обходе: заглушка `about.html` рядом
        # с настоящей `about/index.html` уносила её исходящие ссылки,
        # и целевые страницы становились ложными сиротами.
        keep, drop = ((page, other)
                      if (len(page.links), len(page.text)) >
                         (len(other.links), len(other.text))
                      else (other, page))
        problems.append(
            tr("{a0} и {a1} дают один URL {a2} — взят {a3}, второй пропущен", a0=os.path.relpath(drop.path, root), a1=os.path.relpath(keep.path, root), a2=keep.url, a3=os.path.relpath(keep.path, root)))
        if keep is page:
            # Место по словарю: `pages.index` сравнивал страницы целиком,
            # и сайт, где у каждой страницы есть двойник, грузился за квадрат.
            pages[position[page.key]] = page
            by_key[page.key] = page
    if raw_md:
        problems.append(tr(
            "{a0} файл(ов) .md рядом со сборкой HTML — это файлы, которые сайт отдаёт "
            "как есть, а не страницы; не проверялись: {a1}",
            a0=len(raw_md), a1=", ".join(os.path.relpath(p, root) for p in raw_md[:5])))
    _settle_canonical_origins(pages, base_url, problems)
    pages.sort(key=lambda p: p.url)
    return pages, problems


def _origin(url: str):
    """
    (схема, хост) адреса: порт по умолчанию и punycode не различаются,
    `www.` — различается: это другой хост и настоящий редирект.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    scheme, host = parts.scheme.lower(), parts.netloc.lower()
    default = {"https": ":443", "http": ":80"}.get(scheme)
    if default and host.endswith(default):
        host = host[: -len(default)]
    if not host.isascii():
        try:
            name, colon, rest = host.partition(":")
            host = name.encode("idna").decode("ascii") + colon + rest
        except UnicodeError:
            pass
    return scheme, host


def _settle_canonical_origins(pages: list, base_url: str, problems: list) -> None:
    """
    Canonical на `http://` или `www.`-версию той же страницы — это canonical
    на другой адрес: поисковик считает страницу копией того адреса. Ключ
    `url_key` схему и `www.` снимает (так сравниваются ссылки), и такая
    страница считалась «сама на себя» и уезжала в sitemap.

    Сверяется не с --site, а с тем, как называет себя сам сайт: адрес,
    которым пишет canonical большинство страниц. Неверный --site не делает
    каждую страницу находкой — о нём одна заметка. Голосуют только canonical,
    записанные полным адресом: относительный достроен от --site и о сайте
    ничего не говорит. Если большинства нет, мерило — --site.

    Относительный canonical на себя всё же голос: браузер достраивает его от
    того адреса, по которому страница отдана. Без этого два canonical на
    `http://` из восьми страниц перевешивали сайт. `//www.host/a/` сверяется
    только по хосту: схему он берёт у запроса.
    """
    votes, neutral, host_only = [], 0, []
    for page in pages:
        if not page.canonical or url_key(page.canonical) != page.key:
            continue
        if page.__dict__.get("_canonical_host_only"):
            host_only.append(page)
        elif page.__dict__.get("_canonical_absolute"):
            origin = _origin(page.canonical)
            if origin:
                votes.append((page, origin))
        else:
            neutral += 1
    site = _origin(base_url)
    if not votes and not host_only:
        return
    counts = Counter(origin for _, origin in votes)
    if site is not None and neutral:
        counts[site] += neutral
    if not counts and site is not None:
        counts[site] = 0
    if not counts:
        return
    top, count = max(counts.items(),
                     key=lambda item: (item[1], item[0] == site, item[0][0] == "https"))
    total = len(votes) + (neutral if site is not None else 0)
    home = top if count * 2 > total else site
    if home is None:
        return
    for page, origin in votes:
        if origin != home:
            page.__dict__["_canonical_origin"] = "%s://%s" % home
    for page in host_only:
        origin = _origin(page.canonical)
        if origin and origin[1] != home[1]:
            page.__dict__["_canonical_origin"] = "%s://%s" % home
    if site is not None and home != site:
        problems.append(tr(
            "canonical {a0} из {a1} страниц называют сайт адресом {a2}, а --site — {a3}. "
            "Страницы сверены с {a2}; адреса в sitemap и в отчёте строятся от --site — "
            "если сайт живёт по {a2}, укажи --site {a2}",
            a0=count, a1=total, a2="%s://%s" % home, a3="%s://%s" % site))


def _parse_one(job):
    """Разбор одного файла: то, что раньше делалось в цикле load_pages."""
    path, root, base_url, readme_home = job
    try:
        page = load_page(path, root, base_url, as_index=readme_home)
    except SourceError as exc:
        return "error", path, str(exc)
    if REPORT_MARK in (page.raw or "")[:400]:
        return "skip", path, None
    if not path.lower().endswith((".md", ".markdown")):
        # Кусок шаблона — не страница. В собранный сайт попадают
        # `partials/nav.html`, `_static/webpack-macros.html`,
        # `_includes/head.html`: без <html>, <head> и <title>. Каждый
        # получал «сироту» и «нет title».
        if _is_fragment(page.raw):
            return "fragment", path, None
        page.raw = essence(page.raw)
    # Меню mdBook и rustdoc — сотни одинаковых подписей на каждой странице.
    page.anchors = list(map(sys.intern, page.anchors))
    return "page", path, page


def _parse_chunk(jobs):
    return [_parse_one(job) for job in jobs]


def _init_worker(lang):
    from . import i18n
    i18n.set_lang(lang)


PARALLEL_FROM = 2000


def _parse_all(todo: list, jobs: int = 1) -> list:
    """
    Разбор HTML — две трети времени прогона, и он независим по файлам.
    По просьбе вызывающего (CLI) он идёт в нескольких процессах; порядок
    результата — порядок обхода, так что вывод не меняется. Библиотечный вызов
    остаётся однопроцессным: spawn на macOS и Windows заново импортирует
    чужой __main__.
    """
    if jobs < 2 or len(todo) < PARALLEL_FROM:
        return [_parse_one(job) for job in todo]
    from concurrent.futures import ProcessPoolExecutor
    from . import i18n
    size = 64
    chunks = [todo[i:i + size] for i in range(0, len(todo), size)]
    try:
        with ProcessPoolExecutor(jobs, initializer=_init_worker,
                                 initargs=(i18n.get_lang(),)) as pool:
            return [item for part in pool.map(_parse_chunk, chunks) for item in part]
    except (OSError, ImportError, NotImplementedError, RuntimeError):
        # Нет процессов (песочница, Lambda) — разбираем по-старому.
        return [_parse_one(job) for job in todo]


def default_jobs() -> int:
    """INDEXGAP_JOBS, иначе число ядер, но не больше восьми."""
    try:
        value = int(os.environ.get("INDEXGAP_JOBS") or 0)
    except ValueError:
        value = 0
    return value or min(8, os.cpu_count() or 1)

def _numbered_sibling(path: str) -> bool:
    """
    `product/401/` рядом с `product/402/` — карточка каталога с номером, а не
    страница ошибки: у соседей тоже номера, и не коды ответа. Без этого
    непривязанная карточка выпадала молча и уносила с собой находку «сирота».
    """
    folder = os.path.dirname(path)
    own = os.path.basename(path)
    if own.lower().startswith("index."):
        own, folder = os.path.basename(folder), os.path.dirname(folder)
    own = own.split(".")[0]
    try:
        names = os.listdir(folder)
    except OSError:
        return False
    for name in names:
        stem = name.split(".")[0]
        if (stem != own and stem.isdigit() and len(stem) == len(own)
                and not _ERROR_PAGE.search(stem + ".html")):
            return True
    return False


def _has_pages(path: str, exts) -> bool:
    for _dirpath, _dirnames, filenames in os.walk(path):
        if any(name.lower().endswith(exts) for name in filenames):
            return True
    return False


_PAGE_SIGNS = ("<!doctype", "<html", "<head", "<body", "<title")


def _is_fragment(raw: str) -> bool:
    """
    HTML без единого признака целого документа — заготовка шаблона. Как и файл
    с командами шаблонизатора (`{% macro %}`) и без <title>: отрисованная
    страница их не содержит.
    """
    head = (raw or "")[:20000].lower()
    if not head.strip():
        return False
    if not any(sign in head for sign in _PAGE_SIGNS):
        return True
    return "<title" not in head and bool(re.search(r"\{%-?\s*\w+", head))


_ERROR_PAGE = re.compile(
    r"(^|/)(40[134]|50[0-4x]|5xx|4xx|offline|_not-found|not-found|_error)"
    r"(\.html?|/index\.html?)$", re.I)
# Имена, которые генераторы дают только служебным файлам, на любой глубине:
# `_not-found` и `_global-error` Next.js, оболочка gatsby-plugin-offline.
_ERROR_FILE = re.compile(
    r"(^|/)(5xx|4xx|_not-found|_error|_global-error|offline-plugin-app-shell-fallback)"
    r"(\.html?|/index\.html?)$", re.I)
# `[slug].html`, `[...path].html` — оболочка динамического маршрута Next.js
# (fallback getStaticPaths), а не адрес: по `/blog/%5Bslug%5D.html` никто не ходит.
_DYNAMIC_ROUTE = re.compile(r"(^|/)\[[^/\[\]]+\]\.html?$", re.I)
# Коды и `200.html` (запасной вход SPA у Nuxt, SvelteKit, Surge) — служебные
# только в корне сборки или в корне языка: `status/404/` в глубине — обычная
# страница, если на неё ссылаются.
_TOP_ERROR = re.compile(
    r"^(?:[a-z]{2,3}(?:[-_][a-z0-9]{2,8})*/)?"
    r"(40[134]|50[0-4x]|200|offline|not-found)(\.html?|/index\.html?)$", re.I)


# Каталоги вложений: `.md` в них — пример или ресурс (Docsify `_media`), а не страница.
_ASSET_DIRS = {"_media", "_assets", "assets", "_static", "static", "_images", "images",
               "_files", "files", "_attachments", "_resources"}


def _drop_raw_markdown(pages: list, root: str = None) -> tuple:
    """
    `.md` рядом со сборкой HTML без front matter — файл, а не исходник:
    `auth.md`, `llms.md`, markdown-двойники страниц для агентов. Jekyll и Hugo
    без front matter такой файл страницей не делают, и живой сайт отдаёт его
    как text/markdown. Где HTML нет, markdown — исходник, и он читается.
    """
    html = [p for p in pages if p.path.lower().endswith((".html", ".htm"))]
    if not html:
        return pages, []
    md = [p for p in pages if p.path.lower().endswith((".md", ".markdown"))]
    # Сборка, а не исходники: HTML-страниц не меньше, чем markdown. Тогда .md —
    # то, что генератор положил рядом: `index.source.md` Hugo у каждой
    # страницы, двойники для агентов. Ничто в готовой сборке .md страницей
    # не делает, с шапкой он или без.
    built = len(html) >= len(md)
    page_dirs = {os.path.dirname(p.path) for p in html
                 if os.path.basename(p.path).lower().startswith("index.")}
    kept, dropped = [], []
    for page in pages:
        if page.path.lower().endswith((".md", ".markdown")):
            try:
                with open(page.path, "rb") as fh:
                    head = fh.read(8).lstrip(b"\xef\xbb\xbf")
            except OSError:
                head = b""
            folder = os.path.dirname(page.path)
            asset = any(part.lower() in _ASSET_DIRS for part in
                        os.path.relpath(folder, root or os.path.dirname(html[0].path)).split(os.sep))
            if (built or folder in page_dirs or asset
                    or not head.startswith((b"---", b"+++"))):
                dropped.append(page.path)
                continue
        kept.append(page)
    return kept, dropped


# ── манифест ──────────────────────────────────────────────────────────────────

def load_manifest(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        text, _ = read_text(path)
        data = json.loads(text)
    except (json.JSONDecodeError, SourceError, OSError):
        # Битый манифест — не повод молча начать с нуля: пусть вызывающий скажет.
        return {"_broken": True}
    return data if isinstance(data, dict) else {"_broken": True}


def save_manifest(path: str, data: dict) -> None:
    """
    Запись атомарная: сначала во временный файл, потом переименование.
    Сбой на середине оставлял битый JSON, который читался как пустой,
    и вся история lastmod терялась.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    # Имя временного файла своё у каждого процесса: два одновременных прогона
    # с общим именем отнимали файл друг у друга прямо перед переименованием.
    tmp = os.path.join(directory, f".{os.path.basename(path)}.{os.getpid()}.tmp")
    # `_broken` — служебный флаг чтения, наружу он не пишется. Остальные
    # служебные ключи (например список созданных шардов) сохраняются:
    # без них пакет не знает, какие файлы он вправе убирать за собой.
    payload = {k: v for k, v in data.items() if k != "_broken"}
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
