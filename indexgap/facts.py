# -*- coding: utf-8 -*-
"""
Факты, которые разошлись между языковыми версиями одной страницы.

Перевод — место, где цифры портятся тихо: сбор $35 в оригинале становится
«$53» в арабской версии, срок «85%» — «58%» в индонезийской. Проверка фактов
против данных этого не видит, когда датасета нет или переводы делаются
отдельно от него, а читатель каждой версии видит только свой язык.

Сравниваются только сильные факты — цены и проценты, — и только в одной
валюте: арабская версия, которая сознательно показывает цены в дирхамах,
а английская в долларах, не расходится, а локализована. Переводы, закрытые
от индекса, не участвуют: их никто не увидит в выдаче.
"""

from __future__ import annotations

import re

from .core import url_key
from .i18n import tr

# Единица цены → валюта. Неизвестная единица сравнивается сама с собой.
_CURRENCY = {
    "$": "USD", "usd": "USD", "dollar": "USD", "dollars": "USD", "دولار": "USD",
    "دولارا": "USD", "دولارات": "USD", "долл": "USD", "доллар": "USD",
    "долларов": "USD", "доллара": "USD", "доллары": "USD", "dolar": "USD",
    "dólares": "USD", "dollari": "USD",
    "€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR", "евро": "EUR",
    "£": "GBP", "gbp": "GBP", "pound": "GBP", "pounds": "GBP",
    "₽": "RUB", "rub": "RUB", "руб": "RUB", "рубль": "RUB", "рублей": "RUB", "рубля": "RUB",
    "₹": "INR", "inr": "INR", "rupee": "INR", "rupees": "INR", "रुपये": "INR", "रुपया": "INR",
    "¥": "JPY", "jpy": "JPY", "円": "JPY", "yen": "JPY",
    "元": "CNY", "cny": "CNY", "yuan": "CNY",
    "₩": "KRW", "krw": "KRW", "원": "KRW", "won": "KRW",
    "₪": "ILS", "ils": "ILS", "שקל": "ILS", "שקלים": "ILS",
    "฿": "THB", "thb": "THB", "baht": "THB", "บาท": "THB",
    "ريال": "SAR", "sar": "SAR", "درهم": "AED", "aed": "AED", "دراهم": "AED",
    "sgd": "SGD", "myr": "MYR", "idr": "IDR", "aud": "AUD", "cad": "CAD",
    "chf": "CHF", "try": "TRY", "tl": "TRY", "₺": "TRY", "lira": "TRY", "ليرة": "TRY",
    "kzt": "KZT", "тенге": "KZT", "uah": "UAH", "грн": "UAH", "₴": "UAH",
    "гривень": "UAH",
    # Коды, которые content.CURRENCY_CODES читает ценой: без них цена в SEK
    # находилась, но не сравнивалась.
    "sek": "SEK", "nok": "NOK", "dkk": "DKK", "nzd": "NZD", "qar": "QAR",
    # Доллар по-немецки, по-турецки, по-польски, по-чешски, по-вьетнамски,
    # по-японски и по-китайски.
    "us-dollar": "USD", "us-dollars": "USD", "doları": "USD", "dolarları": "USD",
    "dolarów": "USD", "dolary": "USD", "dolarů": "USD", "đô": "USD",
    "米ドル": "USD", "美金": "USD",
    # Доллары по-персидски, на урду, бенгали, хинди, тайском, иврите, украинском,
    # японском, китайском и корейском.
    "دلار": "USD", "ڈالر": "USD", "ডলার": "USD", "डॉलर": "USD", "डालर": "USD",
    "ดอลลาร์": "USD", "דולר": "USD", "דולרים": "USD", "долар": "USD", "доларів": "USD",
    "долара": "USD", "долари": "USD", "ドル": "USD", "美元": "USD", "달러": "USD",
    "us$": "USD",
    "یورو": "EUR", "यूरो": "EUR", "ยูโร": "EUR", "יורו": "EUR", "ユーロ": "EUR",
    "欧元": "EUR", "유로": "EUR",
    "엔": "JPY", "人民币": "CNY", "港元": "HKD", "hk$": "HKD", "hkd": "HKD",
    "新元": "SGD", "s$": "SGD", "a$": "AUD", "au$": "AUD", "c$": "CAD", "ca$": "CAD",
    "nz$": "NZD", "nt$": "TWD", "r$": "BRL", "brl": "BRL", "mx$": "MXN", "mxn": "MXN",
    "col$": "COP", "cl$": "CLP", "rm": "MYR", "ringgit": "MYR", "rp": "IDR",
    "rupiah": "IDR", "rs": "INR", "টাকা": "BDT", "৳": "BDT", "রুপি": "INR",
    "روپے": "PKR", "روپیہ": "PKR", "تومان": "IRR", "تومن": "IRR", "ریال": "IRR",
    "₱": "PHP", "php": "PHP", "pesos": "MXN", "peso": "MXN", "₫": "VND", "đồng": "VND",
    "dong": "VND", "vnd": "VND", "riyal": "SAR", "riyals": "SAR", "dirham": "AED",
    "dirhams": "AED", "shekel": "ILS", "shekels": "ILS", "₦": "NGN", "naira": "NGN",
    "rand": "ZAR", "zar": "ZAR", "₸": "KZT", "pln": "PLN", "zł": "PLN", "złotych": "PLN",
}

# Знак `$` без буквы страны пишут и для песо, и для канадского, и для
# сингапурского доллара. Испанская версия с «$700» в песо при «$35» в
# оригинале — не расхождение, а пересчёт. Пересчёт виден по тому, что все
# числа перевода отличаются от оригинала в одно и то же число раз.
CONVERSION_MIN_RATIO = 2.0
_CONVERSION_SPREAD = 0.15

# Сколько разных цен одного вида на странице ещё сравнимо. Прайс-лист на сотню
# позиций — не «факт страницы», а таблица, и порядок строк в переводе другой.
MAX_FACTS = 25

# Сколько лишних цен одного вида перевод может показать и остаться сравнимым.
EXTRA_FACTS = 1


def _kind(unit: str) -> str:
    """Вид факта: `%` или валюта цены; пусто — не сравнивается."""
    text = (unit or "").strip().lower()
    if text == "%":
        return "%"
    for word in text.replace(".", " ").split():
        if word in _CURRENCY:
            return _CURRENCY[word]
    for ch in text:
        if ch in _CURRENCY:
            return _CURRENCY[ch]
    return ""


def _facts_in(text: str, out: dict) -> None:
    """Добавляет в out цены и проценты текста."""
    from .content import _numbers_in, _shown
    for number, unit in _numbers_in(text, None).items():
        kind = _kind(unit)
        if kind:
            out.setdefault(kind, {}).setdefault(number, _shown(number, unit))
    # _numbers_in хранит одну единицу на число: «$20 и 20%» или «$35 или €35»
    # теряли цену, и её расхождение не сравнивалось. Каждая валюта читается
    # ещё раз отдельно — остальные цены и проценты стёрты из текста.
    from . import content
    prepared = content._cjk_compounds(content._same_signs(text))
    spans = [(m.start(), m.end(), _kind(m.group(1))) for m in content.PREFIX_PRICE.finditer(prepared)]
    spans += [(m.start(), m.end(), _kind(m.group(0)[len(m.group(1)):]))
              for m in content.SUFFIX_PRICE.finditer(prepared)]
    for pattern in (content.PERCENT, content.PERCENT_WORD, content.PERCENT_BEFORE):
        spans += [(m.start(), m.end(), "%") for m in pattern.finditer(prepared)]
    kinds = {kind for _, _, kind in spans if kind}
    if len(kinds) < 2:
        return
    for kind in sorted(kinds - {"%"}):
        chars = list(prepared)
        for start, end, other in spans:
            if other != kind:
                chars[start:end] = " " * (end - start)
        for number, unit in _numbers_in("".join(chars), None).items():
            if _kind(unit) == kind:
                out.setdefault(kind, {}).setdefault(number, _shown(number, unit))


def facts_of(page) -> dict:
    """{вид: {число: как написано}} — цены и проценты страницы, её title и description."""
    out = {}
    # title и description видны в выдаче раньше текста: цена, разошедшаяся
    # только в них, — тоже расхождение.
    for text in (page.text, getattr(page, "title", ""), getattr(page, "description", "")):
        if text:
            _facts_in(text, out)
    return out


def _clusters(pages: list) -> list:
    """Связные группы страниц по hreflang языков (в любую сторону), без x-default."""
    from .hreflang import read_alternates
    by_key = {p.key: p for p in pages}
    parent = {k: k for k in by_key}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for page in pages:
        for code, href in read_alternates(page):
            # x-default часто ведёт на общую страницу выбора языка: через неё
            # все кластеры сайта слились бы в один с оригиналом без фактов.
            if (code or "").lower() == "x-default":
                continue
            other = url_key(href) if href else ""
            if other in by_key and other != page.key:
                parent[find(page.key)] = find(other)
    groups = {}
    for key in by_key:
        groups.setdefault(find(key), []).append(by_key[key])
    return [g for g in groups.values() if len(g) > 1]


def _reference(group: list):
    """Оригинал кластера: цель x-default, иначе английская версия, иначе самая богатая фактами."""
    from .hreflang import read_alternates
    keys = {p.key: p for p in group}
    for page in group:
        for code, href in read_alternates(page):
            if (code or "").lower() == "x-default" and url_key(href) in keys:
                return keys[url_key(href)]
    english = [p for p in group if (p.lang or "").lower().split("-")[0] == "en"]
    if english:
        return sorted(english, key=lambda p: p.url)[0]
    return max(group, key=lambda p: (sum(len(v) for v in facts_of(p).values()), p.url))


def _value(number: str) -> float:
    try:
        return float(number)
    except ValueError:
        return 0.0


# Единицы, у которых одна валюта: код ISO (`USD`, `EUR`), доллар с буквой
# страны (`US$`, `S$`) и знаки и слова одной валюты (`€`, `₹`, «евро»).
# Пересчёт «под тем же знаком» возможен только у `$`, `¥`, «долларов» и
# «песо»; у процента и у явной валюты 85% → 42% или €35 → €70 — расхождение.
_EXPLICIT_SIGNS = set("€£₽₹₩₪฿₺₴₸₱₫₦৳円元")
_EXPLICIT_WORDS = {"euro", "euros", "евро", "یورو", "यूरो", "ยูโร", "יורו", "ユーロ",
                   "欧元", "유로", "us$", "s$", "a$", "au$", "c$", "ca$", "hk$", "nz$",
                   "nt$", "r$", "mx$", "col$", "cl$"}


def _explicit(shown: str) -> bool:
    """Цена записана так, что валюту нельзя прочесть иначе."""
    from .content import CURRENCY_CODES
    codes = {c.lower() for c in CURRENCY_CODES.split("|")}
    tokens = re.sub(r"[\d.,'\s\u202f\u00a0]+", " ", shown or "").lower().split()
    for token in tokens:
        if token in codes or token in _EXPLICIT_WORDS or any(ch in _EXPLICIT_SIGNS for ch in token):
            return True
    return False


def _may_convert(kind: str, added: list, missing: list) -> bool:
    """Может ли разница быть пересчётом: не процент и не явная валюта с обеих сторон."""
    if kind == "%":
        return False
    return not all(_explicit(shown) for shown in added + missing)


def _converted(added: list, missing: list) -> bool:
    """
    Перевод показывает те же цены в другой валюте под тем же знаком:
    все пары «новое/старое» отличаются в одно и то же число раз, и это
    число далеко от единицы. Опечатка (`35` → `53`) или старая цена так
    не выглядят: они меняют одно число и ненамного.
    """
    if not added or len(added) > len(missing):
        return False
    if len(added) < len(missing):
        # Пересчёт, из которого перевод выбросил одну-две цены: остальные
        # всё равно отличаются в одно и то же число раз.
        if len(added) < 2 or len(missing) - len(added) > 2:
            return False
        from itertools import combinations
        return any(_converted(added, list(part)) for part in combinations(missing, len(added)))
    new = sorted(_value(n) for n in added)
    old = sorted(_value(n) for n in missing)
    if not all(new) or not all(old):
        return False
    ratios = [a / b for a, b in zip(new, old)]
    low, high = min(ratios), max(ratios)
    # Одна цена, выросшая или упавшая ровно в десять раз, — лишний или
    # потерянный ноль (`$35` → `$350`), а не курс валюты.
    if len(ratios) == 1 and (abs(low - 10) < 1e-9 or abs(low * 10 - 1) < 1e-9):
        return False
    far = low >= CONVERSION_MIN_RATIO or high <= 1 / CONVERSION_MIN_RATIO
    return far and high / low <= 1 + _CONVERSION_SPREAD


def _dearer_dollar(kind: str, added_shown: list, added: list, missing: list) -> bool:
    """
    Перевод пишет доллары явно (`350 USD`), и сумма выросла. Пересчётом это
    быть не может: доллара под знаком `$` дороже американского не бывает.
    """
    return (kind == "USD" and all(_explicit(shown) for shown in added_shown)
            and sum(_value(n) for n in added) > sum(_value(n) for n in missing))


def drift(pages: list) -> list:
    """
    `fact-drift`: перевод показывает цену или процент, которых нет в оригинале,
    а оригинальных того же вида у него нет. Пропуск одного числа — не находка
    (перевод мог сократить абзац); расхождение — когда вместо одного стоит другое.
    """
    from .publish import indexable
    live = [p for p in pages if indexable(p)]
    issues = []
    for group in _clusters(live):
        ref = _reference(group)
        ref_facts = facts_of(ref)
        if not ref_facts:
            continue
        for page in sorted(group, key=lambda p: p.url):
            if page is ref:
                continue
            mine = facts_of(page)
            for kind, theirs in sorted(ref_facts.items()):
                ours = mine.get(kind) or {}
                if not ours or len(theirs) > MAX_FACTS or len(ours) > MAX_FACTS:
                    continue
                # Перевод с заметно большим числом цен — другой текст (пример
                # расчёта, лишний абзац), а не те же цифры: сравнивать нечего.
                if len(ours) > len(theirs) + EXTRA_FACTS:
                    continue
                added = sorted(set(ours) - set(theirs))
                missing = sorted(set(theirs) - set(ours))
                if added and missing and not (
                        _may_convert(kind, [ours[n] for n in added], [theirs[n] for n in missing])
                        and _converted(added, missing)
                        and not _dearer_dollar(kind, [ours[n] for n in added], added, missing)):
                    issues.append(("warning", page.url, "fact-drift", tr(
                        "в переводе {a0}, а в оригинале ({a1}) {a2} — цифра разошлась при "
                        "переводе или осталась старой",
                        a0=", ".join(ours[n] for n in added[:4]), a1=ref.url,
                        a2=", ".join(theirs[n] for n in missing[:4]))))
    return issues
