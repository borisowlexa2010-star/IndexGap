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
from urllib.parse import urljoin, urlsplit
from collections import Counter, defaultdict
from html.parser import HTMLParser

from .core import HEAD_TAGS, url_key
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
    "cn": ("zh-CN", N_("«cn» — это страна, а не язык: перед ней нужен язык")),
    "jp": ("ja", N_("«jp» — это страна, код языка — «ja»")),
    "br": ("pt-BR", N_("«br» — это бретонский язык, а не Бразилия")),
    "in": ("hi", N_("«in» — устаревший код индонезийского, а не Индия")),
    "ua": ("uk", N_("«ua» — это страна, код украинского языка — «uk»")),
}

# То, что пишут вместо страны. Великобритания — GB; UK в ISO 3166-1 нет.
NOT_A_REGION = {"UK": "GB", "EN": "", "EU": "", "LATAM": "419"}

_TAG_RE = re.compile(r"^([A-Za-z]{2,3})(?:-([A-Za-z]{4}))?(?:-([A-Za-z]{2}|\d{3}))?$")


class _Links(HTMLParser):
    """Собирает `<link rel="alternate" hreflang=… href=…>` и canonical."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.alternates = []      # (код как написан, href)
        self.canonical = ""
        self.in_body = 0
        self._body = False
        self._raw = 0             # внутри <noscript>/<template>: это не разметка head

    def handle_starttag(self, tag, attrs):
        if tag in ("noscript", "template"):
            self._raw += 1
        if self._raw:
            return
        if tag == "body" or tag not in HEAD_TAGS:
            self._body = True
        if tag != "link":
            return
        data = {k.lower(): (v or "") for k, v in attrs}
        rel = data.get("rel", "").lower().split()
        if "canonical" in rel and data.get("href"):
            self.canonical = data["href"].strip()
        # Атрибуты в HTML нечувствительны к регистру, и половина фреймворков
        # пишет `hrefLang`. Парсер уже привёл ключи к нижнему регистру.
        if "alternate" in rel and data.get("hreflang"):
            if self._body:
                self.in_body += 1
            else:
                self.alternates.append((data["hreflang"].strip(), data.get("href", "").strip()))

    def handle_startendtag(self, tag, attrs):
        if tag in ("noscript", "template"):
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ("noscript", "template") and self._raw:
            self._raw -= 1


def read_alternates(page) -> list:
    """Список (код, href) со страницы. Пустой — значит разметки нет."""
    ready = getattr(page, "alternates", None)
    if ready is not None:
        return ready
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
    region = (match.group(3) or "").upper()
    if region in NOT_A_REGION:
        return tr("«{a0}» — не код страны по ISO 3166-1", a0=region) + (
            tr(" — вероятно, имелось в виду `{a0}`", a0=f"{language}-{NOT_A_REGION[region]}")
            if NOT_A_REGION[region] else "")
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
    # Любая объявленная разметка стоит проверки, сколько бы страниц её ни несло:
    # порог в 5% пропускал сломанный кластер на четырёх страницах из ста.
    if sum(1 for p in pages if read_alternates(p)) >= 2:
        return True
    # Худший случай: версии на трёх языках, `lang="en"` зашит в шаблон, а
    # hreflang нет вовсе. По атрибутам сайт одноязычный — выдаёт его только
    # адрес: один и тот же путь под разными языковыми префиксами.
    from .checks import _locale_split
    seen = {}
    for p in pages:
        host, lang, rest = _locale_split(p.url)
        if lang:
            seen.setdefault((host, rest), set()).add(lang)
    return sum(1 for langs_here in seen.values() if len(langs_here) >= 2) >= 2


def _canonical_to_a_sibling(page, keys) -> bool:
    """
    Закрыта ли страница тем, что canonical отдан версии на другом языке.

    Это и есть конфликт, который губит кластер: поисковик выбрасывает перевод.
    Печатная копия с canonical на основную страницу того же языка — не конфликт,
    а вариант, и её hreflang поисковик просто не читает.
    """
    if page.noindex or not page.canonical:
        return False
    target = url_key(page.canonical)
    if target not in keys:
        return False
    own = (page.lang or "").lower().split("-")[0]
    for code, href in read_alternates(page):
        if href and url_key(href) == target:
            lang = code.lower().split("-")[0]
            return lang not in (own, "x")
    return False


def _origin(parts):
    """
    (схема, хост) адреса в той форме, в которой два написания одного адреса
    совпадают: `demo.example:443` — это `demo.example`, а `xn--e1afmkfd.xn--p1ai`
    — это `пример.рф`. Без этого точная ответная ссылка с явным портом или в
    punycode объявлялась «другим адресом». `www.` не снимается: это другой хост
    и настоящий редирект.
    """
    if not parts or not parts.scheme or not parts.netloc:
        return None
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    default = {"https": ":443", "http": ":80"}.get(scheme)
    if default and host.endswith(default):
        host = host[: -len(default)]
    if not host.isascii():
        try:
            base, colon, rest = host.partition(":")
            host = base.encode("idna").decode("ascii") + colon + rest
        except UnicodeError:
            pass
    return scheme, host


_NO_PARTS = urlsplit("")


def split_href(href):
    try:
        return urlsplit(href)
    except ValueError:              # `http://[x` — битый адрес, не повод падать
        return None


def _latin_not_cyrillic(text: str) -> bool:
    """Текст написан латиницей и в нём нет ни одной кириллической буквы."""
    latin = sum(1 for ch in text or "" if "a" <= ch.lower() <= "z")
    return latin >= 40 and not re.search("[\u0400-\u04ff]", text or "")


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
    default_only = {}
    empty = []
    self_only = []

    for page in pages:
        alternates = read_alternates(page)
        # Относительный href поисковик не принимает: ему нужен полный адрес.
        # Он называется своей находкой, а связи проверяются по адресу, до
        # которого его достроит браузер, — иначе «нет self-ссылки» у
        # страницы, которая на себя ссылается.
        relative = [href for href in dict.fromkeys(h for _, h in alternates) if href and not (
            (split_href(href) or _NO_PARTS).scheme and (split_href(href) or _NO_PARTS).netloc)]
        if relative:
            issues.append(("warning", page.url, "hreflang-relative", tr(
                "адреса в hreflang записаны не полностью ({a0}) — поисковики "
                "требуют полный адрес со схемой и хостом, например {a1}",
                a0=", ".join(relative[:3]), a1=urljoin(page.url, relative[0]))))
            alternates = [(code, urljoin(page.url, href) if href in relative else href)
                          for code, href in alternates]
        declared[page.key] = alternates
        hidden = getattr(page, "alternates_in_body", 0) or 0
        if hidden:
            issues.append(("warning", page.url, "hreflang-in-body", tr(
                "{a0} ссылок hreflang стоят в <body> — поисковики читают их только "
                "из <head>, и связи между версиями для них нет. Перенеси разметку в "
                "<head>", a0=hidden)))
        if not alternates:
            # Закрытой странице hreflang не нужен — пакет сам советует снять его
            # с запаркованных переводов. живой каталог так и сделал, а 1.9.0
            # ответил 1 418 предупреждениями «нет hreflang». Заглушке-редиректу
            # он не нужен тем более: это не страница.
            from .checks import redirect_target
            # Разметка в <body> уже названа своей находкой: «не объявляет
            # ни одной альтернативы» было бы неправдой.
            if indexable(page) and not redirect_target(page) and not hidden:
                empty.append(page)
            continue
        keys, default_keys, lang_keys = set(), set(), set()
        by_code = defaultdict(dict)
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
                default_keys.add(url_key(href))
            else:
                lang_keys.add(url_key(href))
            keys.add(url_key(href))
            by_code[code.strip().lower()].setdefault(url_key(href), href)
        targets[page.key] = keys
        default_only[page.key] = default_keys - lang_keys
        # Один код — одна версия. Два адреса под «en» или два x-default
        # противоречат друг другу, и поисковик не знает, какой верить.
        for code, hrefs in sorted(by_code.items()):
            if len(hrefs) > 1:
                issues.append(("warning", page.url, "hreflang-conflict", tr(
                    "код «{a0}» объявлен для нескольких адресов ({a1}) — у одного "
                    "кода может быть только одна версия, и противоречивую разметку "
                    "поисковик отбрасывает", a0=code, a1=", ".join(list(hrefs.values())[:3]))))
        # Шаблон, печатающий только текущую версию: разметка есть, а связей
        # между переводами нет — то же, что её отсутствие.
        if lang_keys == {page.key} and indexable(page):
            self_only.append(page)

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

    # Адрес, которым сайт называет свои версии: http:// или другой хост в
    # одной ответной ссылке — уже не та страница, а её редирект. Сравнивается
    # с тем, как пишет сам сайт, а не с --site: неверный --site не должен
    # превращать каждую ссылку в находку.
    split = split_href

    origins = Counter()
    for alternates in declared.values():
        for _, href in alternates:
            origin = _origin(split(href))
            if origin:
                origins[origin] += 1
    home = origins.most_common(1)[0][0] if origins else None

    # Шаблон, который пишет http:// (или чужой хост) во всех альтернативах,
    # сам становится «адресом сайта», и сравнивать не с чем: худший случай
    # был невидим. Сверяемся с тем, как страницы называют себя в canonical, —
    # только с canonical, записанным полным адресом: относительный достроен
    # от --site и о сайте ничего не говорит.
    own = Counter()
    for page in pages:
        if (declared.get(page.key) and page.canonical
                and page.__dict__.get("_canonical_absolute")
                and url_key(page.canonical) == page.key):
            origin = _origin(split(page.canonical))
            if origin:
                own[origin] += 1
    # Сравниваются только альтернативы, которые называют страницы этого же
    # сайта: ссылки на соседние домены (`demo.de` с `demo.example`) — не
    # другое написание своего адреса, а другие сайты.
    named = Counter()
    for alternates in declared.values():
        for _, href in alternates:
            origin = _origin(split(href))
            if origin and url_key(href) in known:
                named[origin] += 1
    if named and own:
        stated, count = own.most_common(1)[0]
        wrong = Counter({o: c for o, c in named.items() if o != stated})
        if (wrong and count >= 2
                and count / sum(own.values()) >= 0.9
                and sum(wrong.values()) / sum(named.values()) >= 0.5):
            home = wrong.most_common(1)[0][0]
            issues.append(("critical", "", "hreflang-no-return", tr(
                "ссылки hreflang ведут на {a0}, а сами страницы в canonical "
                "называют себя адресами {a1} ({a2} из {a3}). Каждая альтернатива — "
                "редирект, а не версия, и поисковик отбрасывает кластер. Чинится "
                "один раз, в шаблоне hreflang",
                a0="%s://%s" % home, a1="%s://%s" % stated,
                a2=count, a3=sum(own.values()))))
            # Об отдельных ответных ссылках говорить уже нечего: неверен шаблон.
            home = None

    def exact_return(target, page_key):
        """href, которым target называет страницу, если он отличается от адреса сайта."""
        if home is None:
            return ""
        for _, href in declared.get(target.key) or ():
            if url_key(href) != page_key:
                continue
            origin = _origin(split(href))
            if origin and origin != home:
                return href
        return ""

    from .publish import indexable
    from .checks import redirect_target
    for page in pages:
        keys = targets.get(page.key)
        if keys is None:
            continue
        if page.key in static_cluster:
            continue
        # hreflang закрытой или неканонической страницы поисковик не читает:
        # печатные копии Hugo и старые версии документации Docusaurus давали
        # тысячи «нет обратной ссылки» там, где связей и не должно быть.
        if not indexable(page) and not _canonical_to_a_sibling(page, keys):
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
            # Цель без единой альтернативы — самая частая односторонняя связь,
            # и как раз она раньше пропускалась: проверка шла, только если у
            # цели был хоть какой-то hreflang. Закрытая цель сообщается ниже,
            # своей находкой, и дважды о ней не говорится.
            if back is None and indexable(target):
                back = set()
            if back is not None and page.key not in back:
                issues.append(("critical", page.url, "hreflang-no-return",
                               tr("страница ссылается на {a0}, а та не ссылается "
                                  "обратно. Односторонняя связь не «учитывается "
                                  "частично» — она отбрасывается вся",
                                  a0=target.url)))
            elif back:
                variant = exact_return(target, page.key)
                if variant:
                    issues.append(("critical", page.url, "hreflang-no-return", tr(
                        "{a0} ссылается обратно на {a1} — это другой адрес (схема или "
                        "хост не те, что у остальных ссылок сайта). Поисковик требует "
                        "точный адрес версии, а не его редирект",
                        a0=target.url, a1=variant)))
            # x-default на заглушку, которая разводит посетителей по языкам
            # (корень Hugo и Astro с языком в подкаталоге), — ровно то, что
            # Google советует для x-default: страница выбора или редиректор.
            if (not indexable(target) and other in default_only.get(page.key, ())
                    and redirect_target(target)):
                continue
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
        # «uk» — украинский, а не Великобритания. Сам код верен, поэтому
        # check_tag его пропускает; выдаёт подмену текст латиницей рядом
        # с английской версией в том же кластере.
        siblings = [code for code, href in declared.get(page.key, ())
                    if url_key(href) != page.key and code.lower().split("-")[0] == "en"]
        if (own and own[0].lower().split("-")[0] == "uk" and siblings
                and _latin_not_cyrillic(page.text)):
            issues.append(("warning", page.url, "hreflang-lang-mismatch", tr(
                "{a0}: текст страницы не украинский, а рядом в кластере — английская "
                "версия. Для Великобритании нужен код `en-GB`",
                a0=tr(LOOKS_LIKE_A_COUNTRY["uk"][1]))))

        # Члены кластера должны соглашаться, на каком языке каждая версия:
        # страница, которая называет себя «en», а соседями названа «fr»,
        # ломает кластер для всех.
        for code, href in declared.get(page.key, ()):
            other = known.get(url_key(href)) if href else None
            if other is None or other.key == page.key or code.lower() == "x-default":
                continue
            theirs = [c for c, h in declared.get(other.key, ())
                      if h and url_key(h) == other.key and c.lower() != "x-default"]
            if theirs and not _same_language(code, theirs[0]):
                issues.append(("warning", page.url, "hreflang-conflict", tr(
                    "альтернатива {a0} объявлена здесь как «{a1}», а сама она "
                    "называет себя «{a2}» — версии кластера расходятся в том, на "
                    "каком она языке", a0=other.url, a1=code, a2=theirs[0])))

    # hreflang связывает переводы одной страницы. Требовать его у страницы,
    # у которой перевода нет, — шум: на живом сайте сообщества так попали `/about`,
    # политики и `/hi/lines/shayari/bengali`. Пара узнаётся по тому же пути
    # под другим языковым префиксом; переводы с другим слагом так не видны,
    # и о них говорится одной заметкой, а не находкой на каждой странице.
    from .checks import _locale_split
    by_rest = defaultdict(list)
    for page in pages:
        if indexable(page):
            host, lang, rest = _locale_split(page.url)
            by_rest[(host, rest)].append((lang, page))
    for page in self_only:
        host, lang, rest = _locale_split(page.url)
        others = [p.url for l, p in by_rest[(host, rest)] if l != lang]
        if others:
            issues.append(("warning", page.url, "hreflang-missing", tr(
                "по тому же пути есть страница на другом языке ({a0}), а hreflang "
                "этой страницы называет только её саму. Если это перевод — "
                "перечисли в нём все языковые версии",
                a0=", ".join(sorted(others)[:3]))))
    lonely = 0
    for page in empty:
        # В исходник на Markdown <link> не поставить — его добавит шаблон.
        if str(getattr(page, "path", "")).lower().endswith((".md", ".markdown")):
            continue
        host, lang, rest = _locale_split(page.url)
        others = [p.url for l, p in by_rest[(host, rest)] if l != lang]
        if not others:
            lonely += 1
            continue
        issues.append(("warning", page.url, "hreflang-missing",
                       tr("по тому же пути есть страница на другом языке "
                          "({a0}), а эта не объявляет ни одной альтернативы. "
                          "Если это перевод — свяжи их hreflang; если под "
                          "каждый рынок написан свой текст, связывать не нужно",
                          a0=", ".join(sorted(others)[:3]))))
    if lonely:
        notes.append(tr("{a0} открыт(ых) страниц без hreflang и без пары на "
                        "другом языке по тому же пути. Ошибкой не считается: "
                        "hreflang нужен только переводам. Если переводы есть, "
                        "но под другим адресом, — свяжи их вручную.", a0=lonely))

    if targets and not x_default:
        notes.append(tr("ни одна страница не объявляет `x-default`. Он не "
                        "обязателен, но именно он говорит, что показать тому, "
                        "чей язык не совпал ни с одним объявленным."))

    # Региональные пары: один язык, разные регионы — законно похожи.
    # Регион берётся из кода, которым страница объявляет в кластере саму себя,
    # а не из `<html lang>`: тот у `/us/` и `/uk/` обычно одинаковый `en`,
    # Google его не читает, и верно размеченные версии объявлялись дублями.
    def own_code(p):
        for code, href in declared.get(p.key, ()):
            if href and url_key(href) == p.key and code.strip().lower() != "x-default":
                return code.strip()
        return p.lang or ""

    for page in pages:
        for other_key in sorted(targets.get(page.key, ())):
            other = known.get(other_key)
            if other is None or other.key <= page.key:
                continue
            mine, theirs = own_code(page), own_code(other)
            if _same_language(mine, theirs) and mine.lower() != theirs.lower():
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
