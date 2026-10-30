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
from collections import Counter, defaultdict
from html import unescape as html_unescape
from html.parser import HTMLParser
from urllib.parse import (urljoin, urlparse, urldefrag, urlsplit, urlunsplit,
                          quote, unquote)

from .i18n import tr
from . import __version__

# Без заголовка urllib шлёт `Python-urllib/3.x`, и многие WAF режут такой агент
# по умолчанию: sitemap rumors.app отдавал пакету 403, а curl — 200. Под
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
# берёт, и «सिंगापुर» распадалось на четыре куска — счётчик слов на хинди и
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
    outline: list = None                           # заголовки без шаблона: вне <aside>, <footer>, <nav>
    slots: list = None                             # следы незаполненного шаблона: (вид, образец)

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


# ── URL ───────────────────────────────────────────────────────────────────────

_EXT_RE = re.compile(r"\.(html?|md|markdown)$", re.I)
_BARE_INDEX = re.compile(r"(^|/)index$", re.I)
_INDEX_RE = re.compile(r"(^|/)index\.(html?|md|markdown)$", re.I)


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
    rel = _EXT_RE.sub("", rel)
    if rel in (".", ""):
        rel = ""
    # Пробелы и кириллица в имени файла обязаны уехать в URL закодированными,
    # иначе sitemap невалиден, а ссылка на страницу с ней не сойдётся.
    rel = "/".join(quote(seg, safe="~-._") for seg in rel.split("/"))
    url = urljoin(base_url.rstrip("/") + "/", rel)
    return normalize_url(url, directory=True)


def _file_url(path: str, root: str, base_url: str) -> str:
    """Адрес самого файла, с именем и расширением: от него считаются ссылки."""
    rel = unicodedata.normalize("NFC", os.path.relpath(path, root).replace(os.sep, "/"))
    rel = "/".join(quote(seg, safe="~-._") for seg in rel.split("/"))
    return urljoin(base_url.rstrip("/") + "/", rel)


def check_site_url(site: str) -> str:
    """
    Адрес сайта нужен целиком, со схемой. `example.com` молча даёт URL вида
    `example.com/page/`, невалидный sitemap и сломанный подсчёт внутренних ссылок.
    """
    site = (site or "").strip()
    if not site:
        raise SourceError(tr("Не указан адрес сайта. Добавь --site https://example.com"))
    parts = urlsplit(site)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        guess = site.split("//")[-1].strip("/")
        raise SourceError(
            tr("--site {a0} — так не годится: нужен полный адрес со схемой.\n    Попробуй: --site https://{a1}", a0=site, a1=guess))
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
           "utf-16-be": "utf-8"}
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
    return "cp1251" if paired / high > 0.4 else "cp1252"



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
                break

    utf16 = _bomless_utf16(data)
    if utf16:
        try:
            return data.decode(utf16), utf16
        except UnicodeDecodeError:
            pass

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
        if _mostly_utf8(data):
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

class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.canonical = ""
        self.robots = ""
        self.lang = ""
        self.base = ""
        self.hrefs = []
        self.headings = []
        # Те же заголовки без врезок, подвала и меню. `no-question-headings`
        # считал колонки подвала и «Keep reading» заголовками статьи: на
        # eventiq.io это 40% подзаголовков медианной страницы.
        self.outline = []
        self._chrome_stack = []
        # Видимый текст без кода — для поиска швов шаблона. Собирается тем же
        # проходом: второй разбор исходника стоил пятую часть времени загрузки.
        self._code_stack = []
        self.visible = []
        self._br_run = False       # последним в тексте был <br>, а после него — ничего
        self.anchors = []
        self.jsonld = []
        self.alternates = []       # (код hreflang как написан, href)
        self.blocks = {"li": 0, "table": 0, "img": 0, "img_no_alt": 0,
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

    # -- служебное ------------------------------------------------------------

    @property
    def _in_main(self) -> bool:
        return bool(self._main_stack)

    def _emit(self, text: str):
        target = self._main_chunks if self._in_main else self._chunks
        target.append((text, self._glue))
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
        while self._code_stack and self._code_stack[-1] > self._depth:
            self._code_stack.pop()
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
        if tag == "script" and "ld+json" in a.get("type", "").lower():
            self._in_ld = True
            self._ld_buf = ""
            self._skip_depth += 1
            return
        if tag in SKIP_TAGS:
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

        if tag not in INLINE_TAGS:
            self._glue = False

        if tag not in VOID_TAGS:
            self._imply_end(tag)
            self._open.append(tag)
            self._open_count[tag] += 1
            self._depth = len(self._open)
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
        # последней ячейки и весь <dl> были одним «абзацем»: на eventiq.io
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
            elif tag == "table":
                self.blocks["table"] += 1
            elif tag == "p":
                self.blocks["p"] += 1
            elif tag == "img":
                self.blocks["img"] += 1
                if not a.get("alt", "").strip():
                    self.blocks["img_no_alt"] += 1
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
                self.description = content
            elif name in ("robots", "googlebot"):
                self.robots = (self.robots + "," + content).strip(",")
            elif name and content:
                # author, article:published_time, article:modified_time и прочее:
                # раньше они были невидимы, и на каждой HTML-странице выдавались
                # «нет даты» и «нет автора» — 402 ложные находки на 201 странице.
                self.meta.setdefault(META_ALIASES.get(name, name), content)
        elif tag == "link":
            rel = a.get("rel", "").lower()
            if "canonical" in rel:
                self.canonical = a.get("href", "").strip()
            # Альтернативы hreflang собираются здесь же, за тот же проход.
            # Раньше их читал отдельный разбор того же документа, и не один
            # раз: на каталоге в четыре тысячи страниц это было сорок секунд
            # из шестидесяти восьми.
            if "alternate" in rel.split() and a.get("hreflang"):
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

    def handle_startendtag(self, tag, attrs):
        # `<path/>` внутри пропускаемого <svg> ничего не открывал: starttag
        # вышел раньше, чем дошёл до стека. Закрывать за него нечего — раньше
        # он закрывал <main>, и текст после иконки пропадал со страницы.
        skipping = bool(self._skip_depth)
        self.handle_starttag(tag, attrs)
        if tag in SKIP_TAGS:
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
        if tag in SKIP_TAGS:
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
        self._emit(text)
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


# Служебные блоки внутри основного текста. На eventiq.io крошки, подпись и
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
_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
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


def _is_aside(tag: str, attrs: dict) -> bool:
    if tag == "nav" or attrs.get("role", "").lower() == "navigation":
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
EMPTY_MOUNT = re.compile(
    r"<div[^<>]{0,300}\bid\s*=\s*[\"']?(?:root|app|__next|__nuxt|svelte|q-app)[\"']?"
    r"[^<>]{0,300}>\s*</div>", re.I)
_HTML_OPEN = re.compile(r"<html\b[^<>]{0,2000}>", re.I)
_REFRESH_META = re.compile(r"<meta\b[^<>]{0,2000}>", re.I)
_TIME_TAG = re.compile(r"<time\b[^<>]{0,500}>", re.I)
_NEXT_SCRIPT = re.compile(r"NEXT_REDIRECT[^<]{0,300}")


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
MOJIBAKE = re.compile(r"â€[\u0080-\u00bf\u2018-\u201e\u2122\u0153\u02dc]|Ã[\u0080-\u00bf]"
                      r"|Ð[\u0080-\u00bf]Ð|Ñ[\u0080-\u008f]")


def visible_text(raw: str) -> str:
    """Текст, который видит читатель: без кода, скриптов, <head> и комментариев."""
    return html_unescape(_TAG.sub(" ", drop_spans(raw or "", NOT_VISIBLE)))


def find_slots(text: str, markdown: bool = False) -> list:
    """
    Следы незаполненного шаблона в тексте: [(вид, образец)], не больше трёх
    образцов на вид. В исходнике Markdown `{{ }}` и `{% %}` — синтаксис Hugo
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
             ("mojibake", MOJIBAKE, ("ã", "â€", "ð", "ñ"))]
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
            if len(samples) >= (12 if kind == "bracket" else 3):
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
            parts += [m for m in _REFRESH_META.findall(live) if "equiv" in m.lower()]
        parts += [f"<script>{m}</script>" for m in _NEXT_SCRIPT.findall(live)]
    parts += _TIME_TAG.findall(raw)
    mount = EMPTY_MOUNT.search(raw)
    if mount:
        parts.append(mount.group(0))
    if any(marker in raw for marker in BRIEF_MARKERS):
        prose = drop_spans(raw, NOT_PROSE)
        parts += [marker for marker in BRIEF_MARKERS if marker in prose]
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


# Таблицу в Markdown пишут и тегами: в исходниках eventiq.io все таблицы такие.
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
    return re.split(r"\s#", value, 1)[0].strip() if " #" in value or "\t#" in value else value


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
            wrapped = []
            while i < len(lines) and (not lines[i].strip()
                                      or lines[i][:1] in (" ", "\t", "-")):
                nxt = lines[i]
                i += 1
                stripped = nxt.strip()
                if not stripped:
                    continue
                if nxt[:1] == "-" or ":" in stripped.split(" ")[0]:
                    wrapped = []          # список или вложенный объект — не значение
                    continue
                wrapped.append(stripped)
            if not wrapped:
                continue
            value = " ".join(wrapped)
        else:
            value = _yaml_scalar(value)
        value = _clean(_unquote_value(value))
        if value:
            out[key] = value
    return out


# ── страница ──────────────────────────────────────────────────────────────────

def load_page(path: str, root: str, base_url: str, as_index: bool = False) -> Page:
    raw, encoding = read_text(path)
    notes = []
    if not is_utf8(encoding):
        notes.append(tr("файл прочитан как {a0}, а не UTF-8", a0=encoding))
    elif "\ufffd" in raw:
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
        md_anchors = [text.strip() for text, _ in matches]
        md_headings = [(len(h), _clean(t)) for h, t in MD_HEADING.findall(_strip_fences(body))]
        base_href = ""
        text = _strip_markdown(body)
        # Без шапки заголовком страницы становится первый заголовок текста —
        # так делает GitHub Pages. При шапке без title это не действует:
        # там отсутствие title — находка.
        if not m and not toml and md_headings and md_headings[0][0] == 1:
            meta = {"title": md_headings[0][1]}
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
            slots=find_slots(text, markdown=True),
            blocks={"li": _md_list_items(_strip_fences(body)),
                    "table": len(re.findall(r"^[ \t>]*\|[^\n]+\|[ \t]*$", body, re.M)) and 1 or 0,
                    "img": len(re.findall(r"!\[[^\[\]\n]{0,1000}\]\(", body)),
                    "img_no_alt": len(re.findall(r"!\[[ \t]*\]\(", body)),
                    "script": 0, "p": 0},
        )
    else:
        ex = _Extractor()
        ex.feed(raw)
        ex.close()
        hrefs = ex.hrefs
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
            headings=ex.headings,
            outline=ex.outline,
            slots=find_slots(" ".join(ex.visible)),
            anchors=ex.anchors,
            raw=raw,
            encoding=encoding,
            notes=notes,
            jsonld=ex.jsonld,
            alternates=ex.alternates,
            paragraphs=ex.paragraphs,
            blocks=ex.blocks,
        )

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
    if page.canonical:
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
            if own.path != urlsplit(page.url).path:
                site_parts = urlsplit(page.url)
                page.url = urlunsplit((site_parts.scheme, site_parts.netloc, own.path, "", ""))
    seen = set()
    forms = []
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
        form = ("file" if _EXT_RE.search(raw_path) else
                "slash" if raw_path.endswith("/") else "bare")
        absolute = normalize_url(absolute)
        key = url_key(absolute)
        if key != page.key and key not in seen:
            seen.add(key)
            page.links.append(absolute)
            forms.append((key, form))
    page.__dict__["_link_forms"] = forms
    if foreign:
        page.__dict__["_foreign_links"] = foreign

    return page


# ── X-Robots-Tag из файлов хостинга ──────────────────────────────────────────

def _route_regex(pattern: str):
    """`/glossary/*` (Netlify) или `/glossary/(.*)`, `/:slug*` (Vercel) → выражение."""
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("(.*)", i):
            out.append(".*")
            i += 4
            continue
        if ch == "*":
            out.append(".*")
        elif ch == ":":
            m = re.match(r":\w+(\*|\+)?", pattern[i:])
            if m:
                out.append(".*" if m.group(1) else "[^/]+")
                i += len(m.group(0))
                continue
            out.append(re.escape(ch))
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("".join(out) + "$")


_TOML_FOR = re.compile(r"""^\s*for\s*=\s*["']([^"']+)["']""", re.M)
_TOML_TAG = re.compile(r"""^\s*["']?X-Robots-Tag["']?\s*=\s*["']([^"']+)["']""", re.I | re.M)


def _closes(value: str) -> bool:
    """
    Закрывает ли значение X-Robots-Tag страницу для Google. Директива с
    именем бота (`bingbot: noindex`, `googlebot-news: noindex`) действует
    только на него.
    """
    agent = ""
    for token in re.split(r"[,\s]+", (value or "").lower()):
        if token.endswith(":") and len(token) > 1:
            agent = token[:-1]
            continue
        if ":" in token:
            agent, _, token = token.partition(":")
        if token in ("noindex", "none") and agent in ("", "googlebot"):
            return True
    return False


def _same_host(a: str, b: str) -> bool:
    a, b = (a or "").lower().split(":")[0], (b or "").lower().split(":")[0]
    strip = lambda h: h[4:] if h.startswith("www.") else h
    return bool(a) and strip(a) == strip(b)


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


def header_noindex_rules(root: str, host: str = "") -> list:
    """
    Правила X-Robots-Tag: noindex из `_headers` (Netlify, Cloudflare Pages),
    `netlify.toml` и `vercel.json` — в сборке и уровнем выше.

    Тот же noindex, отданный заголовком, был невидим: 88 страниц глоссария
    закрывались из `_headers`, а отчёт показывал их открытыми.

    Каждое правило — (выражение, файл, шаблон, закрывает ли). Правило с чужим
    хостом (`https://:project.pages.dev/*` — рецепт Cloudflare для превью)
    к сайту не относится; `! X-Robots-Tag` в `_headers` снимает заголовок —
    это правило «открывает».
    """
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
            if name.strip().lower() == "x-robots-tag" and _closes(value):
                rules.append((_route_regex(path), "_headers", current, True))
    for folder in near:
        toml = os.path.join(folder, "netlify.toml")
        if not os.path.isfile(toml):
            continue
        try:
            text, _ = read_text(toml)
        except SourceError:
            text = ""
        for block in text.split("[[headers]]")[1:]:
            block = block.split("[[", 1)[0]
            where, tag = _TOML_FOR.search(block), _TOML_TAG.search(block)
            if where and tag and _closes(tag.group(1)):
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
                        and _closes(str(header.get("value", "")))):
                    rules.append((_route_regex(entry["source"]), "vercel.json",
                                  entry["source"], True))
        break
    return rules


def _apply_header_rules(pages: list, root: str, base_url: str, problems: list) -> None:
    rules = header_noindex_rules(root, urlsplit(base_url).netloc)
    if not any(closes for *_, closes in rules):
        return
    base = urlsplit(base_url).path.rstrip("/")
    hits = Counter()
    for page in pages:
        path = urlsplit(page.url).path
        if base and path.startswith(base + "/"):
            path = path[len(base):]
        matches = lambda regex: regex.match(path) or regex.match(path.rstrip("/"))
        reopened = {source for regex, source, _, closes in rules
                    if not closes and matches(regex)}
        for regex, source, pattern, closes in rules:
            if closes and source not in reopened and matches(regex):
                if not page.noindex:
                    page.robots = (page.robots + ",noindex").strip(",")
                hits[(source, pattern)] += 1
                break
    for (source, pattern), n in sorted(hits.items()):
        problems.append(tr("{a0} закрывает от индекса {a1} страниц(ы) заголовком "
                           "X-Robots-Tag: noindex — правило {a2}", a0=source, a1=n, a2=pattern))


def _settle_flat_urls(pages: list, root: str, base_url: str) -> None:
    """
    Адрес плоской страницы `filter.html` — в той форме, в какой на неё
    ссылается сам сайт.

    Раньше каждая такая страница без canonical получала `/filter/`, и он же
    уезжал в sitemap. На GitHub Pages, S3 и обычном nginx это 404: pkgdown,
    Pelican, mdBook и Sphinx отдают `filter.html`. Next.js-экспорт кладёт
    `about.html`, а ссылается на `/about` — тогда адрес `/about`. Если ссылок
    нет, берётся `filter.html`: он работает на любом статическом хостинге.
    """
    votes = defaultdict(Counter)
    for page in pages:
        for key, form in page.__dict__.pop("_link_forms", ()):
            votes[key][form] += 1
    order = {"file": 0, "bare": 1, "slash": 2}
    for page in pages:
        name = os.path.basename(page.path or "").lower()
        if (not name.endswith((".html", ".htm")) or name.startswith("index.")
                or page.__dict__.get("_url_declared")):
            continue
        counted = votes.get(page.key)
        form = (min(counted, key=lambda f: (-counted[f], order[f])) if counted else "file")
        if form == "slash":
            continue
        file_url = _file_url(page.path, root, base_url)
        if form == "bare":
            file_url = _EXT_RE.sub("", file_url)
        parts = urlsplit(file_url)
        page.url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


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
    todo = []
    source_repo = any(os.path.exists(os.path.join(root, m)) for m in SOURCE_MARKERS)
    # Исходники для GitHub Pages: `.md` без шапки там собирается в страницу,
    # а README.md становится главной, если своей главной в каталоге нет.
    jekyll = os.path.isfile(os.path.join(root, "_config.yml"))
    def unreadable(exc):
        if not os.path.isdir(root):
            return                  # нет самого каталога — об этом скажут выше
        # Каталог без прав на чтение или со слишком длинным путём раньше
        # пропадал молча: «разобрано страниц: 1» — и ни слова о том, что ещё.
        problems.append(tr("{a0}: каталог не прочитан ({a1}) — страницы в нём не проверялись",
                           a0=getattr(exc, "filename", "") or root,
                           a1=getattr(exc, "strerror", "") or exc))

    for dirpath, dirnames, filenames in os.walk(root, onerror=unreadable):
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
                             if not d.startswith(".") and d not in skip and d not in OWN_DIRS)
        for name in sorted(filenames):
            if name.startswith(".") or name.lower() in OWN_FILES:
                continue
            if not name.lower().endswith(exts):
                continue
            path = os.path.join(dirpath, name)
            # Страница ошибки — не страница сайта: на неё никто не ссылается,
            # она короткая, и в sitemap ей не место. Её выдаёт почти любой
            # генератор, и каждая получала «сироту» и «тонкую».
            if _ERROR_PAGE.search(os.path.relpath(path, root).replace(os.sep, "/")):
                continue
            readme_home = (jekyll and name.lower() == "readme.md"
                           and not any(f.lower().startswith("index.") for f in filenames))
            todo.append((path, root, base_url, readme_home))
    for kind, path, value in _parse_all(todo, jobs):
        if kind == "error":
            problems.append(value)
        elif kind == "fragment":
            fragments.append(path)
        elif kind == "page":
            loaded.append(value)
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
    pages.sort(key=lambda p: p.url)
    return pages, problems


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
