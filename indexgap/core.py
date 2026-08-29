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

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import (urljoin, urlparse, urldefrag, urlsplit, urlunsplit,
                          quote, unquote)

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
OWN_FILES = {"indexgap-report.html", "indexgap-report.json", "indexgap-check.html",
             "indexgap-check.json", "indexgap-doctor.html", "indexgap-doctor.json"}

# Каталоги сборки пропускаются: иначе `indexgap check .` в обычном репозитории
# статического генератора разбирает и исходники, и собранный сайт, и каждая
# страница оказывается собственным почти-дублем.
SKIP_DIRS = {"node_modules", ".git", ".svn", "__pycache__", ".next", ".nuxt",
             "vendor", ".venv", "venv", "public", "_site", "dist", "build",
             "out", ".output", "target", ".vercel", ".astro", "coverage"}

DEFAULT_EXTS = (".html", ".htm", ".md", ".markdown")


class SourceError(Exception):
    """Файл невозможно прочитать. Сообщение адресовано человеку, не разработчику."""


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

    @property
    def key(self) -> str:
        """Ключ для сравнения с любой ссылкой на эту страницу."""
        return url_key(self.url)

    @property
    def words(self) -> list:
        return re.findall(r"\w+", self.text.lower(), flags=re.UNICODE)

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
            " ".join(self.words),
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ── URL ───────────────────────────────────────────────────────────────────────

_EXT_RE = re.compile(r"\.(html?|md|markdown)$", re.I)
_INDEX_RE = re.compile(r"(^|/)index\.(html?|md|markdown)$", re.I)


def url_key(url: str) -> str:
    """
    Приводит адрес к форме, в которой ссылка и страница сравнимы.

    `/about.html`, `/about/`, `/about`, `/about/index.html` и `/%D0%BE`
    в процент-кодировании — это один и тот же адрес. Сравнение по сырой
    строке даёт «сироту» на каждой странице обычного статического сайта.
    """
    if not url:
        return ""
    parts = urlsplit(url)
    path = unquote(parts.path or "/")
    # `{{base}}/{{slug}}` в шаблоне даёт `/guides//visa/`. Сервер такую страницу
    # отдаёт, а сравнение по сырой строке объявляло её сиротой.
    path = re.sub(r"/{2,}", "/", path)
    path = _INDEX_RE.sub(r"\1", path)
    path = _EXT_RE.sub("", path)
    if len(path) > 1:
        path = path.rstrip("/")
    if not path:
        path = "/"
    host = (parts.netloc or "").lower()
    # Порт по умолчанию — это тот же адрес: `example.com:443` и `example.com`
    # различались, и страница молча выпадала из sitemap по «чужому» canonical.
    for scheme, port in (("https", ":443"), ("http", ":80")):
        if host.endswith(port) and (not parts.scheme or parts.scheme == scheme):
            host = host[: -len(port)]
    if host.startswith("www."):
        host = host[4:]
    query = parts.query
    return urlunsplit(("", host, path, query, ""))


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
    rel = _INDEX_RE.sub(r"\1", rel)
    rel = _EXT_RE.sub("", rel)
    if rel in (".", ""):
        rel = ""
    # Пробелы и кириллица в имени файла обязаны уехать в URL закодированными,
    # иначе sitemap невалиден, а ссылка на страницу с ней не сойдётся.
    rel = "/".join(quote(seg, safe="~-._") for seg in rel.split("/"))
    url = urljoin(base_url.rstrip("/") + "/", rel)
    return normalize_url(url, directory=True)


def check_site_url(site: str) -> str:
    """
    Адрес сайта нужен целиком, со схемой. `example.com` молча даёт URL вида
    `example.com/page/`, невалидный sitemap и сломанный подсчёт внутренних ссылок.
    """
    site = (site or "").strip()
    if not site:
        raise SourceError("Не указан адрес сайта. Добавь --site https://example.com")
    parts = urlsplit(site)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        guess = site.split("//")[-1].strip("/")
        raise SourceError(
            f"--site {site} — так не годится: нужен полный адрес со схемой.\n"
            f"    Попробуй: --site https://{guess}")
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
        raise SourceError(f"{path}: файл не читается ({exc.strerror or exc}).")

    for bom, encoding in BOMS:
        if data.startswith(bom):
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError:
                break

    # <meta charset> важнее угадывания — но именно из мета-тега.
    # Раньше слово `charset=` бралось откуда угодно, включая адрес скрипта
    # `/x.js?charset=koi8-r`, и валидный UTF-8 читался как кракозябры.
    declared = re.search(
        rb"""<meta[^>]{0,200}?charset\s*=\s*["']?\s*([\w.:-]+)""", data[:4096], re.I)
    order = list(FALLBACK_ENCODINGS)
    if declared:
        name = declared.group(1).decode("ascii", "ignore").lower()
        if name:
            order = [name] + [e for e in order if e != name]

    for encoding in order:
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        return text, _canonical_encoding(encoding)
    raise SourceError(
        f"{path}: не удалось определить кодировку. Пересохрани файл в UTF-8.")


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
        self.anchors = []
        self.jsonld = []
        self.blocks = {"li": 0, "table": 0, "img": 0, "img_no_alt": 0,
                       "script": 0, "p": 0}
        self.meta = {}             # author, datePublished и прочее из <meta>
        self._chunks = []          # (текст, приклеивать ли к предыдущему)
        self._main_chunks = []
        self._paragraphs = []
        self._para_buf = []
        self._skip_depth = 0
        self._in_title = False
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
            self._para_buf.append((text, self._in_main))
        self._glue = True

    def _flush_paragraph(self):
        buf, self._para_buf = self._para_buf, []
        text = re.sub(r"\s+", " ", " ".join(t for t, _ in buf)).strip()
        if text:
            self._paragraphs.append((text, any(m for _, m in buf)))

    # -- разбор ---------------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script" and "ld+json" in a.get("type", "").lower():
            self._in_ld = True
            self._ld_buf = ""
            self._skip_depth += 1
            return
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            if tag == "script":
                self.blocks["script"] += 1
            return
        # Внутри пропускаемого блока не существует ни ссылок, ни мета-тегов:
        # ссылка в <template> не ведёт никуда, пока её не отрендерит скрипт.
        if self._skip_depth:
            return

        if tag not in INLINE_TAGS:
            self._glue = False

        self._depth += 1
        if tag not in VOID_TAGS and (tag in MAIN_TAGS
                                     or a.get("role", "").lower() == "main"):
            self._main_stack.append((tag, self._depth))
            self._saw_main = True

        # Счётчики структуры считаются по основному блоку: список в меню
        # не делает страницу структурированной.
        if self._in_main or not self._saw_main:
            if tag == "li":
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
        elif tag == "base" and a.get("href"):
            self.base = a["href"].strip()
        elif tag == "title":
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
        elif tag == "link" and "canonical" in a.get("rel", "").lower():
            self.canonical = a.get("href", "").strip()
        elif tag in ("h1", "h2", "h3", "h4"):
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
        self.handle_starttag(tag, attrs)
        if tag in SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag not in SKIP_TAGS:
            self._depth = max(0, self._depth - 1)
            if self._main_stack and self._main_stack[-1][1] > self._depth:
                self._main_stack.pop()

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self._in_ld = False
            if self._ld_buf.strip():
                self.jsonld.append(self._ld_buf.strip())
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        # Закрытие любого тега снимает основной блок, открытый на этой глубине —
        # неважно, какой тег его открыл: <main>, <article> или <div role="main">.
        self._depth = max(0, self._depth - 1)
        while self._main_stack and self._main_stack[-1][1] > self._depth:
            self._main_stack.pop()
        if tag not in INLINE_TAGS:
            self._glue = False
        if tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2", "h3", "h4") and self._in_heading:
            text = _clean(self._heading_buf)
            if text:
                self.headings.append((self._in_heading, text))
            self._in_heading = 0
            # Заголовок не абзац: раньше он становился отдельным «абзацем»
            # и занимал место прямого ответа.
            self._para_buf = []
        elif tag == "a" and self._in_anchor:
            self.anchors.append(_clean(self._anchor_buf))
            self._in_anchor = False
        elif tag in ("p", "div", "section", "li"):
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
        if self._saw_main:
            inside = [text for text, in_main in self._paragraphs if in_main]
            if inside:
                return inside
        return [text for text, _ in self._paragraphs]


def _clean(text: str) -> str:
    """Нормализация пробелов вместе с неразрывными: NBSP — тоже пробел."""
    return re.sub(r"[\s\u00a0\u2007\u202f\u2009]+", " ", text or "").strip()


# ── Markdown ──────────────────────────────────────────────────────────────────

FRONTMATTER = re.compile(r"^\ufeff?\s*-{3,}[ \t]*\r?\n(.*?)\r?\n-{3,}[ \t]*(?:\r?\n|$)", re.S)
FRONTMATTER_OPEN = re.compile(r"^\ufeff?\s*-{3,}[ \t]*\r?\n")
MD_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)")
MD_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.M)
MD_FENCE = re.compile(r"^([ \t]*)(```|~~~).*?^\1?\2[ \t]*$", re.S | re.M)


def _strip_fences(md: str) -> str:
    """Заголовок внутри блока кода — это комментарий, а не заголовок страницы."""
    return MD_FENCE.sub("\n", md)


def _strip_markdown(md: str) -> str:
    md = _strip_fences(md)
    md = re.sub(r"`[^`]*`", " ", md)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md)
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"<!--.*?-->", " ", md, flags=re.S)
    md = re.sub(r"<[^>]+>", " ", md)          # сырой HTML внутри markdown
    md = re.sub(r"^[#>\-\*\+\s]+", " ", md, flags=re.M)
    md = re.sub(r"[*_~]", "", md)
    return _clean(md)


def _md_paragraphs(md: str) -> list:
    body = _strip_fences(md)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    out = []
    for block in re.split(r"\n[ \t]*\n", body):
        block = block.strip()
        if not block or block.startswith("#"):
            continue
        out.append(_strip_markdown(block))
    return [p for p in out if p]


def _unquote_value(value: str) -> str:
    value = value.strip()
    for ch in ('"', "'"):
        if len(value) >= 2 and value.startswith(ch) and value.endswith(ch):
            return value[1:-1]
    return value


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
        value = _clean(_unquote_value(value))
        if value:
            out[key] = value
    return out


# ── страница ──────────────────────────────────────────────────────────────────

def load_page(path: str, root: str, base_url: str) -> Page:
    raw, encoding = read_text(path)
    notes = []
    if not is_utf8(encoding):
        notes.append(f"файл прочитан как {encoding}, а не UTF-8")

    url = path_to_url(path, root, base_url)
    host = urlparse(base_url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    if path.lower().endswith((".md", ".markdown")):
        meta, body = {}, raw
        m = FRONTMATTER.match(raw)
        if m:
            meta = _parse_frontmatter(m.group(1))
            body = raw[m.end():]
        elif FRONTMATTER_OPEN.match(raw):
            notes.append("фронтматтер открыт, но не закрыт: строка `---` в конце блока")
        elif raw.lstrip()[:3] == "---":
            notes.append("фронтматтер не распознан")
        matches = MD_LINK.findall(_strip_fences(body))
        hrefs = [href for _, href in matches]
        md_anchors = [text.strip() for text, _ in matches]
        md_headings = [(len(h), _clean(t)) for h, t in MD_HEADING.findall(_strip_fences(body))]
        base_href = ""
        text = _strip_markdown(body)
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
            blocks={"li": len(re.findall(r"^\s*[-*+]\s+", body, re.M)),
                    "table": len(re.findall(r"^\s*\|.+\|\s*$", body, re.M)) and 1 or 0,
                    "img": len(re.findall(r"!\[[^\]]*\]\(", body)),
                    "img_no_alt": len(re.findall(r"!\[\s*\]\(", body)),
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
            anchors=ex.anchors,
            raw=raw,
            encoding=encoding,
            notes=notes,
            jsonld=ex.jsonld,
            paragraphs=ex.paragraphs,
            blocks=ex.blocks,
        )

    # Canonical приводится к абсолютному виду тем же базовым адресом, что
    # и ссылки. Относительный `<base href>` раньше оставлял canonical
    # относительным, и самоссылающийся canonical объявлялся «чужим».
    base_for_links = urljoin(url, base_href) if base_href else url
    if page.canonical:
        page.canonical = urljoin(base_for_links, page.canonical)
    seen = set()
    for href in hrefs:
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            continue
        absolute, _ = urldefrag(urljoin(base_for_links, href))
        netloc = urlparse(absolute).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if netloc != host:
            continue
        absolute = normalize_url(absolute)
        key = url_key(absolute)
        if key != page.key and key not in seen:
            seen.add(key)
            page.links.append(absolute)

    return page


def load_pages(root: str, base_url: str, exts=DEFAULT_EXTS) -> tuple:
    """
    Возвращает (страницы, проблемы). Проблемы — это файлы, которые не прочитались,
    и страницы с совпавшими URL. Раньше первый же битый симлинк ронял весь прогон,
    а два файла с одинаковым URL молча давали дубль в sitemap.
    """
    pages, problems, by_key = [], [], {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in SKIP_DIRS]
        for name in sorted(filenames):
            if name.startswith(".") or name.lower() in OWN_FILES:
                continue
            if not name.lower().endswith(exts):
                continue
            path = os.path.join(dirpath, name)
            try:
                page = load_page(path, root, base_url)
            except SourceError as exc:
                problems.append(str(exc))
                continue
            other = by_key.get(page.key)
            if other is not None:
                # Из двух файлов с одним адресом берём содержательный, а не тот,
                # что раньше встретился в обходе: заглушка `about.html` рядом
                # с настоящей `about/index.html` уносила её исходящие ссылки,
                # и целевые страницы становились ложными сиротами.
                keep, drop = ((page, other)
                              if (len(page.links), len(page.text)) >
                                 (len(other.links), len(other.text))
                              else (other, page))
                problems.append(
                    f"{os.path.relpath(drop.path, root)} и "
                    f"{os.path.relpath(keep.path, root)} дают один URL "
                    f"{keep.url} — взят "
                    f"{os.path.relpath(keep.path, root)}, второй пропущен")
                if keep is page:
                    pages[pages.index(other)] = page
                    by_key[page.key] = page
                continue
            by_key[page.key] = page
            pages.append(page)
    pages.sort(key=lambda p: p.url)
    return pages, problems


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
    tmp = os.path.join(directory, f".{os.path.basename(path)}.tmp")
    # `_broken` — служебный флаг чтения, наружу он не пишется. Остальные
    # служебные ключи (например список созданных шардов) сохраняются:
    # без них пакет не знает, какие файлы он вправе убирать за собой.
    payload = {k: v for k, v in data.items() if k != "_broken"}
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
