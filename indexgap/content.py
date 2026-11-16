# -*- coding: utf-8 -*-
"""
Проверки самого текста — то, что агент написал, против того, что его просили написать.

Три вещи, которые на сотне страниц не поймать глазами:

  1. Выдуманные факты. В брифе написано «ничего не выдумывать», но никто это
     не проверяет. Сверяем числа из текста с данными строки: пошлина, срок,
     стоимость. Сотня страниц с выдуманными цифрами — это уже не SEO-проблема,
     а ущерб человеку, который по ним поедет.

  2. Шаблонные швы. Текст разный, а скелет один: те же H2 в том же порядке
     на всех страницах. Для поисковика это признак штамповки, даже когда
     слова не совпадают.

  3. Невыполненный бриф. Забытый блок инструкции в файле, `status: draft`,
     анкоры вида «здесь» и «подробнее».

Всё локально, без сети и ключей.

Что изменилось после аудита — три вещи, каждая отменяла проверку целиком:

  * фактом считалось только «число + единица из датасета». Если в датасете
    одна колонка с рублями, то «12 лет опыта», «3500 заказов» и «25 тонн»
    были невидимы: из семи выдумок ловилась одна;
  * число, стоящее на многих страницах, прощалось как «общее для сайта» —
    то есть выдумка, вбитая в шаблон, прощалась всегда. Теперь общим может
    быть только то, что есть хотя бы в одной строке датасета;
  * «1,500» превращалось в 1.5, и правильная английская цена объявлялась
    выдумкой, а ошибка в тысячу раз — нет.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from .subject import Said
from .core import (BRIEF_MARKERS, OWN_BRIEF_MARKERS, SLOT_TEMPLATE, brief_prose,
                   find_slots, tokenize, visible_text)
from .i18n import tr

CONFIG = {
    "template_share": 0.70,      # доля страниц с одинаковым скелетом заголовков
    "min_anchor_chars": 4,       # анкор короче — неинформативный
    "min_pages_for_seams": 5,    # ниже этого швы шаблона не оцениваются
    "match_min_score": 0.8,      # покрытие слов ключа заголовком страницы
}

# Число: либо разряды через пробел (18 000), либо целое с дробной частью.
# Жадное `[\d\s.,]*` съедало точки, запятые и переводы строк, и «* 44 / * 55 руб»
# давало критичную находку про несуществующее «4455 руб».
#
# Разряды с запятой и точкой идут первыми и целиком: `1,299.99` и немецкое
# `1.299,99` — одно число. Без них выражение брало `1,299`, а остаток `.99`
# склеивался со следующим куском, и цена, дословно стоящая в данных,
# объявлялась выдуманной «299.99 USD».
# Индийская запись (`12,34,567` — двенадцать лакхов) идёт раньше западной:
# иначе `12,34` бралось целиком как дробь 12,34, и верная цена из данных
# объявлялась выдуманной. Швейцарский апостроф `1'234.50` — разряды.
NUMBER = (r"\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d+)?|"
          r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,3}(?:\.\d{3})+(?:,\d+)?|"
          r"\d{1,3}(?:'\d{3})+(?:[.,]\d+)?|"
          r"\d{1,3}(?:[ \u202f\u00a0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")

# Число не начинается с середины другого: перед ним не цифра и не разделитель.
NOT_INSIDE = r"(?<![\d.,])"

# Пробелы, которыми разделяют разряды и число с единицей.
_SP = r"[   ]"
_HYPHEN_SIGNS = r"\-\u2010\u2011"

# Знаки, которыми другие письменности пишут то же самое. Арабский десятичный
# `٫` и разрядный `٬`, арабский `٪` и полноширинный `％`, типографский
# апостроф в `1’234`. Без этого `١٬٢٣٤٫٥٠` распадалось на куски, а `٩٥٪`
# не считалось процентом вовсе — выдуманная доля проходила молча.
_SAME_SIGNS = str.maketrans({"٫": ".", "٬": ",", "٪": "%",
                             "％": "%", "﹪": "%", "’": "'",
                             "ʼ": "'", "，": ",", "．": ".",
                             # Невидимые знаки направления письма: RTL-редакторы
                             # ставят `&rlm;` рядом с числом, и «35‏ دولارا» не
                             # читалось как цена.
                             "\u200e": None, "\u200f": None, "\u061c": None,
                             "\u2066": None, "\u2067": None, "\u2068": None,
                             "\u2069": None, "\u202a": None, "\u202b": None,
                             "\u202c": None, "\u202d": None, "\u202e": None})


def _same_signs(text: str) -> str:
    return (text or "").translate(_SAME_SIGNS)


# Множители после числа. «3万円» — тридцать тысяч иен, «1,5 млн» — полтора
# миллиона: в данных стоит 30000 и 1500000, и без множителя верная цифра
# объявлялась выдуманной, а выдуманная «5万» при 30000 в данных уходила
# в «просмотри глазами». CJK-знаки идут вплотную, словам нужна граница.
SCALES = {
    "万": 10**4, "萬": 10**4, "만": 10**4, "億": 10**8, "亿": 10**8, "억": 10**8,
    "千": 10**3, "천": 10**3,
    "тыс": 10**3, "тысяч": 10**3, "тысячи": 10**3, "тысяча": 10**3,
    "млн": 10**6, "миллион": 10**6, "миллиона": 10**6, "миллионов": 10**6,
    "млрд": 10**9, "миллиард": 10**9, "миллиарда": 10**9, "миллиардов": 10**9,
    "thousand": 10**3, "million": 10**6, "millions": 10**6, "mln": 10**6,
    "billion": 10**9, "billions": 10**9, "bn": 10**9,
    "lakh": 10**5, "lakhs": 10**5, "lac": 10**5, "crore": 10**7, "crores": 10**7,
    "mio": 10**6, "mrd": 10**9, "millionen": 10**6, "milliarden": 10**9,
    "millón": 10**6, "millones": 10**6, "mil": 10**3, "milliard": 10**9,
    "milliards": 10**9, "milioni": 10**6, "milione": 10**6, "miliardi": 10**9,
    "milhão": 10**6, "milhões": 10**6,
    # «$1.6k», «1.45K»: так цену пишут в карточках и объявлениях. Без «k»
    # верные $1,600 читались как $1.6 и становились критичной находкой.
    "k": 10**3,
}
_CJK_SCALES = "万萬만億亿억千천"
_SCALE_WORDS = "|".join(re.escape(w) for w in sorted(
    (k for k in SCALES if k[0] not in _CJK_SCALES), key=len, reverse=True))
_SCALE_AFTER = re.compile(
    _SP + r"?(?:([" + _CJK_SCALES + r"])|(" + _SCALE_WORDS + r")\.?(?![^\W\d_]))", re.I)


def _scale_in(unit: str) -> tuple:
    """(слово, множитель) множителя внутри подписи единицы — или ("", 1).

    Слово множителя — целым словом: «k» в «kg» и «mil» в «miles» — не тысяча.
    """
    lowered = (unit or "").lower()
    for word, factor in sorted(SCALES.items(), key=lambda kv: -len(kv[0])):
        if word[0] in _CJK_SCALES:
            if word in lowered:
                return word, factor
        elif re.search(r"(?<![^\W\d_])" + re.escape(word) + r"(?![^\W\d_])", lowered):
            return word, factor
    return "", 1


def _scale_at(text: str, end: int) -> tuple:
    """(множитель, длина) множителя сразу после числа — или (1, 0)."""
    match = _SCALE_AFTER.match(text, end)
    if not match:
        return 1, 0
    word = (match.group(1) or match.group(2)).lower()
    return SCALES.get(word, 1), match.end() - end

PERCENT = re.compile(NOT_INSIDE + r"(" + NUMBER + r")\s*%")

# Процент словом: «85 per cent», «85 процентов», «85 درصد». Без этого перевод,
# где знак `%` заменён словом, выпадал из сравнения цифр между языками.
PERCENT_WORDS = (
    "per\\s?cent|percent|pct|процент(?:ов|а|ы)?|відсотк(?:ів|а|и)|prozent|por\\s?ciento|"
    "pour\\s?cent|per\\s?cento|por\\s?cento|procent|persen|peratus|phần\\s?trăm|"
    "درصد|بالمائة|بالمئة|في\\s?المائة|प्रतिशत|শতাংশ|فیصد|เปอร์เซ็นต์|אחוז(?:ים)?"
)
# Знак процента перед числом: так пишут по-турецки («%85'i»), по-курдски и
# по-баскски. Перед знаком — начало, пробел или скобка, а не буква, цифра или
# `=`/`/`: `a%20b` и `?q=%20` в адресе — не проценты.
PERCENT_BEFORE = re.compile(r"(?:(?<=^)|(?<=[\s(«\"“„]))%(" + NUMBER + r")(?![\d%$]|[^\W\d_])", re.U)

PERCENT_WORD = re.compile(
    NOT_INSIDE + r"(" + NUMBER + r")" + _SP + r"?(?:" + PERCENT_WORDS + r")(?![^\W\d_])",
    re.I | re.U)

# Цена, записанная по-английски: валюта перед числом. Такие числа не искались
# вовсе, и единственная настоящая выдумка на странице — `$95` при `$60`
# в данных — была единственным, о чём проверка молчала.
CURRENCY_CODES = ("USD|EUR|GBP|JPY|CNY|INR|AUD|CAD|CHF|SGD|AED|RUB|BRL|MXN|KRW|TRY|"
                  "PLN|SEK|NOK|DKK|HKD|NZD|ZAR|THB|IDR|MYR|PHP|VND|SAR|QAR|KZT|UAH")
# Доллар с буквой страны и местные сокращения: `S$35`, `HK$200`, `R$ 90`,
# `RM 35`, `Rp 350.000`. Раньше такие цены не находились вовсе.
LOCAL_PREFIXES = r"(?:US|S|A|AU|C|CA|HK|NZ|NT|R|MX|COL|CL)\$|RM|Rp\.?|Rs\.?|₱|₫|₩|₪|₺|₴|₸|৳"
_LOCAL_PREFIX = re.compile(LOCAL_PREFIXES)
# Знак с пробелом — «$ 2,900», «€ 1.900» — та же цена: так пишут в нидерландской,
# немецкой и французской типографике. Но знак, перед которым стоит число
# («1.900 € 12 Monate»), — это валюта после числа, а не перед следующим.
PREFIX_PRICE = re.compile(
    r"(?<![\w.,$])((?:" + LOCAL_PREFIXES + r")[  \u00a0]?|[$€£¥₹₽](?=\d)|(?<!\d" + _SP + r")[$€£¥₹₽]" + _SP
    + r"|(?:" + CURRENCY_CODES + r")[  \u00a0]?)(" + NUMBER + r")(?![\d])")

# Валюта после числа: `9.900 €`, `9,900 ₪`, `٩٩٠٠ دولار`, `3万円`. Раньше
# ценой считалась только валюта перед числом, и выдуманная цена на испанском,
# иврите или арабском уходила в «просмотри глазами» вместо критичной находки.
CURRENCY_SIGNS = "€£¥₹₽₪₩₫₺₴₸฿$₱₦₵₡₲₭₮৳﷼円元圓원"
CURRENCY_WORDS = (
    "dollars?|dolar|dólares|dollari|euros?|pounds?|rupees?|yen|yuan|baht|pesos?|reais|"
    "доллар(?:ов|а|ы)?|евро|фунт(?:ов|а)?|"
    "francs?|lira|lire|zł|złotych|kronor|kroner|kč|lei|"
    "руб(?:л[а-яё]*)?|грн|гривен[а-яё]*|гривн[а-яё]*|тенге|сум|сомов|лари|"
    "دولار[ًا]?|دولارات|ريال|ريالات|درهم|دراهم|دينار|جنيه|ليرة|تومان|ریال|"
    "שקל|שקלים|ש\"ח|"
    "रुपये|रुपया|रुपए|บาท|đồng|"
    "دلار|یورو|تومن|ڈالر|روپے|روپیہ|ডলার|টাকা|রুপি|डॉलर|डालर|यूरो|"
    "ดอลลาร์|ยูโร|דולר|דולרים|יורו|долар(?:ів|а|и)?|гривень|"
    "ringgit|rupiah|dong|riyals?|dirhams?|shekels?|rand|naira|TL|"
    "ドル|ユーロ|美元|欧元|港元|新元|人民币|달러|유로|엔"
)
# Валютные слова CJK пишутся вплотную к следующему слову («35ドルです»), поэтому
# для них граница слова не нужна, в отличие от `dollar` в `dollars-and-sense`.
CJK_CURRENCY_WORDS = "ドル|ユーロ|美元|欧元|港元|新元|人民币|달러|유로"
SUFFIX_PRICE = re.compile(
    NOT_INSIDE + r"(" + NUMBER + r")"
    # Слово-множитель — целым словом: «18945 kgbp» — не тысячи фунтов.
    r"(?:" + _SP + r"?(?:[" + _CJK_SCALES + r"]|(?:" + _SCALE_WORDS + r")(?:\.|(?![^\W\d_]))))?"
    + _SP + r"?(?:" + CJK_CURRENCY_WORDS + r"|[" + CURRENCY_SIGNS + r"]|(?:" + CURRENCY_WORDS
    + "|" + CURRENCY_CODES + r")(?![^\W\d_]))", re.I | re.U)


# Общее «число + слово»: ловит «12 лет», «25 тонн», «3500 заказов» —
# то, чего нет в списке единиц проекта, но что всё равно является фактом.
# Отрицательный просмотр назад отсекает «топ-10», «айфон-15», «ГОСТ-12»:
# число, приклеенное к слову дефисом, — часть названия, а не мера.
GENERIC_FACT = re.compile(
    r"(?<![^\W\d_]-)" + NOT_INSIDE + "(" + NUMBER + ")[  \\u00a0]?(м²|м2|km²|[^\\W\\d_]{1,14}|[%°$€£₽¥₹])", re.U)

# Слова, которые после числа не делают его фактом: это нумерация и служебное.
NON_UNITS = {
    "и", "или", "а", "но", "в", "во", "на", "по", "из", "с", "со", "до", "от",
    "за", "к", "ко", "о", "об", "при", "для", "же", "ли", "не", "ни", "то",
    "это", "год", "года", "году", "годов", "г", "гг", "у", "я", "ю", "е",
    "без", "около", "почти", "более", "менее", "свыше", "всего", "лишь",
    "б", "ж", "з", "й", "ф", "х", "ц", "ш", "щ", "ы", "э",
    "and", "or", "the", "a", "an", "of", "in", "on", "at", "to", "for", "by",
    "is", "are", "was", "were", "no",
    # Счётные и порядковые контексты: «3 шага», «2 варианта», «5 звёзд»,
    # «1 этаж», «в 2 раза» — это речь, а не факты строки. Без этого списка
    # второй эшелон давал 62% шума.
    "шаг", "шага", "шагов", "вариант", "варианта", "вариантов", "раз", "раза",
    "звезда", "звезды", "звёзд", "звезд", "этаж", "этажа", "этаже", "балл",
    "балла", "баллов", "пункт", "пункта", "место", "места", "способ", "способа",
    "способов", "причин", "причины", "совет", "совета", "советов", "правило",
    "правила", "штука", "штуки", "часть", "части", "человек", "минимум",
    "максимум", "топ", "номер", "версия", "версии", "этап", "этапа", "этапов",
    "step", "steps", "ways", "way", "reasons", "tips", "things", "times",
    "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
    "сентября", "октября", "ноября", "декабря",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}

# То же для других языков: служебные слова, счётные контексты и месяцы.
# Только то, что после числа не бывает фактом строки: «3 Schritte», «5 pasos»,
# «15 janvier». «Jahre», «días», «tahun» сюда не входят — «12 Jahre am Markt»
# и есть тот факт, который проверка должна видеть.
NON_UNITS |= {
    # de
    "und", "oder", "der", "die", "das", "den", "dem", "des", "ein", "eine", "von",
    "im", "am", "zu", "zum", "zur", "für", "mit", "bis", "ab", "schritt", "schritte",
    "schritten", "tipps", "gründe", "mal", "sterne", "punkte", "stufe", "stufen",
    "januar", "februar", "märz", "mai", "juni", "juli", "oktober", "dezember",
    # fr
    "et", "ou", "le", "la", "les", "du", "des", "à", "au", "aux", "pour", "par",
    "sur", "étape", "étapes", "conseils", "raisons", "fois", "étoiles", "façons",
    "janvier", "février", "mars", "avril", "juin", "juillet", "août", "septembre",
    "octobre", "novembre", "décembre",
    # es / pt / it
    "y", "e", "o", "el", "lo", "los", "las", "del", "en", "por", "para", "con", "da",
    "do", "os", "as", "em", "no", "na", "com", "il", "gli", "di", "per",
    "paso", "pasos", "passo", "passos", "passi", "consejos", "dicas", "consigli",
    "razones", "razões", "motivi", "veces", "vezes", "volte", "estrellas", "estrelas",
    "stelle", "maneras", "formas", "modi",
    "enero", "febrero", "marzo", "mayo", "junio", "julio", "agosto", "octubre",
    "noviembre", "diciembre", "janeiro", "fevereiro", "março", "maio", "junho",
    "julho", "outubro", "novembro", "dezembro", "gennaio", "febbraio", "aprile",
    "maggio", "giugno", "luglio", "settembre", "ottobre", "dicembre",
    # nl / tr / pl
    "en", "of", "het", "een", "van", "op", "voor", "met", "stap", "stappen", "keer",
    "ve", "veya", "ile", "için", "bir", "adım", "adımda", "kez", "kere",
    "i", "lub", "w", "z", "na", "do", "krok", "kroki", "kroków", "razy",
    # id / ms
    "dan", "atau", "di", "ke", "dari", "untuk", "yang", "pada", "dengan", "langkah",
    "tips", "cara", "alasan", "kali", "bintang", "poin", "tahap",
    "januari", "februari", "maret", "mac", "april", "mei", "juni", "juli",
    "agustus", "ogos", "september", "oktober", "november", "desember", "disember",
    # ar / fa / ur / hi / bn
    "و", "أو", "في", "من", "إلى", "على", "خطوات", "خطوة", "مرات", "طرق", "نصائح",
    "و", "یا", "در", "از", "به", "مرحله", "بار", "روش",
    "اور", "یا", "میں", "سے", "مراحل", "مرحلے", "بار",
    "और", "या", "में", "से", "चरण", "बार", "तरीके", "सुझाव",
    "এবং", "বা", "ধাপ", "বার", "উপায়",
}


# Сокращения английских единиц времени: «44 min» при `34 minutes` в данных —
# та же единица. Без них ошибка уходила из критичных в «просмотри глазами».
_UNIT_SHORT = {"minutes": ("min", "mins"), "hours": ("hr", "hrs"),
               "seconds": ("sec", "secs")}


def _unit_forms(units: list) -> list:
    """Единицы проекта вместе с единственным числом и сокращениями: months → month."""
    out = set()
    for unit in units or ():
        unit = (unit or "").strip()
        if not unit:
            continue
        out.add(unit)
        lowered = unit.lower()
        if re.fullmatch(r"[a-z]{4,}s", lowered) and not lowered.endswith("ss"):
            out.add(unit[:-1])
        out.update(_UNIT_SHORT.get(lowered, ()))
    return sorted(out, key=len, reverse=True)


def build_fact_pattern(units: list):
    """Собирает выражение «число + единица» под единицы конкретного проекта."""
    units = _unit_forms(units)
    if not units:
        return None
    alternatives = "|".join(re.escape(u) for u in units)
    # Через дефис — составное прилагательное: «a 4-month deposit», «a 44-minute
    # ride». Раньше такое число не читалось вовсе. «5 min read» — подпись блога.
    return re.compile(NOT_INSIDE + r"(" + NUMBER + r")(?:[  \u00a0]|[" + _HYPHEN_SIGNS + r"])?(?:"
                      + alternatives + r")(?![^\W\d_])(?!" + _SP + r"read\b)", re.I | re.U)


def _norm_number(raw: str) -> str:
    """
    Нормализует число, различая разделитель разрядов и десятичную запятую.

    «1,500» в английском тексте — это полторы тысячи, «1,5» в русском —
    полтора. Раньше и то и другое становилось 1.5: правильная цена
    объявлялась выдумкой, а ошибка в тысячу раз проходила молча.
    """
    s = re.sub(r"[\s\xa0 ']", "", _same_signs(str(raw))).strip(".,")
    if not s:
        return ""
    if "." in s and "," in s:
        # Десятичным считается тот разделитель, который стоит последним.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        # 1,500 / 12,345,678 — разряды. 1,5 / 0,25 — десятичная дробь.
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3
                              and len(parts[0]) <= 3 and parts[0] != "0"):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3
                              and len(parts[0]) <= 3 and parts[0] != "0"):
            s = s.replace(".", "")
    try:
        value = float(s)
    except ValueError:
        return s
    return str(int(value)) if value == int(value) else str(value)


def _scaled(raw: str, factor: int) -> str:
    number = _norm_number(raw)
    if factor == 1 or not number:
        return number
    try:
        value = float(number) * factor
    except ValueError:
        return number
    return str(int(round(value))) if abs(value - round(value)) < 1e-6 else str(value)


# «14万5000円», «9万8千円», «14만 5000원» — одно число, 145000 и 98000. Раньше
# множитель применялся к одному числу, и от цены оставался хвост «5000円».
_CJK_COMPOUND = re.compile(r"(?<![\d.,])(\d{1,4})([万萬]|만" + _SP + r"?)(\d{1,4})([千천])?(?![\d.,]?\d)")


def _cjk_compounds(text: str) -> str:
    def joined(match):
        head = int(match.group(1)) * 10**4
        tail = int(match.group(3)) * (10**3 if match.group(4) else 1)
        if match.group(4) and tail >= 10**4:
            return match.group(0)
        if not match.group(4) and len(match.group(3)) != 4:
            # «3万5円» — не запись одного числа; разбирать её не берёмся.
            return match.group(0)
        return str(head + tail)
    return _CJK_COMPOUND.sub(joined, text or "")


def _numbers_in(text: str, fact_pattern) -> dict:
    """
    Числа, которые в этом тексте выглядят как факт.

    Возвращает {число: единица}. Единица нужна, чтобы в отчёте было написано
    «25 тонн», а не просто «25»: без неё находку невозможно проверить глазами.
    """
    found = {}
    text = _cjk_compounds(_same_signs(text))
    for match in PERCENT.finditer(text or ""):
        number = _norm_number(match.group(1))
        if number:
            found.setdefault(number, "%")
    for match in PERCENT_WORD.finditer(text or ""):
        number = _norm_number(match.group(1))
        if number:
            found.setdefault(number, "%")
    for match in PERCENT_BEFORE.finditer(text or ""):
        number = _norm_number(match.group(1))
        if number:
            found.setdefault(number, "%")
    if fact_pattern:
        for match in fact_pattern.finditer(text or ""):
            number = _norm_number(match.group(1))
            if number:
                found[number] = match.group(0)[len(match.group(1)):].strip(" -\u2010\u2011\u00a0\u202f")
                for earlier in _listed_before(text, match.start(1)):
                    found.setdefault(earlier, found[number])
    for match in PREFIX_PRICE.finditer(text or ""):
        sign = match.group(1).strip()
        factor, length = _scale_at(text, match.end())
        # «$1,600–2,400», «$950 to 1,900»: второй край — та же валюта, а
        # множитель в конце («$1.5–2 million») относится к обоим краям.
        second = _RANGE_SECOND.match(text, match.end() + length)
        if second and re.fullmatch(r"\d{4}", second.group(1)) and _year_like(second.group(1)):
            second = None
        if second:
            more, more_length = _scale_at(text, second.end())
            more_scale = text[second.end():second.end() + more_length].strip()
            value = _scaled(second.group(1), more)
            # Диапазон идёт вверх. «From $1,450 - 2 bedrooms» — не диапазон цен.
            if not _ascending(_scaled(match.group(2), more if factor == 1 else factor), value):
                second = None
        if second:
            found.setdefault(value, (sign + " " + more_scale).strip())
            if factor == 1 and more != 1:
                factor, length = more, 0
                scale = more_scale
        number = _scaled(match.group(2), factor)
        if number:
            if length:
                scale = text[match.end():match.end() + length].strip()
            elif factor == 1:
                scale = ""
            found.setdefault(number, (sign + " " + scale).strip())
    for match in SUFFIX_PRICE.finditer(text or ""):
        factor, _ = _scale_at(text, match.end(1))
        number = _scaled(match.group(1), factor)
        if number:
            unit = match.group(0)[len(match.group(1)):].strip()
            found.setdefault(number, unit)
            if factor == 1:
                for earlier in _listed_before(text, match.start(1)):
                    found.setdefault(earlier, unit)
    for match in list(PERCENT.finditer(text or "")) + list(PERCENT_WORD.finditer(text or "")):
        for earlier in _listed_before(text, match.start(1)):
            found.setdefault(earlier, "%")
    return found


# Перечисление, где единица стоит только после последнего числа: «29, 49
# и 149 долларов», «۲۹، ۴۹، ۱۴۹ و ۲۴۹ دلار», «10, 20 or 30%». Без этого
# цена бралась одна, и перевод, где так и пишут, «терял» остальные цифры.
# Перед последним числом нужен союз: «In 2026, 15%» — не перечисление.
_LIST_AND = (_SP + r"+(?:and|or|и|или|و|یا|und|oder|et|ou|y|o|e|dan|atau|và|hoặc|และ|"
             r"หรือ|ve|veya|और|या|এবং|ও|та|або|ו)" + _SP + r"+")
_LIST_COMMA = _SP + r"*[,،、;]" + _SP + r"*"
_LIST_LAST = re.compile(NOT_INSIDE + r"(" + NUMBER + r")(?:" + _LIST_COMMA + r")?" + _LIST_AND + r"$", re.I)
_LIST_MORE = re.compile(NOT_INSIDE + r"(" + NUMBER + r")" + _LIST_COMMA + r"$")
MAX_LISTED = 6

# Диапазон с одной единицей: «12–27 minutes», «4 to 6 months», «10–15%»,
# «$1,600–2,400». Проверялся только край рядом с единицей, и выдуманный
# второй край проходил молча. Число не должно сидеть в слове («COVID-19»,
# «A4-5») — это название, а не край диапазона.
_RANGE_JOIN = (r"(?:" + _SP + r"*[" + _HYPHEN_SIGNS + r"–—]" + _SP + r"*|" + _SP
               + r"+(?:to|до|bis|tot|à)" + _SP + r"+)")
_RANGE_FIRST = re.compile(r"(?<![\w.,\-–—])(" + NUMBER + r")" + _RANGE_JOIN + r"$", re.I)
_RANGE_SECOND = re.compile(_RANGE_JOIN + r"(" + NUMBER + r")(?![\d.,]?\d)(?![\w\-–—])", re.I)


def _ascending(low: str, high: str) -> bool:
    try:
        return float(low) < float(high)
    except (TypeError, ValueError):
        return False


def _year_like(number: str) -> bool:
    return number.isdigit() and 1900 <= int(number) <= 2100


def _listed_before(text: str, start: int) -> list:
    """Числа перечисления прямо перед числом с единицей — без своей единицы."""
    match = _RANGE_FIRST.search(text, max(0, start - 40), start)
    if match:
        number = _norm_number(match.group(1))
        last = re.match(NUMBER, text[start:])
        if number and not _year_like(number) and last and _ascending(number, _norm_number(last.group(0))):
            return [number]
        return []
    out, end, pattern = [], start, _LIST_LAST
    while len(out) < MAX_LISTED:
        match = pattern.search(text, max(0, end - 40), end)
        if not match:
            break
        number = _norm_number(match.group(1))
        if not number or _year_like(number):
            break
        out.append(number)
        end, pattern = match.start(), _LIST_MORE
    return out


_SCALE = re.compile(r"(?:\b(?:out\s+of|of|из|von|sur|su|de|na)\s+|/\s?)(?:5|10|100)\b(?!\s?%)",
                    re.I)


def _generic_numbers_in(text: str) -> dict:
    """«Число + любое слово» — второй эшелон: слабее сигнал, но покрывает всё."""
    found = {}
    # Верх шкалы — «4.6 out of 5», «4,6 из 5», «4.6/5» — постоянная, а не
    # факт строки: на каталоге это давало `check-by-eye` на 164 страницах из 202.
    text = _SCALE.sub(" ", _cjk_compounds(_same_signs(text)))
    for match in GENERIC_FACT.finditer(text):
        unit = match.group(2).strip().lower()
        if unit in NON_UNITS or unit.isdigit():
            continue
        factor, _ = _scale_at(text, match.end(1))
        number = _scaled(match.group(1), factor)
        if not number:
            continue
        # Год в тексте — не факт строки: «в 2026 году», «с 1998 г.» Годом
        # считается только голое четырёхзначное число: `1,900` с разделителем
        # разрядов — это тысяча девятьсот чего-то, а не год.
        if re.fullmatch(r"\d{4}", match.group(1)) and 1900 <= int(number) <= 2100:
            continue
        found.setdefault(number, match.group(2).strip())
    return found


# ── числа прописью ────────────────────────────────────────────────────────────
#
# «Гарантия — двенадцать месяцев» при `6 месяцев` в строке — та же выдумка, что
# «12 месяцев», только цифрой её не поймать: сроки и количества модель пишет
# словами охотнее, чем цены. Страница с таким текстом проходила сверку молча.
#
# Уровень — «просмотри глазами», а не критичная находка. Прописью пишут и
# общие слова о предмете: на демо-сайте пакета «usually within three to six
# months» стоит в обычном абзаце при `3 months` в строке, и критичная находка
# там была бы ложной. Отличить такой абзац от выдуманного срока по тексту
# нельзя, поэтому число показывается человеку, а `--strict` не роняет.
#
# Читается только то, в чём нельзя ошибиться:
#
#   * числительное от 2 до 99, и сразу за ним единица проекта. «Два слова»,
#     «three reasons» — речь, а не факт строки, и сюда не попадают;
#   * «один месяц», «one day» не читаются вовсе: это почти всегда оборот;
#   * хвост большего числа — «сто двадцать минут», «one hundred and twenty
#     minutes» — не читается как 20: сотни здесь не разбираются, а неверно
#     прочитанное число хуже непрочитанного;
#   * русский и английский, и только на странице этого языка или без `lang`.
#     Французское `six mois` при `lang="fr"` — не наш словарь.
#
# Русские формы — именительный с винительным и родительный: именно они стоят
# перед единицей в том виде, в каком она записана в датасете («двенадцать
# месяцев», «в течение двенадцати месяцев»), и собирательные «двое», «трое»,
# «четверо» — обычная форма перед «суток».
_SPELLED = {
    "ru": {
        "ones": {"один": 1, "одна": 1, "одно": 1, "одного": 1, "одной": 1, "одну": 1,
                 "два": 2, "две": 2, "двух": 2, "двое": 2, "три": 3, "трёх": 3,
                 "трех": 3, "трое": 3, "четыре": 4, "четырёх": 4, "четырех": 4,
                 "четверо": 4, "пять": 5, "пяти": 5,
                 "шесть": 6, "шести": 6, "семь": 7, "семи": 7, "восемь": 8,
                 "восьми": 8, "девять": 9, "девяти": 9},
        "teens": {"десять": 10, "десяти": 10, "одиннадцать": 11, "одиннадцати": 11,
                  "двенадцать": 12, "двенадцати": 12, "тринадцать": 13,
                  "тринадцати": 13, "четырнадцать": 14, "четырнадцати": 14,
                  "пятнадцать": 15, "пятнадцати": 15, "шестнадцать": 16,
                  "шестнадцати": 16, "семнадцать": 17, "семнадцати": 17,
                  "восемнадцать": 18, "восемнадцати": 18, "девятнадцать": 19,
                  "девятнадцати": 19},
        "tens": {"двадцать": 20, "двадцати": 20, "тридцать": 30, "тридцати": 30,
                 "сорок": 40, "сорока": 40, "пятьдесят": 50, "пятидесяти": 50,
                 "шестьдесят": 60, "шестидесяти": 60, "семьдесят": 70,
                 "семидесяти": 70, "восемьдесят": 80, "восьмидесяти": 80,
                 "девяносто": 90, "девяноста": 90},
        "bigger": {"сто", "ста", "двести", "двухсот", "триста", "трёхсот", "трехсот",
                   "четыреста", "четырёхсот", "четырехсот", "пятьсот", "пятисот",
                   "шестьсот", "шестисот", "семьсот", "семисот", "восемьсот",
                   "восьмисот", "девятьсот", "девятисот", "тысяча", "тысячи",
                   "тысяч", "тысячу", "миллион", "миллиона", "миллионов",
                   "миллиард", "миллиарда", "миллиардов"},
    },
    "en": {
        "ones": {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9},
        "teens": {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
                  "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
                  "eighteen": 18, "nineteen": 19},
        "tens": {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
                 "seventy": 70, "eighty": 80, "ninety": 90},
        "bigger": {"hundred", "thousand", "million", "billion"},
    },
}
# Десятки с единицами соединяют пробелом или одним дефисом — любым из тех, что
# ставит вёрстка: неразрывным, тире. С одним ASCII-дефисом «twenty‑six months»
# читалось как «six months» — при 6 в строке выдуманные 26 сходили за данные.
# Тире в пробелах — уже не одно число: «twenty — five minutes after your call».
_HYPHENS = r"\-\u2010\u2011"
_JOIN = r"(?:\s+|[" + _HYPHENS + r"\u2013\u2014])"
# Слово перед числительным — через любые знаки: «one thousand, twenty minutes».
_WORD_BEFORE = re.compile(r"([^\W\d_]+)\W+$")


def build_spelled_patterns(units: list) -> dict:
    """Выражения «числительное + единица проекта» по языкам — или пусто без единиц."""
    # Единица в одну букву или служебное слово — «16 A», «220 В», `in` — после
    # числительного оказывается обычной речью: «two a day», «три в ряд».
    units = sorted({u for u in _unit_forms(units)
                    if len(u) > 1 and u.lower() not in NON_UNITS},
                   key=len, reverse=True)
    if not units:
        return {}
    unit = "|".join(re.escape(u) for u in units)

    def any_of(words):
        return "|".join(sorted(words, key=len, reverse=True))

    patterns = {}
    for lang, table in _SPELLED.items():
        single = [w for w, n in table["ones"].items() if n > 1] + list(table["teens"])
        patterns[lang] = re.compile(
            # Не внутри слова и не после слова с дефисом: «top-six months»,
            # «fourty-six months» — не «six months».
            r"(?<![^\W\d_])(?<![^\W\d_][" + _HYPHENS + r"])"
            r"(?:(?P<tens>" + any_of(table["tens"]) + r")"
            r"(?:" + _JOIN + r"(?P<ones>" + any_of(table["ones"]) + r"))?"
            r"|(?P<single>" + any_of(single) + r"))"
            # «a six-month deposit» — через один дефис, как и цифрой.
            r"(?:" + _SP + r"+|[" + _HYPHENS + r"])(?P<unit>" + unit + r")(?![^\W\d_])(?!" + _SP + r"read\b)", re.I | re.U)
    return patterns


def _tail_of_bigger(text: str, start: int, bigger: set) -> bool:
    """Стоит ли перед числительным сотня или тысяча: «сто двадцать», «hundred and twenty»."""
    match = _WORD_BEFORE.search(text, max(0, start - 40), start)
    if match and match.group(1).lower() == "and":
        match = _WORD_BEFORE.search(text, max(0, match.start() - 40), match.start())
    return bool(match) and match.group(1).lower() in bigger


def _spelled_numbers_in(text: str, patterns: dict, lang: str = "") -> dict:
    """
    Числа прописью с единицей проекта: {число: (единица, как написано)}.

    Написание нужно отчёту: находка показывает число так, как оно стоит на
    странице, иначе «12 месяцев» на ней не найти.
    """
    found = {}
    code = (lang or "").strip().lower()[:2]
    # Мягкий перенос стоит внутри слова и на странице не виден: «twen­ty-six».
    text = (text or "").replace("\u00ad", "")
    for name, pattern in patterns.items():
        if code and code != name:
            continue
        table = _SPELLED[name]
        for match in pattern.finditer(text):
            if _tail_of_bigger(text, match.start(), table["bigger"]):
                continue
            # Без учёта регистра `i` совпадает и с турецкими `İ`, `ı`, а `s` — с
            # `ſ`; в словаре таких написаний нет. Слово, которого нет в словаре,
            # не читается: падение на «SİX MONTHS» останавливало весь прогон.
            if match.group("single"):
                word = match.group("single").lower()
                value = table["ones"].get(word) or table["teens"].get(word)
            else:
                tens, ones = match.group("tens"), match.group("ones")
                value = table["tens"].get(tens.lower())
                if value and ones:
                    more = table["ones"].get(ones.lower())
                    # Границы блоков в тексте страницы — пробел: «…a crew of
                    # twenty» и «Five minutes from…» из соседних пунктов списка
                    # — не двадцать пять.
                    apart = ones[0].isupper() and not tens[0].isupper()
                    value = value + more if more and not apart else None
            if not value:
                continue
            found.setdefault(str(value), (match.group("unit"),
                                          " ".join(match.group(0).split())))
    return found


# Число в данных строки: не приклеенное к буквам, чтобы артикул «A-90-15»
# не выдавал индульгенцию выдуманной цифре 90.
#
# Дефис сам по себе числу не мешает: `3-5 days` — это и 3, и 5, а `2026-03-15`
# — три числа. Мешает буква в той же цепочке через дефис. Раньше любой дефис
# рядом выбрасывал число, и диапазон из данных не поддерживал собственные края.
ROW_NUMBER = re.compile(r"(?<![\w.,])(" + NUMBER + r")(?!\w)")
_SCALED_NUMBER = re.compile(r"(?<![\w.,])(" + NUMBER + r")")
_CHAIN = re.compile(r"[\w\-–—]*")
_CHAIN_BACK = re.compile(r"[\w\-–—]*$")


# Единица, приклеенная к числу в ячейке: «34min», «1450EUR», «45m²», «145000円»,
# «34分». Так пишут в таблицах и всегда — в японском и китайском. Буквы перед
# числом и цифры после единицы — уже артикул («A90», «90A15»), его число не берётся.
_GLUED_UNIT = re.compile(r"(?<![\w.,\-–—])(" + NUMBER + r")[^\W\d_]{1,8}(?![\w\-–—])")


def _numbers_of(value) -> list:
    """Числа из одного значения строки — кроме тех, что сидят в артикуле."""
    text, out = str(value), []
    for match in _GLUED_UNIT.finditer(text):
        out.append(match.group(1))
    for match in ROW_NUMBER.finditer(text):
        chain = (_CHAIN_BACK.search(text[:match.start()]).group(0)
                 + _CHAIN.match(text, match.end()).group(0))
        if re.search(r"[^\W\d_]", chain):
            continue
        out.append(match.group(1))
    return out


def _row_numbers(row: dict) -> set:
    out = set()
    for value in (row or {}).values():
        text = _same_signs(str(value))
        for raw in _numbers_of(text):
            number = _norm_number(raw)
            if number:
                out.add(number)
        # «3万» или «1,5 млн» в самих данных: и как есть, и в единицах. Своё
        # выражение: обычное отбрасывает число, приклеенное к знаку (артикул),
        # а CJK-множитель — тоже знак.
        for match in _SCALED_NUMBER.finditer(text):
            factor, _ = _scale_at(text, match.end(1))
            if factor != 1:
                out.add(_norm_number(match.group(1)))
                out.add(_scaled(match.group(1), factor))
    return out


def _site_constants(rows: list, share: float = 0.5) -> set:
    """
    Числа, постоянные для всего сайта: фиксированная пошлина, срок гарантии,
    год основания — то, что законно стоит на каждой странице.

    Раньше прощалось ЛЮБОЕ число из любой строки датасета. На каталоге
    из 5000 строк это 1993 значения, включая все целые от 1 до 100, —
    то есть 85% выдумок получали индульгенцию автоматически, и чем крупнее
    проект, тем меньше работала проверка. Постоянная величина — та, что
    повторяется в одной и той же колонке у большинства строк.
    """
    rows = list(rows or ())
    if not rows:
        return set()
    # Считаются не отдельные числа, а набор чисел ячейки: «3-5 days» во всех
    # строках — это постоянные 3 и 5 вместе. Постоянной колонку делает одно
    # значение, которое встречается чаще других. Если два значения делят колонку
    # поровну — «2 months» в половине строк и «3 months» в другой, — это не
    # постоянная, а данные строки: раньше прощались оба, и страница с чужим
    # сроком залога проходила молча.
    per_column = defaultdict(Counter)
    for row in rows:
        for column, value in (row or {}).items():
            numbers = frozenset(n for n in (_norm_number(raw) for raw in _numbers_of(value)) if n)
            if numbers:
                per_column[column][numbers] += 1
    threshold = max(2, int(len(rows) * share))
    out = set()
    for counter in per_column.values():
        top = counter.most_common(2)
        if top[0][1] < threshold:
            continue
        if len(top) > 1 and top[1][1] == top[0][1]:
            continue
        out |= top[0][0]
    return out


def _stems(text: str) -> set:
    from .generate import STOPWORDS, _stem
    tokens = re.findall(r"\w+", (text or "").lower(), flags=re.UNICODE)
    return {_stem(t) for t in tokens if t not in STOPWORDS}


def _slug_of(page, root: str) -> str:
    rel = os.path.relpath(page.path, root).replace(os.sep, "/")
    rel = re.sub(r"(^|/)index\.(html?|md|markdown)$", r"\1", rel, flags=re.I)
    rel = re.sub(r"\.(html?|md|markdown)$", "", rel, flags=re.I).strip("/")
    return rel.rsplit("/", 1)[-1] if rel else ""


# Колонка, в которой генератор хранит адрес страницы строки.
SLUG_COLUMNS = ("slug", "url", "path", "permalink", "page", "uri", "handle", "url_path",
                "page_url", "адрес", "ссылка", "урл")


def _slug_column(rows: list, keyword_field: str) -> str:
    fields = [f for f in (rows[0].keys() if rows else ()) if f and f != keyword_field]
    for name in SLUG_COLUMNS:
        for field in fields:
            if field.strip().lower() == name:
                return field
    return ""


def _path_forms(value: str) -> tuple:
    """`berlin`, `/rent/berlin/`, `rent/berlin.html`, `https://x.com/rent/berlin` → (полный путь, последний сегмент)."""
    from urllib.parse import urlsplit
    text = (value or "").strip()
    if "://" in text:
        text = urlsplit(text).path
    text = re.sub(r"(^|/)index\.(html?|md|markdown)$", r"\1", text, flags=re.I)
    text = re.sub(r"\.(html?|md|markdown)$", "", text, flags=re.I).strip("/").lower()
    return text, text.rsplit("/", 1)[-1] if text else ""


def match_rows(pages: list, rows: list, keyword_field: str, root: str,
               cfg: dict = None) -> dict:
    """
    Связывает страницу с исходной строкой датасета.

    Три пути, от надёжного к приблизительному: ключ во фронтматтере, совпадение
    slug, покрытие слов ключа заголовком. Неоднозначность больше не разрешается
    «в пользу первого попавшегося»: если два кандидата подходят одинаково,
    страница считается несопоставленной. Раньше результат зависел от порядка
    строк в CSV, и верные цифры объявлялись выдумкой.
    """
    from .generate import slugify

    cfg = {**CONFIG, **(cfg or {})}
    by_keyword, by_slug = {}, {}
    slug_clash = set()
    for row in rows:
        key = (row.get(keyword_field) or "").strip()
        if not key:
            continue
        by_keyword.setdefault(key.lower(), row)
        slug = slugify(key)
        if slug in by_slug and by_slug[slug] is not row:
            slug_clash.add(slug)
        by_slug.setdefault(slug, row)

    # Колонка адреса — самая надёжная связь после ключа во фронтматтере:
    # демо с колонками `query` и `slug` давало «сверено 0 из 10», и выдуманная
    # цена пропадала из отчёта.
    slug_field = _slug_column(rows, keyword_field)
    by_path, by_last, last_clash = {}, {}, set()
    if slug_field:
        for row in rows:
            full, last = _path_forms(row.get(slug_field) or "")
            if not last:
                continue
            by_path.setdefault(full, row)
            if last in by_last and by_last[last] is not row:
                last_clash.add(last)
            by_last.setdefault(last, row)

    matched, ambiguous = {}, []
    # Сначала надёжные связи — по ключу во фронтматтере и по slug, для всех
    # страниц. Строка, у которой так нашлась своя страница, приблизительному
    # сопоставлению по заголовку уже не предлагается: иначе строку «austin
    # villa» получали ещё и хаб `/austin/`, и статья блога с теми же словами в
    # заголовке — и их числа сверялись с чужими данными.
    claimed, pending = set(), []
    for page in pages:
        key = (page.meta.get("keyword") or "").strip().lower()
        row = by_keyword.get(key) if key else None
        if row is None and slug_field:
            rel = os.path.relpath(page.path, root).replace(os.sep, "/")
            full, last = _path_forms(rel)
            row = by_path.get(full) or (by_last.get(last) if last not in last_clash else None)
        if row is None:
            slug = _slug_of(page, root)
            if slug in slug_clash:
                ambiguous.append(page.url)
                continue
            row = by_slug.get(slug)
        if row is not None:
            matched[page.url] = row
            claimed.add(id(row))
        else:
            pending.append(page)
    free = sorted(k for k, r in by_keyword.items() if id(r) not in claimed)

    for page in pending:
        row = None
        haystack = " ".join([page.title] + [t for _, t in page.headings[:2]]).lower()
        # Ключи из Вордстата в именительном падеже, заголовки — в предложном.
        # Без нормализации словоформ сопоставлялось 10 страниц из 100,
        # и сверка фактов молча выключалась на девяти десятых сайта.
        haystack_tokens = _stems(haystack)
        scored = []
        for candidate_key in free:
            key_tokens = _stems(candidate_key)
            if not key_tokens:
                continue
            scored.append((len(key_tokens & haystack_tokens) / len(key_tokens),
                           len(key_tokens), candidate_key))
        scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
        if scored and scored[0][0] >= cfg["match_min_score"]:
            # Ничья означает, что мы не знаем, какая строка чья.
            if len(scored) > 1 and abs(scored[1][0] - scored[0][0]) < 1e-9 \
                    and scored[1][1] == scored[0][1]:
                ambiguous.append(page.url)
            else:
                row = by_keyword[scored[0][2]]

        if row is not None:
            matched[page.url] = row
    return {"matched": matched, "ambiguous": sorted(set(ambiguous)), "slug_field": slug_field}


def _shown(number: str, unit: str) -> str:
    """Число с единицей так, как его пишут: `$1900`, а не `1900 $`."""
    # Множитель показывается так, как стоит на странице: «5万元», а не
    # «50000 万元», которое читается как пятьсот миллионов.
    lowered = (unit or "").lower()
    word, factor = _scale_in(unit)
    if word:
        try:
            raw = _norm_number(repr(round(float(number) / factor, 6)))
        except ValueError:
            raw = ""
        if raw:
            glue = "" if word[0] in _CJK_SCALES and lowered.startswith(word) else " "
            if unit and unit[0] in "$€£¥₹₽":
                parts = unit.split()
                rest = " ".join(parts[1:])
                # «$1.6k» — множитель в одну букву пишут вплотную.
                if len(rest) == 1:
                    return f"{parts[0]}{raw}{rest}"
                return f"{parts[0]}{raw} {rest}".strip()
            return f"{raw}{glue}{unit}".strip()
    if unit and unit in "$€£¥₹₽":
        return f"{unit}{number}"
    if unit and _LOCAL_PREFIX.fullmatch(unit):
        return f"{unit}{number}" if unit.endswith("$") or len(unit) == 1 else f"{unit} {number}"
    if unit and unit.upper() in CURRENCY_CODES.split("|"):
        return f"{unit} {number}"
    return f"{number} {unit}".strip()


def _supported(number: str, unit: str, allowed: set) -> bool:
    """
    Есть ли число в данных — как есть или до множителя: «1,5 млн» при 1,5
    в колонке «цена, млн» — тоже из данных.
    """
    if number in allowed:
        return True
    word, factor = _scale_in(unit)
    if word:
        try:
            raw = float(number) / factor
        except ValueError:
            return False
        if _norm_number(repr(round(raw, 6))) in allowed:
            return True
    return False


# Число, которое страница посчитала из своей строки: «три месяца аренды
# вперёд — $4,350» при `rent: $1,450` и `deposit: 3 months`. В данных его нет,
# но и выдумкой оно не является — итог, годовая цена, скидка. Критичной
# находкой оно роняло `--strict` на верных страницах. Теперь оно уходит в
# «просмотри глазами» с подсказкой, как его можно было получить: человек
# проверит, а совпадение не пройдёт незамеченным. Лучшее решение — отдельная
# колонка с посчитанным значением: тогда генератор и проверка читают одно.
DERIVED_MIN = 100         # меньше — слишком легко получить случайно
DERIVED_MAX_INPUTS = 12   # в строке длиннее совпадение пар становится правилом


_MONEY = re.compile(
    r"(?:" + LOCAL_PREFIXES + r"|[" + CURRENCY_SIGNS + r"]|" + CJK_CURRENCY_WORDS + r")|"
    r"(?<![^\W\d_])(?:" + CURRENCY_WORDS + "|" + CURRENCY_CODES + r")(?![^\W\d_])", re.I | re.U)
_PERCENT_COLUMN = re.compile(r"%|percent|pct|процент|discount|скидк", re.I)


def _kind(text: str) -> str:
    """Чем меряется значение: `money`, слово единицы или пусто для голого числа."""
    text = _same_signs(str(text or ""))
    if _MONEY.search(text):
        return "money"
    if "%" in text or PERCENT_WORD.search(text):
        return "%"
    words = re.findall(r"[^\W\d_]+", text.lower())
    # «minutes» и «minute», «месяцев» и «месяца» — одна единица.
    return words[-1][:4] if words else ""


def _row_kinds(row: dict) -> dict:
    """{число строки: чем оно меряется} — для чисел, посчитанных из строки."""
    out = {}
    for column, value in (row or {}).items():
        kind = "%" if _PERCENT_COLUMN.search(str(column or "")) else _kind(value)
        for raw in _numbers_of(_same_signs(str(value))):
            number = _norm_number(raw)
            if number:
                out.setdefault(number, kind)
    return out


def _derivation(number: str, row_numbers: set, kinds: dict = None, kind: str = None) -> str:
    """
    Как число получается из двух чисел строки — или пусто.

    С `kinds` (чем меряется каждое число строки) и `kind` (чем меряется само
    число) счёт должен сходиться по единицам: цена — это цена из строки, умноженная
    на что угодно, срок — срок, умноженный на голое число, доля — от числа той же
    меры и только по числу, которое в строке записано процентом. Без этого
    «$961 = 31 × 31 минуту» и «$2037 = 2100 − 3 месяца %» уходили в мелочи.
    """
    try:
        target = float(number)
    except ValueError:
        return ""
    if abs(target) < DERIVED_MIN:
        return ""
    values = []
    for raw in row_numbers:
        try:
            value = float(raw)
        except ValueError:
            continue
        if value not in (0.0, 1.0):
            values.append((value, raw))
    if len(values) > DERIVED_MAX_INPUTS:
        return ""
    values.sort()

    def same(x):
        return abs(x - target) < 0.005 or (target == round(target) and abs(x - target) < 0.5
                                            and x != round(x))

    def of(raw):
        return (kinds or {}).get(raw, "")

    def product_fits(ra, rb):
        if kinds is None:
            return True
        for one, other in ((ra, rb), (rb, ra)):
            if kind == "money" and of(one) == "money":
                return True
            if kind and kind != "money" and of(one) == kind and of(other) == "":
                return True
        return False

    def share_fits(rbig, rpct):
        if kinds is None:
            return True
        return of(rpct) == "%" and bool(kind) and of(rbig) == kind

    for i, (a, ra) in enumerate(values):
        # Число само на себя не умножается: «$961 = 31 × 31» — не расчёт.
        for b, rb in values[i + 1:]:
            # Только произведение и доля: суммы и разности пар объясняют
            # почти любое число, и выдумка уходила бы в «мелочи».
            if same(a * b) and product_fits(ra, rb):
                return f"{ra} × {rb}"
            for big, rbig, pct, rpct in ((b, rb, a, ra), (a, ra, b, rb)):
                if 0 < pct < 100 and share_fits(rbig, rpct):
                    if same(big * pct / 100):
                        return f"{rpct}% × {rbig}"
                    if same(big * (100 - pct) / 100):
                        return f"{rbig} − {rpct}%"
    return ""


def _with_head(page) -> str:
    """Текст страницы вместе с <title> и meta description, если их нет в тексте."""
    text = page.text or ""
    extra = []
    for part in (getattr(page, "title", ""), getattr(page, "description", "")):
        part = (part or "").strip()
        if part and part not in text and part not in extra:
            extra.append(part)
    # Абзацем: число из заголовка не склеивается с первым словом текста.
    return "\n\n".join(extra + [text]) if extra else text


def check_facts(pages: list, matched: dict, rows: list, cfg: dict = None,
                fact_units: list = None) -> list:
    """
    Числа в тексте, которых нет в данных строки. Это кандидаты в выдумку.

    Прощается только то, что встречается где-то в датасете: год, телефон,
    срок действия паспорта в соседней строке — это данные проекта. Число,
    которого нет во всём датасете, не прощается никогда, сколько бы страниц
    его ни повторяло. Раньше было наоборот: выдумка, вбитая в шаблон, стояла
    на всех страницах и потому всегда считалась «общей для сайта».
    """
    cfg = {**CONFIG, **(cfg or {})}
    if not matched:
        return []
    fact_pattern = build_fact_pattern(fact_units)
    spelled_patterns = build_spelled_patterns(fact_units)
    constants = _site_constants(rows)

    issues = []
    for page in sorted(pages, key=lambda p: p.url):
        row = matched.get(page.url)
        if row is None:
            continue
        allowed = _row_numbers(row) | constants

        # Заголовок и описание — тот текст, который человек видит в выдаче:
        # «$1,900» в <title> при $1,450 в строке — та же выдумка, что в абзаце.
        text = _with_head(page)
        strong = _numbers_in(text, fact_pattern)
        weak = _generic_numbers_in(text)
        # Прописью — во второй эшелон. Если то же число стоит на странице и
        # цифрой при случайном слове, показываются оба написания: «twelve
        # months» не должно прятаться за «12 reviewers», а «6 awards» — за «six
        # months». Число, уже ставшее критичной находкой, ниже отсеивается само.
        generic = set(weak)
        written = {}
        for number, (unit, phrase) in _spelled_numbers_in(
                text, spelled_patterns, getattr(page, "lang", "")).items():
            weak.setdefault(number, unit)
            written[number] = phrase

        def shown(number, unit):
            if number not in written:
                text = _shown(number, unit)
            else:
                text = written[number] + (", " + _shown(number, unit) if number in generic else "")
            if number in derived:
                text += tr(" (= {a0} из строки?)", a0=derived[number])
            return text

        unknown_strong = {n: u for n, u in strong.items() if not _supported(n, u, allowed)}
        own = _row_numbers(row)
        kinds = _row_kinds(row)
        derived = {n: how for n, u in unknown_strong.items()
                   for how in [_derivation(n, own, kinds, _kind(u))] if how}
        for number in derived:
            weak[number] = unknown_strong.pop(number)
        unknown_weak = {n: u for n, u in weak.items()
                        if not _supported(n, u, allowed) and n not in unknown_strong}

        if unknown_strong:
            issues.append((
                "critical", page.url, "unsupported-number",
                Said(tr("в тексте есть числа, которых нет в данных: ")
                     + ", ".join(_shown(n, u) for n, u in
                                 sorted(unknown_strong.items())[:6])
                     + (tr(" и ещё") if len(unknown_strong) > 6 else ""),
                     unknown_strong)))
        if unknown_weak:
            # Одна строка на страницу и уровень «мелочь»: это список
            # для просмотра глазами, а не приговор. Раньше каждое такое
            # число становилось отдельным предупреждением, и 62% отчёта
            # занимал шум вроде «3 шага» и «5 звёзд».
            # Числа прописью — первыми: у них единица проекта, и за «и ещё N»
            # им не место.
            listed = sorted(unknown_weak.items(),
                            key=lambda kv: (kv[0] not in written and kv[0] not in derived,
                                           -len(kv[0]), kv[0]))[:8]
            issues.append((
                "info", page.url, "check-by-eye",
                Said(tr("числа, которых нет в данных — просмотри глазами: ")
                     + ", ".join(shown(n, u) for n, u in listed)
                     + (tr(" и ещё {a0}", a0=len(unknown_weak) - len(listed))
                        if len(unknown_weak) > len(listed) else ""),
                     unknown_weak)))
    return issues


def _opening(page) -> list:
    """
    Слова, с которых начинается текст страницы, — после её заголовка.

    У страницы без <main> в начале текста стоят баннер и меню: на pyvideo
    «A thank you to everyone who makes this possible» и пункты навигации
    давали `same-opening` на 21 756 страницах. Текст статьи начинается после
    её H1 — или первого заголовка, если H1 нет.
    """
    words = page.words
    heads = page.headings or []
    title = next((t for level, t in heads if level == 1), heads[0][1] if heads else "")
    marker = tokenize(title) if title else []
    if marker:
        window = words[:300]
        for at in range(len(window) - len(marker) + 1):
            if window[at:at + len(marker)] == marker:
                return words[at + len(marker):]
    return words


SLOT_MARK = "…"


def _slot_skeletons(pages: list, skip: set) -> dict:
    """Скелеты заголовков, где слова-подстановки из H1 заменены меткой."""
    h1_words = {}
    df = Counter()
    for page in pages:
        heads = page.headings or []
        h1 = next((t for level, t in heads if level == 1), "")
        own = {w.lower() for w in tokenize(h1) if len(w) >= 2 and not w.isdigit()}
        h1_words[page.url] = own
        df.update(own)
    half = len(pages) / 2
    out = defaultdict(list)
    for page in pages:
        if page.url in skip:
            continue
        slots = {w for w in h1_words[page.url] if df[w] < half}
        if not slots:
            continue
        skeleton, masked = [], False
        for level, text in page.headings or []:
            if level < 2:
                continue
            tokens = [w.lower() for w in tokenize(text)]
            kept = [SLOT_MARK if w in slots else w for w in tokens]
            # Заголовок из одного значения («Alpha») — не шаблонная фраза:
            # такой скелет совпал бы у любых страниц со списком городов.
            if SLOT_MARK in kept and any(w != SLOT_MARK for w in kept):
                masked = True
                skeleton.append(" ".join(kept))
            else:
                skeleton.append(text.strip().lower())
        if masked and len(skeleton) >= 2:
            out[tuple(skeleton)].append(page.url)
    return out


def check_template_seams(pages: list, cfg: dict = None) -> dict:
    """
    Ищет общий скелет: одинаковую последовательность заголовков.
    Возвращает и находки, и сам повторяющийся скелет — его полезно показать.
    """
    cfg = {**CONFIG, **(cfg or {})}
    if len(pages) < cfg["min_pages_for_seams"]:
        return {"issues": [], "repeated": [],
                "skipped": tr("страниц {a0} — мало для оценки шаблонности", a0=len(pages))}

    skeletons = defaultdict(list)
    for page in pages:
        skeleton = tuple(text.strip().lower() for level, text in page.headings if level >= 2)
        if len(skeleton) >= 2:
            skeletons[skeleton].append(page.url)

    issues, repeated = [], []
    # Порог считается от страниц, у которых скелет вообще есть. Раньше он брался
    # от всех страниц, и сайт из двух половин (городские + услуговые страницы)
    # с двумя разными шаблонами проходил проверку молча.
    with_skeleton = sum(len(urls) for urls in skeletons.values())
    threshold = max(3, int(max(with_skeleton, 1) * cfg["template_share"]))
    stamped = set()
    for skeleton, urls in sorted(skeletons.items()):
        if len(urls) >= threshold:
            repeated.append({"headings": list(skeleton), "count": len(urls)})
            stamped.update(urls)
            for url in sorted(urls):
                issues.append((
                    "warning", url, "template-skeleton",
                    tr("те же {a0} заголовков в том же порядке ещё у {a1} страниц", a0=len(skeleton), a1=len(urls) - 1)))

    # «Сколько стоит в Alpha», «Где искать в Alpha»: подставленное значение
    # стоит и в подзаголовках, и скелеты по точному тексту не совпадали ни у
    # одной пары. Слово из H1, которое есть меньше чем у половины страниц, —
    # значение подстановки; оно заменяется меткой, и скелеты сравниваются
    # ещё раз. Только для страниц, которых точное сравнение не нашло.
    for skeleton, urls in sorted(_slot_skeletons(pages, stamped).items()):
        if len(urls) >= threshold:
            repeated.append({"headings": list(skeleton), "count": len(urls)})
            for url in sorted(urls):
                issues.append((
                    "warning", url, "template-skeleton",
                    tr("те же {a0} заголовков в том же порядке ещё у {a1} страниц", a0=len(skeleton), a1=len(urls) - 1)))

    # Одинаковое начало текста — второй признак штамповки. Считается по основному
    # тексту: раньше сюда попадало меню, и находка срабатывала на любом сайте.
    openings = defaultdict(list)
    for page in pages:
        words = _opening(page)[:12]
        if len(words) >= 8:
            openings[" ".join(words)].append(page.url)
    for opening, urls in sorted(openings.items()):
        if len(urls) >= max(3, int(len(pages) * 0.3)):
            for url in sorted(urls):
                issues.append((
                    "warning", url, "same-opening",
                    tr("первые слова текста совпадают ещё у {a0} страниц", a0=len(urls) - 1)))

    return {"issues": issues,
            "repeated": sorted(repeated, key=lambda r: (-r["count"], r["headings"])),
            "skipped": ""}



# Иероглиф несёт примерно столько же, сколько слово: «中文» — это «на китайском»,
# и по длине его мерить нельзя. На живом сайте виз переключатель языков и ссылки
# на соцсети давали `vague-anchor` на всех 2 970 страницах — сто процентов сайта,
# то есть находка без смысла.
# По длине анкор судим только там, где длина что-то значит: латиница,
# кириллица, греческий. В иероглифике знак несёт столько же, сколько слово;
# в деванагари, бенгали, арабице, корейском, тайском слово короче латинского
# по числу кодовых точек, но не по смыслу.
#
# Измерено на живом сайте виз: `vague-anchor` срабатывал на 295 страницах
# из 296 на хинди, столько же на бенгали и урду — и ни на одной английской.
# Причиной были «यमन» (Йемен) и «হোম» (Главная): три знака, полное слово.
#
# Список именно белый, а не чёрный: чёрный я уже написал неверно — диапазон
# «нелатиницы» захватил кириллицу, и «тут» перестало быть находкой.
JUDGEABLE_LETTER = re.compile(r"[A-Za-z\u00c0-\u024f\u0370-\u03ff\u0400-\u052f]")
ANY_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

# Короткие анкоры, информативные сами по себе: языки и площадки.
KNOWN_SHORT_ANCHORS = {
    "vk", "x", "fb", "ok", "tg", "wa", "yt", "in", "li", "рф",
    "en", "ru", "de", "fr", "es", "it", "pt", "pl", "cs", "tr", "ar", "fa",
    "hi", "bn", "ur", "zh", "id", "ms", "ja", "ko", "th", "vi", "uz", "kk",
}


def _uninformative_length(anchor: str, cfg: dict) -> bool:
    """
    Короткий анкор — не всегда бессмысленный.

    По длине судим только там, где длина что-то значит: латиница и кириллица.
    Для остальных письменностей остаётся список бессмысленных слов — а его
    для них нет, и пакет молчит. Молчание честнее, чем 295 находок из 296,
    все ложные.
    """
    text = anchor.strip()
    if text.lower() in KNOWN_SHORT_ANCHORS:
        return False
    letters = ANY_LETTER.findall(text)
    if not letters:
        return False
    if any(not JUDGEABLE_LETTER.match(ch) for ch in letters):
        return False
    # «FAQ», «ROI», «API», «ЖКХ»: аббревиатура заглавными — подпись пункта
    # меню, а не «тут». Одна буква аббревиатурой не бывает.
    if len(letters) >= 2 and "".join(letters).isupper():
        return False
    return len(text) < cfg["min_anchor_chars"]


_FIELD_LEFTOVER = re.compile(r"\b(?:undefined|NaN)\b|(?<=\S)\s+\b(?:null|None)\b")
# Пустое значение стоит там, где генератор подставляет поле: в начале, после
# предлога или разделителя. «Plumbers in undefined», «Austin, null» — шов;
# «Handling None values», «Why NaN !== NaN» — предмет текста.
_SLOT_BEFORE = re.compile(
    r"(?:^|[,|·•—–:;(\-]|\b(?:in|for|near|at|from|of|to|в|во|для|на|из|по|у))\s*$", re.I)
# `{{ft^2}}` — нотация единиц, а не переменная: внутри шва стоит имя поля.
_SLOT_NAME = re.compile(r"^\s*[A-Za-z_][\w.]*\s*(?:\|[^{}]*)?$")
_IDENT = re.compile(r"[A-Za-z_]\w*")


def _docs_page(page) -> bool:
    """Страница с примерами кода: `{FOLDER_NAME}` и `undefined` на ней — нотация автора."""
    raw = (page.raw or "")[:400_000].lower()
    return "<pre" in raw or "<code" in raw


def _field_leftovers(value: str) -> list:
    hits = list(_FIELD_LEFTOVER.finditer(value))
    if len({m.group(0).strip() for m in hits}) > 1:
        return []                          # «null vs undefined» — тема, а не шов
    return [m.group(0).strip() for m in hits
            if _SLOT_BEFORE.search(value[:m.start()])]


def _template_verdict(sample: str, columns: set, docs: bool) -> str:
    """
    Шов шаблона: critical, warning или пусто.

    С датасетом решают его колонки: `{{city}}` при колонке `city` — шов,
    `{FOLDER_NAME}` — нотация документации. Без датасета на странице с кодом
    это предупреждение, на странице без кода — критично, как и было.
    """
    if sample.startswith("{{") and not _SLOT_NAME.match(sample[2:-2]):
        return ""
    names = {n.lower() for n in _IDENT.findall(sample)}
    if columns:
        return "critical" if names & columns else "warning"
    return "warning" if docs else "critical"

_EMPTY_SLOT = re.compile(
    # «Plumbers in , TX»: пробел перед знаком — пустое место. «Where it comes
    # from?» — законный предлог в конце фразы, пробела там нет.
    # Знак после пробела и перед пробелом или концом: «GraphQL for .NET» и
    # «in .editorconfig» — не пустое место. `pick()` — вызов функции.
    r"\b(?:in|for|near|at|from|of|в|во|для|на|из|по)\s+[,.;:|)](?=\s|$)"
    r"|^\s*[|–—:,\-]\s|(?<![\w)])\(\s*\)|,\s+,")
_LD_LEFTOVER = {"undefined", "NaN", "null", "None", "[object Object]"}


def _ld_strings(node, depth=0):
    if depth > 40:
        return
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _ld_strings(value, depth + 1)
    elif isinstance(node, list):
        for value in node:
            yield from _ld_strings(value, depth + 1)


def check_slots(pages: list, fields=(), cfg: dict = None) -> list:
    """
    Следы незаполненного шаблона: `{{city}}`, `%CITY%`, `undefined`, `NaN`,
    `[object Object]`, «Plumbers in , TX», lorem ipsum, ответ модели вместо
    текста, текст в чужой кодировке.

    Видимый текст разбор собирает сам, без кода и скриптов (`core.find_slots`).
    Здесь добавляются поля, которые генератор заполняет отдельно: title,
    description, заголовки и JSON-LD. Слово в квадратных скобках — шов, только
    если так называется колонка датасета: «[City]» при колонке `city`.
    """
    columns = {str(f).strip().lower() for f in fields or () if str(f).strip()}
    issues = []
    for page in sorted(pages, key=lambda p: p.url):
        markdown = (page.path or "").lower().endswith((".md", ".markdown"))
        slots = page.slots
        if slots is None:
            slots = find_slots(visible_text(page.raw) if not markdown else page.text,
                               markdown=markdown)
        critical, empty = [], []
        docs = _docs_page(page)
        llm = [s for k, s in slots if k == "llm"]
        mojibake = [s for k, s in slots if k == "mojibake"]
        for kind, sample in slots:
            if kind == "template":
                verdict = _template_verdict(sample, columns, docs)
                if verdict == "critical":
                    critical.append(sample)
                elif verdict:
                    empty.append(sample)
            elif kind == "leftover":
                (empty if docs else critical).append(sample)
            elif kind == "lorem":
                # Документация шаблонизаторов показывает lorem ipsum в примерах
                # (hexo.io). На странице каталога это забытая заглушка — но
                # видна она и так, а критичной находкой заслоняла бы остальное.
                empty.append(sample)
            elif kind == "bracket" and sample.strip("[]").strip().lower() in columns:
                critical.append(sample)
        fields_text = [page.title or "", page.description or ""] + [
            t for level, t in (page.headings or []) if level <= 2]
        for value in fields_text:
            if not markdown:
                for m in SLOT_TEMPLATE.finditer(value):
                    verdict = _template_verdict(m.group(0), columns, docs)
                    if verdict == "critical":
                        critical.append(m.group(0))
                    elif verdict:
                        empty.append(m.group(0))
            if not docs:
                critical += _field_leftovers(value)
            if not docs and _EMPTY_SLOT.search(value):
                # `opt_*()`, `if ()`, «| — побитовое ИЛИ» — заголовки справочника.
                empty.append(value.strip())
        for block in page.jsonld or []:
            try:
                data = json.loads(block)
            except (ValueError, RecursionError):
                continue
            for value in _ld_strings(data):
                if value.strip() in _LD_LEFTOVER:
                    critical.append(value.strip())
                else:
                    critical += [m.group(0) for m in SLOT_TEMPLATE.finditer(value)]
        critical = list(dict.fromkeys(critical))
        if critical or empty:
            shown = ", ".join(f"«{s}»" for s in (critical or empty)[:3])
            issues.append(("critical" if critical else "warning", page.url, "unfilled-slot",
                           tr("незаполненные места шаблона: {a0}", a0=shown)))
        if llm:
            issues.append(("warning", page.url, "llm-leftover",
                           tr("в тексте остался ответ модели, а не текст страницы: «{a0}»",
                              a0=llm[0])))
        if mojibake:
            issues.append(("warning", page.url, "mojibake",
                           tr("текст в неверной кодировке: «{a0}» — файл сохранён в одной "
                              "кодировке, а прочитан в другой", a0=mojibake[0])))
    return issues


def _other_draft(page) -> list:
    """
    Остальные пометки черновика, которые понимает `publish.is_draft`: `draft:
    true` (Hugo), `published: false` (Jekyll), `status: wip`, дата публикации в
    будущем. Такую страницу пакет не берёт в sitemap и IndexNow, а её находки
    о содержимом снимает. Раньше об этом не говорилось ничего: страница просто
    исчезала из отчёта.
    """
    from datetime import date
    from .publish import is_draft
    if not is_draft(page):
        return []
    meta = {str(k).lower().replace("-", "_"): v for k, v in (page.meta or {}).items()}
    for key in ("publishdate", "publish_date"):
        value = str(meta.get(key, "")).strip().strip("'\"")[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value) and value > date.today().isoformat():
            return [("info", page.url, "still-draft",
                     tr("публикация запланирована на {a0} — до этого дня страница не "
                        "публикуется и не проверялась как открытая", a0=value))]
    label = "draft"
    for key, values in (("status", ("wip", "unpublished")), ("draft", ("true", "yes", "1")),
                        ("published", ("false", "no", "0"))):
        value = str(meta.get(key, "")).strip().lower()
        if value in values:
            label = f"{key}: {value}"
            break
    return [("critical", page.url, "still-draft",
             tr("{a0} — страница помечена как черновик и не будет опубликована",
                a0=label))]


def check_brief(pages: list, cfg: dict = None) -> list:
    """Выполнен ли бриф: не остались ли следы заготовки и вменяемы ли анкоры."""
    cfg = {**CONFIG, **(cfg or {})}
    issues = []
    for page in sorted(pages, key=lambda p: p.url):
        raw = brief_prose(page.raw)
        if any(marker in raw for marker in OWN_BRIEF_MARKERS):
            issues.append(("critical", page.url, "brief-left",
                           tr("в файле остался блок брифа или TODO — страница не дописана")))
        elif any(marker in raw for marker in BRIEF_MARKERS):
            # Руководство по стилю, описывающее комментарии `TODO:`, получало
            # «страница не дописана» критичной находкой.
            issues.append(("warning", page.url, "brief-left",
                           tr("в тексте страницы есть «TODO» — если это пометка автора, "
                              "а не предмет текста, страница не дописана")))
        status = (page.meta.get("status") or "").lower()
        if status in ("draft", "черновик", "todo"):
            issues.append(("critical", page.url, "still-draft",
                           tr("status: {a0} — страница помечена как незаконченная", a0=status)))
        else:
            issues += _other_draft(page)

        vague_list = {v.lower() for v in cfg.get("vague_anchors", ())}
        # Названия городов — «Омск», «Сочи», «Тула» — короткие и совершенно
        # информативные. Порог в восемь символов помечал 100% гео-анкоров.
        vague = [a for a in page.anchors
                 if a and (a.strip().lower() in vague_list
                           or _uninformative_length(a, cfg))]
        if vague:
            issues.append(("info", page.url, "vague-anchor",
                           tr("неинформативные анкоры: ")
                           + ", ".join(f"«{a}»" for a in vague[:4])))
    return issues


def run(pages: list, rows: list = None, keyword_field: str = "keyword",
        root: str = ".", cfg: dict = None, fact_units: list = None) -> dict:
    """Все контентные проверки разом."""
    cfg = {**CONFIG, **(cfg or {})}
    issues = []
    matched, ambiguous = {}, []
    facts_checked = False

    if rows:
        result = match_rows(pages, rows, keyword_field, root, cfg)
        matched, ambiguous = result["matched"], result["ambiguous"]
        # Сверка фактов работает всегда, когда есть с чем сверять. Раньше она
        # включалась только при непустом списке единиц — и молча выключалась
        # на датасете без валют, то есть на большинстве проектов.
        issues += check_facts(pages, matched, rows, cfg, fact_units)
        facts_checked = bool(matched)
        # Сверка, которая молча покрыла треть сайта, хуже отсутствия сверки:
        # человек видит «критичных 0» и думает, что числа проверены.
        if len(pages) >= 5 and len(matched) < len(pages) * 0.5:
            issues.append(("warning", "", "dataset-unbound", tr(
                "сверка с датасетом покрыла {a0} из {a1} страниц — числа остальных не "
                "проверялись. Свяжи страницы со строками: колонка slug или url в датасете, "
                "`keyword:` во фронтматтере или <meta name=\"keyword\"> в шаблоне",
                a0=len(matched), a1=len(pages))))

    seams = check_template_seams(pages, cfg)
    issues += seams["issues"]
    issues += check_brief(pages, cfg)
    issues += check_slots(pages, fields=list(rows[0].keys()) if rows else (), cfg=cfg)

    notes = []
    if seams.get("skipped"):
        notes.append(tr("швы шаблона не оценивались: ") + seams["skipped"])
    if ambiguous:
        notes.append(
            tr("{a0} страниц(ы) подошли сразу к нескольким строкам датасета — сверка фактов для них не делалась. Добавь `keyword` во фронтматтер, чтобы связь была однозначной.", a0=len(ambiguous)))

    return {
        "issues": issues,
        "repeated_skeletons": seams["repeated"],
        # Не только счётчик, но и сама связь: `brief` кладёт в наряд строку
        # датасета, чтобы человек чинил числа по данным, а не по памяти.
        "matched": matched,
        "matched_rows": len(matched),
        "ambiguous": ambiguous,
        "facts_checked": facts_checked,
        "fact_units": sorted(fact_units or []),
        "notes": notes,
        "unmatched": sorted(p.url for p in pages if p.url not in matched) if rows else [],
        # В обратную сторону: строка без страницы — сбой генерации или фильтр.
        "rows_without_page": sorted(
            str(r.get(keyword_field) or "") for r in (rows or [])
            if id(r) not in {id(v) for v in matched.values()}),
    }
