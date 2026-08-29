# -*- coding: utf-8 -*-
"""
Многоязычность и гео: hreflang.

Программатик почти всегда мультиязычен. Один и тот же каталог разворачивают
на десять языков — и получают не десять сайтов, а один, у которого десять
версий каждой страницы. Связывает их только hreflang, и ломается он тихо.

Что важно понимать про эту разметку, потому что от этого зависят проверки:

  * **Кластер взаимный.** Если A ссылается на B, а B на A не ссылается,
    Google отбрасывает связь целиком — не «частично учитывает», а отбрасывает.
    Это самая частая и самая незаметная поломка: половина кластера выглядит
    правильно.
  * **Каждая страница обязана ссылаться на себя.** Без self-ссылки кластер
    невалиден, хотя внешне список альтернатив полный.
  * **`x-default` не обязателен, но нужен**: он говорит, что показывать тому,
    чей язык не совпал ни с одним из объявленных.
  * **hreflang не про дубли.** Он не склеивает страницы и не заменяет canonical.
    Canonical, указывающий на другую языковую версию, убивает кластер.
  * **Код языка — не код страны.** `uk` — это украинский, а не Соединённое
    Королевство (`en-GB`). Ошибка настолько типовая, что проверяется отдельно.

Отдельно про гео. Две версии на одном языке для разных стран — `en-us`
и `en-gb` — законно похожи почти дословно. Обычная проверка дублей называет
такую пару `near-duplicate` и советует canonical, а это ровно тот совет,
который убьёт региональную версию. Поэтому пары внутри одного hreflang-кластера
из проверки дублей исключаются и выносятся отдельной строкой.
"""

from __future__ import annotations

import re
from collections import defaultdict
from html.parser import HTMLParser

from .core import url_key
from .i18n import N_, tr

# ISO 639-1. Список нужен, чтобы отличить язык от страны: без него `en-uk`
# и `zh-cn` выглядят одинаково правдоподобно, а верен только второй.
LANGUAGES = {
    "ab", "aa", "af", "ak", "sq", "am", "ar", "an", "hy", "as", "av", "ae", "ay",
    "az", "bm", "ba", "eu", "be", "bn", "bh", "bi", "bs", "br", "bg", "my", "ca",
    "ch", "ce", "ny", "zh", "cv", "kw", "co", "cr", "hr", "cs", "da", "dv", "nl",
    "dz", "en", "eo", "et", "ee", "fo", "fj", "fi", "fr", "ff", "gl", "ka", "de",
    "el", "gn", "gu", "ht", "ha", "he", "hz", "hi", "ho", "hu", "ia", "id", "ie",
    "ga", "ig", "ik", "io", "is", "it", "iu", "ja", "jv", "kl", "kn", "kr", "ks",
    "kk", "km", "ki", "rw", "ky", "kv", "kg", "ko", "ku", "kj", "la", "lb", "lg",
    "li", "ln", "lo", "lt", "lu", "lv", "gv", "mk", "mg", "ms", "ml", "mt", "mi",
    "mr", "mh", "mn", "na", "nv", "nd", "ne", "ng", "nb", "nn", "no", "ii", "nr",
    "oc", "oj", "cu", "om", "or", "os", "pa", "pi", "fa", "pl", "ps", "pt", "qu",
    "rm", "rn", "ro", "ru", "sa", "sc", "sd", "se", "sm", "sg", "sr", "gd", "sn",
    "si", "sk", "sl", "so", "st", "es", "su", "sw", "ss", "sv", "ta", "te", "tg",
    "th", "ti", "bo", "tk", "tl", "tn", "to", "tr", "ts", "tt", "tw", "ty", "ug",
    "uk", "ur", "uz", "ve", "vi", "vo", "wa", "cy", "wo", "fy", "xh", "yi", "yo",
    "za", "zu",
}

# Коды, которые люди пишут как страну, а они значат совсем другое.
LOOKS_LIKE_A_COUNTRY = {
    "uk": ("en-GB", N_("«uk» — это украинский язык, а не Великобритания")),
    "gb": ("en-GB", N_("«gb» — это страна, а не язык: перед ней нужен язык")),
    "us": ("en-US", N_("«us» — это страна, а не язык: перед ней нужен язык")),
    "eu": ("", N_("«eu» — не язык и не страна по ISO 3166-1")),
    "cn": ("zh-CN", N_("«cn» — это страна, а не язык: перед ней нужен язык")),
    "jp": ("ja", N_("«jp» — это страна, код языка — «ja»")),
    "br": ("pt-BR", N_("«br» — это бретонский язык, а не Бразилия")),
    "in": ("hi", N_("«in» — устаревший код индонезийского, а не Индия")),
    "ua": ("uk", N_("«ua» — это страна, код украинского языка — «uk»")),
}

_TAG_RE = re.compile(r"^([A-Za-z]{2,3})(?:-([A-Za-z]{4}))?(?:-([A-Za-z]{2}|\d{3}))?$")


class _Links(HTMLParser):
    """Собирает `<link rel="alternate" hreflang=… href=…>` и canonical."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.alternates = []      # (код как написан, href)
        self.canonical = ""

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        data = {k.lower(): (v or "") for k, v in attrs}
        rel = data.get("rel", "").lower().split()
        if "canonical" in rel and data.get("href"):
            self.canonical = data["href"].strip()
        # Атрибуты в HTML нечувствительны к регистру, и половина фреймворков
        # пишет `hrefLang`. Парсер уже привёл ключи к нижнему регистру.
        if "alternate" in rel and data.get("hreflang"):
            self.alternates.append((data["hreflang"].strip(), data.get("href", "").strip()))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def read_alternates(page) -> list:
    """Список (код, href) со страницы. Пустой — значит разметки нет."""
    raw = page.raw or ""
    if "alternate" not in raw.lower():
        return []
    parser = _Links()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:                       # noqa: BLE001 — битый HTML не повод падать
        pass
    return parser.alternates


def check_tag(code: str) -> str:
    """
    Что не так с кодом. Пустая строка — всё в порядке.

    Проверяется форма и то, что первая часть — действительно язык. Регион
    по ISO 3166-1 не сверяется со списком: он меняется, а ошибки в нём редки
    по сравнению с классической подменой языка страной.
    """
    value = (code or "").strip()
    if not value:
        return tr("пустой код")
    if value.lower() == "x-default":
        return ""
    match = _TAG_RE.match(value)
    if not match:
        return tr("«{a0}» не похож на код языка: ожидается вид `en`, `pt-BR`, "
                  "`zh-Hant-TW` или `x-default`", a0=value)
    language = match.group(1).lower()
    if language in LOOKS_LIKE_A_COUNTRY and language not in ("uk", "br", "in"):
        instead, why = LOOKS_LIKE_A_COUNTRY[language]
        return tr(why) + (tr(" — вероятно, имелось в виду `{a0}`", a0=instead)
                          if instead else "")
    if language not in LANGUAGES:
        return tr("«{a0}» не является кодом языка по ISO 639-1", a0=language)
    return ""


def _same_language(a: str, b: str) -> bool:
    return (a or "").split("-")[0].lower() == (b or "").split("-")[0].lower() and a and b


def clusters(pages: list) -> dict:
    """
    Кто с кем связан hreflang. Ключ — url_key страницы, значение — множество
    ключей, на которые она ссылается (включая себя, если ссылается).
    """
    out = {}
    for page in pages:
        out[page.key] = {url_key(href) for _code, href in read_alternates(page) if href}
    return out


def is_multilingual(pages: list) -> bool:
    """
    Мультиязычен ли сайт. Проверять hreflang на одноязычном бессмысленно,
    а ругаться на его отсутствие — вредно: это была бы находка на каждой
    странице каждого обычного сайта.
    """
    langs = {(p.lang or "").split("-")[0].lower() for p in pages if p.lang}
    if len(langs) >= 2:
        return True
    return sum(1 for p in pages if read_alternates(p)) >= max(2, len(pages) // 20)


def check(pages: list, cfg: dict = None) -> dict:
    """Все проверки hreflang разом. Возвращает находки, заметки и пары-регионы."""
    issues, notes = [], []
    regional_pairs = []
    if len(pages) < 2 or not is_multilingual(pages):
        return {"issues": issues, "notes": notes, "regional_pairs": regional_pairs,
                "checked": False}

    from .publish import indexable

    known = {p.key: p for p in pages}
    declared = {}
    targets = {}
    x_default = set()
    empty = []

    for page in pages:
        alternates = read_alternates(page)
        declared[page.key] = alternates
        if not alternates:
            empty.append(page)
            continue
        keys = set()
        for code, href in alternates:
            problem = check_tag(code)
            if problem:
                issues.append(("warning", page.url, "hreflang-bad-code", problem))
            if not href:
                issues.append(("warning", page.url, "hreflang-bad-code",
                               tr("у альтернативы «{a0}» пустой href", a0=code)))
                continue
            if code.strip().lower() == "x-default":
                x_default.add(page.key)
            keys.add(url_key(href))
        targets[page.key] = keys

    # Шаблон, печатающий один и тот же кластер на всех страницах, — это одна
    # беда, а не тысяча. На живом каталоге недвижимости все 1 099 страниц
    # объявляли одинаковый набор альтернатив, ведущий на главную: пакет выдавал
    # 5 498 находок вместо одной строки о шаблоне.
    static_cluster = set()
    if len(targets) >= 20:
        shapes = defaultdict(list)
        for key, keys in targets.items():
            shapes[frozenset(keys)].append(key)
        biggest, members = max(shapes.items(), key=lambda kv: len(kv[1]))
        # Главная законно есть в собственном кластере — требовать «ни одна
        # не ссылается на себя» нельзя, иначе проверка не сработает ровно там,
        # где нужна. Смотрим долю.
        orphaned = [m for m in members if m not in biggest]
        if (len(members) / len(targets) >= 0.9
                and len(orphaned) / len(members) >= 0.9):
            static_cluster = set(orphaned)
            sample = sorted(biggest)[:3]
            issues.append(("critical", "", "hreflang-static-cluster",
                           tr("{a0} страниц из {a1} объявляют один и тот же набор "
                              "альтернатив ({a2}) и ни одна не ссылается на себя. "
                              "Шаблон печатает кластер главной на каждой странице — "
                              "для поисковика связей между версиями нет вообще. "
                              "Чинится один раз, в шаблоне.",
                              a0=len(members), a1=len(targets),
                              a2=", ".join(sample))))

    for page in pages:
        keys = targets.get(page.key)
        if keys is None:
            continue
        if page.key in static_cluster:
            continue

        if page.key not in keys:
            issues.append(("critical", page.url, "hreflang-no-self",
                           tr("в кластере нет ссылки на саму эту страницу — "
                              "без self-ссылки Google считает кластер невалидным "
                              "целиком")))

        for other in sorted(keys):
            if other == page.key:
                continue
            target = known.get(other)
            if target is None:
                issues.append(("info", page.url, "hreflang-unknown-target",
                               tr("альтернатива {a0} не найдена среди разобранных "
                                  "страниц — проверить взаимность нельзя",
                                  a0=other)))
                continue
            back = targets.get(target.key)
            if back is not None and page.key not in back:
                issues.append(("critical", page.url, "hreflang-no-return",
                               tr("страница ссылается на {a0}, а та не ссылается "
                                  "обратно. Односторонняя связь не «учитывается "
                                  "частично» — она отбрасывается вся",
                                  a0=target.url)))
            if not indexable(target):
                issues.append(("warning", page.url, "hreflang-target-blocked",
                               tr("альтернатива {a0} закрыта от индексации или "
                                  "отдаёт canonical другой странице — кластер "
                                  "указывает на то, чего в индексе не будет",
                                  a0=target.url)))

        # canonical, уводящий на другой язык, обнуляет весь кластер.
        if page.canonical:
            canonical_key = url_key(page.canonical)
            other = known.get(canonical_key)
            if (canonical_key != page.key and other is not None
                    and (other.lang or "") and (page.lang or "")
                    and not _same_language(other.lang, page.lang)):
                issues.append(("critical", page.url, "hreflang-canonical-conflict",
                               tr("canonical ведёт на версию другого языка ({a0}) — "
                                  "это отменяет hreflang: поисковик склеит версии "
                                  "вместо того, чтобы показывать нужную",
                                  a0=other.url)))

        # Объявленный для себя код должен совпадать с языком страницы.
        own = [code for code, href in declared.get(page.key, ())
               if url_key(href) == page.key and code.lower() != "x-default"]
        if own and page.lang and not _same_language(own[0], page.lang):
            issues.append(("warning", page.url, "hreflang-lang-mismatch",
                           tr("self-ссылка объявлена как «{a0}», а страница "
                              "объявляет lang=«{a1}»", a0=own[0], a2=None, a1=page.lang)))

    if empty and len(empty) != len(pages):
        for page in empty:
            issues.append(("warning", page.url, "hreflang-missing",
                           tr("на сайте есть версии на разных языках, а у этой "
                              "страницы нет ни одной альтернативы — поисковик "
                              "не узнает, что версии связаны")))

    if targets and not x_default:
        notes.append(tr("ни одна страница не объявляет `x-default`. Он не "
                        "обязателен, но именно он говорит, что показать тому, "
                        "чей язык не совпал ни с одним объявленным."))

    # Региональные пары: один язык, разные регионы — законно похожи.
    for page in pages:
        for other_key in sorted(targets.get(page.key, ())):
            other = known.get(other_key)
            if other is None or other.key <= page.key:
                continue
            if _same_language(page.lang, other.lang) and page.lang != other.lang:
                regional_pairs.append((page.url, other.url))

    if regional_pairs:
        notes.append(tr("региональных пар (один язык, разные страны): {a0}. "
                        "Они законно похожи почти дословно — это работа "
                        "hreflang, а не повод ставить canonical.",
                        a0=len(regional_pairs)))

    langs = sorted({(p.lang or "?").split("-")[0].lower() for p in pages if p.lang})
    if langs:
        notes.append(tr("языков на сайте: {a0} ({a1}). Объём текста и длины "
                        "title и description считаются по письменности каждой "
                        "страницы, а не по языку сайта.",
                        a0=len(langs), a1=", ".join(langs)))

    return {"issues": issues, "notes": notes, "regional_pairs": regional_pairs,
            "checked": True}
