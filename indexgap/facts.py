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
    "chf": "CHF", "try": "TRY", "₺": "TRY", "lira": "TRY", "ليرة": "TRY",
    "kzt": "KZT", "тенге": "KZT", "uah": "UAH", "грн": "UAH", "₴": "UAH",
    "гривень": "UAH",
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


def facts_of(page) -> dict:
    """{вид: {число: как написано}} — цены и проценты страницы."""
    from .content import _numbers_in, _shown
    out = {}
    for number, unit in _numbers_in(page.text or "", None).items():
        kind = _kind(unit)
        if kind:
            out.setdefault(kind, {})[number] = _shown(number, unit)
    return out


def _clusters(pages: list) -> list:
    """Связные группы страниц по hreflang (в любую сторону)."""
    from .hreflang import read_alternates
    by_key = {p.key: p for p in pages}
    parent = {k: k for k in by_key}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for page in pages:
        for _code, href in read_alternates(page):
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


def _converted(added: list, missing: list) -> bool:
    """
    Перевод показывает те же цены в другой валюте под тем же знаком:
    все пары «новое/старое» отличаются в одно и то же число раз, и это
    число далеко от единицы. Опечатка (`35` → `53`) или старая цена так
    не выглядят: они меняют одно число и ненамного.
    """
    if len(added) != len(missing):
        return False
    new = sorted(_value(n) for n in added)
    old = sorted(_value(n) for n in missing)
    if not all(new) or not all(old):
        return False
    ratios = [a / b for a, b in zip(new, old)]
    low, high = min(ratios), max(ratios)
    far = low >= CONVERSION_MIN_RATIO or high <= 1 / CONVERSION_MIN_RATIO
    return far and high / low <= 1 + _CONVERSION_SPREAD


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
                if added and missing and not _converted(added, missing):
                    issues.append(("warning", page.url, "fact-drift", tr(
                        "в переводе {a0}, а в оригинале ({a1}) {a2} — цифра разошлась при "
                        "переводе или осталась старой",
                        a0=", ".join(ours[n] for n in added[:4]), a1=ref.url,
                        a2=", ".join(theirs[n] for n in missing[:4]))))
    return issues
