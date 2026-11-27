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
import unicodedata
from functools import lru_cache
from urllib.parse import urlsplit
from collections import Counter, defaultdict
from .subject import Said
from .core import (BRIEF_MARKERS, OWN_BRIEF_MARKERS, SLOT_TEMPLATE, brief_prose,
                   find_slots, tokenize, visible_text)
from .core import NOT_SHOWN, drop_spans
from .i18n import tr
from .settings import unit_word

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
                             # Полноширинные «￥9,900» и «＄99» — те же иена и
                             # доллар, «45㎡» — те же квадратные метры.
                             "￥": "¥", "＄": "$", "㎡": "m²",
                             # Невидимые знаки направления письма: RTL-редакторы
                             # ставят `&rlm;` рядом с числом, и «35‏ دولارا» не
                             # читалось как цена.
                             "\u200e": None, "\u200f": None, "\u061c": None,
                             "\u2066": None, "\u2067": None, "\u2068": None,
                             "\u2069": None, "\u202a": None, "\u202b": None,
                             "\u202c": None, "\u202d": None, "\u202e": None,
                             # Гершаим: «ש״ח» — та же запись, что «ש"ח».
                             "\u05f4": '"',
                             # Невидимые знаки без ширины и мягкий перенос:
                             # «$&#8203;1,900» и «1,6&shy;00» на экране — одно число.
                             "\u200b": None, "\u2060": None, "\ufeff": None,
                             "\u180e": None, "\u00ad": None})

# Невидимые знаки у самой цифры: ZWNJ, ZWJ, ZWSP, word joiner, мягкий перенос.
# «۹۹‌٪» с ZWNJ не читалось как процент. Внутри слов ZWNJ нужен (персидский),
# поэтому снимается только рядом с цифрой.
_GLUE_AT_DIGIT = re.compile(r"(?<=\d)[\u200b-\u200d\u2060\u00ad\ufeff]+|[\u200b-\u200d\u2060\u00ad\ufeff]+(?=\d)")
# Арабская запятая между разрядами: «١،٦٠٠ دولار» — 1600, а не 1 и 600.
_ARABIC_THOUSANDS = re.compile(r"(?<![\d.,،])\d{1,3}(?:،\d{3})+(?![\d.,،]?\d)")
# Персидская дробь через косую черту: «۳/۵ درصد» — 3.5%. Только между
# персидскими или арабскими цифрами и перед процентом, множителем или валютой:
# дату «۱۴۰۳/۰۵/۱۲» и оценку «۴/۵» это не трогает.
_PERSIAN_SLASH = re.compile(
    r"(?<![\d/])([\u0660-\u0669\u06f0-\u06f9]+)/([\u0660-\u0669\u06f0-\u06f9]+)(?![\d/])"
    r"(?=[ \u00a0\u200c]?(?:%|٪|درصد|هزار|میلیون|میلیارد|تومان|تومن|ریال|دلار|یورو))")


def _same_signs(text: str) -> str:
    text = _GLUE_AT_DIGIT.sub("", text or "")
    text = _ARABIC_THOUSANDS.sub(lambda m: m.group(0).replace("،", ","), text)
    text = _PERSIAN_SLASH.sub(r"\1.\2", text)
    return text.translate(_SAME_SIGNS)


# Множители после числа. «3万円» — тридцать тысяч иен, «1,5 млн» — полтора
# миллиона: в данных стоит 30000 и 1500000, и без множителя верная цифра
# объявлялась выдуманной, а выдуманная «5万» при 30000 в данных уходила
# в «просмотри глазами». CJK-знаки идут вплотную, словам нужна граница.
SCALES = {
    "万": 10**4, "萬": 10**4, "만": 10**4, "億": 10**8, "亿": 10**8, "억": 10**8,
    "千": 10**3, "천": 10**3,
    # «8千万円», «2천만원» — десять миллионов: раньше читалось как тысяча.
    "千万": 10**7, "千萬": 10**7, "천만": 10**7,
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
    # Арабский, персидский, урду, иврит, хинди, бенгали, индонезийский и
    # тайский: «٣ ملايين دولار», «۹۹ هزار تومان», «₹15 लाख», «Rp 8,5 juta».
    # Без них выдумка в тысячу раз проходила молча, а верная цена с
    # множителем объявлялась выдуманной.
    "ألف": 10**3, "الف": 10**3, "آلاف": 10**3, "ألاف": 10**3,
    "مليون": 10**6, "ملايين": 10**6, "مليار": 10**9,
    "هزار": 10**3, "میلیون": 10**6, "میلیارد": 10**9,
    "ہزار": 10**3, "لاکھ": 10**5, "کروڑ": 10**7,
    "אלף": 10**3, "אלפים": 10**3, "מיליון": 10**6, "מיליארד": 10**9,
    "हज़ार": 10**3, "हजार": 10**3, "\u0939\u095b\u093e\u0930": 10**3, "लाख": 10**5,
    "करोड़": 10**7, "\u0915\u0930\u094b\u095c": 10**7,
    "হাজার": 10**3, "লাখ": 10**5, "লক্ষ": 10**5, "কোটি": 10**7,
    "lacs": 10**5, "cr": 10**7,
    "ribu": 10**3, "rb": 10**3, "juta": 10**6, "jt": 10**6, "miliar": 10**9,
    "triliun": 10**12,
    "พัน": 10**3, "หมื่น": 10**4, "แสน": 10**5, "ล้าน": 10**6,
}
_CJK_SCALES = "万萬만億亿억千천"
# Тайские множители, как и CJK, пишутся слитно с валютой: «15 ล้านบาท».
_GLUED_SCALES = ("พัน", "หมื่น", "แสน", "ล้าน")
_SCALE_WORDS = "|".join(re.escape(w) for w in sorted(
    (k for k in SCALES if k[0] not in _CJK_SCALES and k not in _GLUED_SCALES),
    key=len, reverse=True))
_CJK_SCALE = r"千[万萬]|천만|[" + _CJK_SCALES + r"]"
_SCALE_AFTER = re.compile(
    _SP + r"?(?:(" + _CJK_SCALE + "|" + "|".join(_GLUED_SCALES) + r")|("
    + _SCALE_WORDS + r")\.?(?![^\W\d_]))", re.I)


# Множители, которые пишут только при цене: «$2.54M», «£2.6m», «₹2.5 Cr»,
# «₹25.2 L», «R$ 2,67 mi», «$2.58B». Без валюты «5 m» — это метры, поэтому
# они читаются только после знака или кода валюты. Одна строчная «m» — только
# вплотную к числу.
_PRICE_SCALES = {"m": 10**6, "mm": 10**6, "mn": 10**6, "mi": 10**6, "b": 10**9,
                 "cr": 10**7, "l": 10**5}
# «$50 B&B» и «$5 M-F» — не миллиарды и не миллионы.
_PRICE_SCALE_AFTER = re.compile(
    r"(?:" + _SP + r"?(?:((?i:mm|mn|mi|cr))|([MBL]))|(m))(?![\w&'’/\-]|\.\w)\.?")


def _price_scale_at(text: str, end: int) -> tuple:
    """Как `_scale_at`, но ещё и с множителями, которые пишут только при цене."""
    factor, length = _scale_at(text, end)
    if factor != 1:
        return factor, length
    match = _PRICE_SCALE_AFTER.match(text, end)
    if not match:
        return 1, 0
    word = (match.group(1) or match.group(2) or match.group(3)).lower()
    return _PRICE_SCALES[word], match.end() - end


# Подпись и название колонки повторяются на каждой странице: без кэша разбор
# одних и тех же пяти заголовков стоил семь секунд на десять тысяч страниц.
@lru_cache(maxsize=4096)
def _scale_in(unit: str, price: bool = False) -> tuple:
    """(слово, множитель) множителя внутри подписи единицы — или ("", 1).

    Слово множителя — целым словом: «k» в «kg» и «mil» в «miles» — не тысяча.
    С `price` — и множитель цены («$ M»), если в подписи есть валюта.
    """
    lowered = (unit or "").lower()
    for word, factor in sorted(SCALES.items(), key=lambda kv: -len(kv[0])):
        if word[0] in _CJK_SCALES:
            if word in lowered:
                return word, factor
        elif word in _GLUED_SCALES:
            if re.search(r"(?:^|(?<=[\s\d]))" + word, lowered):
                return word, factor
        elif re.search(r"(?<![^\W\d_])" + re.escape(word) + r"(?![^\W\d_])", lowered):
            return word, factor
    if price and _MONEY.search(unit or ""):
        for word in re.findall(r"[^\W\d_]+", unit or ""):
            if word.lower() in _PRICE_SCALES and (word.lower() != "l" or word == "L") \
                    and (len(word) > 1 or word in "MBLm"):
                return word.lower(), _PRICE_SCALES[word.lower()]
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
    "درصد|بالمائة|بالمئة|في\\s?المائة|في\\s?المئة|प्रतिशत|শতাংশ|فیصد|เปอร์เซ็นต์|אחוז(?:ים)?"
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
                  "PLN|SEK|NOK|DKK|HKD|NZD|ZAR|THB|IDR|MYR|PHP|VND|SAR|QAR|KZT|UAH|"
                  "CZK|HUF|BGN|EGP|PKR|KES|NGN|TWD|CLP")
# Коды, совпадающие со словами («ron» — ром, «ils» — «они», «cop»), — только
# заглавными.
_CASED_CODES = "RON|ILS|NIS|COP|ARS"
_ALL_CODES = frozenset((CURRENCY_CODES + "|" + _CASED_CODES).split("|"))
# Доллар с буквой страны и местные сокращения: `S$35`, `HK$200`, `R$ 90`,
# `RM 35`, `Rp 350.000`. Раньше такие цены не находились вовсе.
LOCAL_PREFIXES = (r"(?:US|S|A|AU|C|CA|HK|NZ|NT|R|MX|COL|CL)\$|RM|Rp\.?|Rs\.?|₱|₫|₩|₪|₺|₴|₸|৳|"
                  r"฿|₦|₵|₡|₲|₭|₮|﷼|kr\.?|Dhs\.?|KSh|SFr\.")
_LOCAL_PREFIX = re.compile(LOCAL_PREFIXES)
# Знак с пробелом — «$ 2,900», «€ 1.900» — та же цена: так пишут в нидерландской,
# немецкой и французской типографике. Но знак, перед которым стоит число
# («1.900 € 12 Monate»), — это валюта после числа, а не перед следующим.
# Иероглифы, кана и хангыль — буквы для `\w`, но пробелов в этих письменностях
# нет: «价格为$450。», «料金は¥9,900。» — знак валюты стоит вплотную к слову.
_CJK_LETTERS = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff"
PREFIX_PRICE = re.compile(
    r"(?:(?<![\w.,$])|(?<=[" + _CJK_LETTERS + r"]))((?:" + LOCAL_PREFIXES + r")[  \u00a0]?|[$€£¥₹₽฿](?=\d)|(?<!\d" + _SP + r")[$€£¥₹₽฿]" + _SP
    + r"|(?:" + CURRENCY_CODES + "|" + _CASED_CODES + r")[  \u00a0]?)(" + NUMBER + r")(?![\d])")

# Валюта после числа: `9.900 €`, `9,900 ₪`, `٩٩٠٠ دولار`, `3万円`. Раньше
# ценой считалась только валюта перед числом, и выдуманная цена на испанском,
# иврите или арабском уходила в «просмотри глазами» вместо критичной находки.
CURRENCY_SIGNS = "€£¥₹₽₪₩₫₺₴₸฿$₱₦₵₡₲₭₮৳﷼円元圓원"
CURRENCY_WORDS = (
    "dollars?|dolar|dólares|dollari|euros?|pounds?|rupees?|yen|yuan|baht|pesos?|reais|"
    "доллар(?:ов|а|ы)?|евро|фунт(?:ов|а)?|"
    "francs?|lira|lire|zł|złotych|kronor|kroner|kč|lei|"
    "руб(?:л[а-яё]*)?|грн|гривен[а-яё]*|гривн[а-яё]*|тенге|сум|сомов|лари|"
    "دولار[ًا]?|دولارات|يورو|ريال|ريالات|درهم|دراهم|دينار|جنيه|ليرة|تومان|ریال|"
    "שקל|שקלים|ש\"ח|"
    "रुपये|रुपया|रुपए|บาท|đồng|"
    "دلار|یورو|تومن|ڈالر|روپے|روپیہ|ডলার|টাকা|রুপি|डॉलर|डालर|यूरो|"
    "ดอลลาร์|ยูโร|דולר|דולרים|יורו|долар(?:ів|а|и)?|гривень|"
    "ringgit|rupiah|dong|riyals?|dirhams?|shekels?|rand|naira|TL|kr|лв|Dhs|KSh|ر\\.س|د\\.إ|"
    "us-dollars?|(?:abd[  \u00a0])?(?:doları|dolarları)|dolarów|dolary|dolarů|долл|đô[  \u00a0]la|"
    "米ドル|ドル|ユーロ|美元|美金|欧元|港元|新元|人民币|달러|유로|엔"
)
# Валютные слова CJK пишутся вплотную к следующему слову («35ドルです»), поэтому
# для них граница слова не нужна, в отличие от `dollar` в `dollars-and-sense`.
# Тайский тоже пишется без пробелов: «15 ล้านบาทต่อเดือน».
CJK_CURRENCY_WORDS = "米ドル|ドル|ユーロ|美元|美金|欧元|港元|新元|人民币|달러|유로|บาท|ดอลลาร์|ยูโร"
# «1.540,– €», «1508,-- €», «1510.-€», «18,000.- บาท», «2,50,000/- रुपये»:
# прочерк вместо копеек перед валютой.
_NO_CENTS = r"(?:[.,](?:--?|[–—])|/-)"
SUFFIX_PRICE = re.compile(
    NOT_INSIDE + r"(" + NUMBER + r")" + _NO_CENTS + r"?"
    # Слово-множитель — целым словом: «18945 kgbp» — не тысячи фунтов.
    r"(?:" + _SP + r"?(?:" + _CJK_SCALE + "|" + "|".join(_GLUED_SCALES) + r"|(?:" + _SCALE_WORDS + r")(?:\.|(?![^\W\d_]))"
    r"|(?-i:Cr|mn|mi)(?![^\W\d_]))|(?-i:MM|M|B)(?![^\W\d_]))?"
    + _SP + r"?(?:" + CJK_CURRENCY_WORDS + r"|[" + CURRENCY_SIGNS + r"]|(?:" + CURRENCY_WORDS
    + "|" + CURRENCY_CODES + "|(?-i:" + _CASED_CODES + r"))(?:(?![^\W\d_])|(?<=[a-zA-Z])(?=[" + _CJK_LETTERS + r"])))",
    re.I | re.U)


# Общее «число + слово»: ловит «12 лет», «25 тонн», «3500 заказов» —
# то, чего нет в списке единиц проекта, но что всё равно является фактом.
# Отрицательный просмотр назад отсекает «топ-10», «айфон-15», «ГОСТ-12»:
# число, приклеенное к слову дефисом, — часть названия, а не мера.
GENERIC_FACT = re.compile(
    r"(?<![^\W\d_]-)" + NOT_INSIDE + "(" + NUMBER + ")[  \\u00a0]?(м²|м2|km²|" + unit_word(14)
    + "|[%°$€£₽¥₹])", re.U)

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
    # Порядковые окончания: «the 20th of each month», «a 19th-century house».
    "st", "nd", "rd", "th",
    "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
    "сентября", "октября", "ноября", "декабря",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    # Порядковые суффиксы и время суток: «31st», «the 3rd deadline», «7 pm» —
    # не мера, а дата, номер и час.
    "st", "nd", "rd", "th", "pm",
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
               "seconds": ("sec", "secs"), "months": ("mo", "mos"),
               "years": ("yr", "yrs"), "weeks": ("wk", "wks"),
               "kilograms": ("kg", "kgs"), "kilometres": ("km", "kms")}
# И обратно: в таблице `34 min` и `3 mo`, в тексте — «44 minutes» и «5 months».
# Раньше короткая форма в данных не давала длинной, и выдумка уходила в
# «просмотри глазами».
_UNIT_LONG = {short: (long, long[:-1]) + shorts
              for long, shorts in _UNIT_SHORT.items() for short in shorts}
_UNIT_LONG["km"] += ("kilometers", "kilometer")
_UNIT_LONG["kms"] += ("kilometers", "kilometer")
_UNIT_SHORT["kilometers"] = _UNIT_SHORT["kilometres"]

# Формы одной единицы, которые после числа значат одно и то же: падежи и
# число в русском, немецком, испанском, итальянском, португальском, японские
# написания месяца и площадь. Только слова, которые после числа не бывают ничем
# другим: «год» и «an» сюда не входят — «в 2026 году», «$5 an hour».
_UNIT_FAMILIES = (
    {"месяц", "месяца", "месяцев"}, {"минута", "минуты", "минут", "минуту"},
    {"час", "часа", "часов"}, {"день", "дня", "дней"},
    {"неделя", "недели", "недель", "неделю"},
    {"monat", "monate", "monaten", "monats"}, {"minute", "minuten"},
    {"stunde", "stunden"}, {"woche", "wochen"}, {"jahr", "jahre", "jahren"},
    {"mes", "meses"}, {"minuto", "minutos", "minuti"}, {"semana", "semanas"},
    {"año", "años"}, {"día", "días"}, {"mese", "mesi"},
    {"giorno", "giorni"}, {"mês", "meses"}, {"dia", "dias"}, {"ano", "anos"},
    {"ヶ月", "か月", "カ月", "ヵ月", "ケ月"}, {"个月", "個月"},
    {"m²", "m2", "sqm", "sq m", "square metres", "square meters", "square metre", "square meter"},
    {"м²", "м2", "кв. м", "кв.м", "кв м"},
)


def _unit_forms(units: list) -> list:
    """Единицы проекта вместе с единственным числом и сокращениями: months → month."""
    out = set()
    for unit in units or ():
        unit = _same_signs(unit or "").strip()
        if not unit:
            continue
        out.add(unit)
        lowered = unit.lower()
        # «days» → «day», «beds» → «bed»: «a 9-day wait», «a 5-bed house».
        if re.fullmatch(r"[a-z]{3,}s", lowered) and not lowered.endswith(("ss", "us", "is")):
            out.add(unit[:-1])
        # Другие формы того же слова: в данных «3 месяца», на странице —
        # «5 месяцев» и «1 месяц»; в данных «3ヶ月», на странице «5か月».
        for family in _UNIT_FAMILIES:
            if lowered in family or (_CJK_CHAR.search(lowered)
                                     and any(lowered.startswith(f) for f in family)):
                out.update(family)
        out.update(_UNIT_SHORT.get(lowered, ()))
        out.update(_UNIT_SHORT.get(lowered + "s", ()))
        out.update(_UNIT_LONG.get(lowered, ()))
    return sorted(out, key=len, reverse=True)


# Иероглифы, кана и хангыль: в этих письменностях нет пробелов, и за единицей
# сразу идёт следующее слово — «44分です», «5ヶ月分», «34분입니다».
_CJK_CHAR = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]")


def build_fact_pattern(units: list):
    """Собирает выражение «число + единица» под единицы конкретного проекта."""
    units = _unit_forms(units)
    if not units:
        return None
    # Граница слова после единицы — только для письменностей с пробелами. Для
    # «分» и «ヶ月» она не выполнялась почти никогда: «44分です» уходило в
    # «просмотри глазами», хотя «44分。» было критичной находкой.
    spaced = [re.escape(u) for u in units if not _CJK_CHAR.search(u)]
    glued = [re.escape(u) for u in units if _CJK_CHAR.search(u)]
    alternatives = "|".join(
        # «45kmです», «45min到达»: за латинской единицей вплотную идёт CJK.
        (["(?:" + "|".join(spaced) + r")(?![^\W\d_" + _CJK_LETTERS + r"])"] if spaced else [])
        + (["(?:" + "|".join(glued) + ")"] if glued else []))
    # Через дефис — составное прилагательное: «a 4-month deposit», «a 44-minute
    # ride». Раньше такое число не читалось вовсе. «5 min read» — подпись блога.
    return re.compile(NOT_INSIDE + r"(" + NUMBER + r")(?:[  \u00a0]|[" + _HYPHEN_SIGNS + r"])?(?:"
                      + alternatives + r")(?!" + _SP + r"read\b)", re.I | re.U)


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


# «1億2000万円», «3억 2천만원» — тоже одно число: 120000000 и 320000000.
_CJK_OKU = re.compile(r"(?<![\d.,])(\d{1,4})([億亿]|억" + _SP + r"?)(\d{1,4})(千[万萬]|천만|[万萬]|만)"
                      r"(?![\d.,]?\d)")


def _cjk_compounds(text: str) -> str:
    def oku(match):
        scale = 10**7 if match.group(4)[0] in "千천" else 10**4
        tail = int(match.group(3)) * scale
        if tail >= 10**8:
            return match.group(0)
        return str(int(match.group(1)) * 10**8 + tail)

    text = _CJK_OKU.sub(oku, text or "")

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
            unit = match.group(0)[len(match.group(1)):].strip(" -\u2010\u2011\u00a0\u202f")
            # Единица данных — сам множитель («15 लाख», «8,5 juta»): число — с ним.
            word, factor = _scale_in(unit)
            number = _scaled(match.group(1), factor if word and word == unit.lower() else 1)
            if number:
                found[number] = unit
                for earlier in _listed_before(text, match.start(1)):
                    found.setdefault(earlier, found[number])
    for match in PREFIX_PRICE.finditer(text or ""):
        sign = match.group(1).strip()
        factor, length = _price_scale_at(text, match.end())
        # «$1,600–2,400», «$950 to 1,900»: второй край — та же валюта, а
        # множитель в конце («$1.5–2 million») относится к обоим краям.
        second = _RANGE_SECOND.match(text, match.end() + length)
        # Голое «2026» после цены — обычно год («from $1,450 – 2026 guide»), но
        # «$1450-2000 a month» — диапазон цен: за ним идёт срок оплаты.
        if second and re.fullmatch(r"\d{4}", second.group(1)) \
                and (_year_like(second.group(1)) or sign == "฿" and 2400 <= int(second.group(1)) <= 2700) \
                and not _PER_PERIOD.match(text, second.end()):
            second = None
        # «$1,450 – 1600 Oak Avenue»: за голым числом — имя собственное, это
        # номер дома, а не второй край цены.
        if second and re.fullmatch(r"\d+", second.group(1)) \
                and _NAME_AFTER.match(text, second.end()) \
                and not _SUFFIX_AFTER.match(text, second.end()):
            second = None
        if second:
            more, more_length = _price_scale_at(text, second.end())
            more_scale = text[second.end():second.end() + more_length].strip().rstrip(".")
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
                scale = text[match.end():match.end() + length].strip().rstrip(".")
            elif factor == 1:
                scale = ""
            found.setdefault(number, (sign + " " + scale).strip())
    for match in SUFFIX_PRICE.finditer(text or ""):
        factor, _ = _price_scale_at(text, match.end(1))
        number = _scaled(match.group(1), factor)
        if number:
            unit = re.sub(r"^" + _NO_CENTS, "", match.group(0)[len(match.group(1)):]).strip()
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
_LIST_AND = (r"(?:" + _SP + r"+(?:and|or|и|или|و|یا|und|oder|et|ou|y|o|e|dan|atau|và|hoặc|และ|"
             r"หรือ|ve|veya|और|या|এবং|ও|та|або|ו)" + _SP + r"+"
             # Арабское «و» пишется слитно со следующим словом («و١٤٩»),
             # ивритское «ו» — через макаф или дефис («ו-149»).
             r"|" + _SP + r"+(?:و|ו[\-\u05be]?))")
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


# Срок оплаты после цены: «a month», «per night», «/mo», «в месяц».
_PER_PERIOD = re.compile(
    _SP + r"*(?:(?:a|an|per|each|every|в|за)" + _SP + r"+|/" + _SP + r"?)"
    r"(?:(?:months?|mo|years?|yr|weeks?|wk|nights?|days?|person)(?![^\W\d_])"
    r"|(?:месяц|мес|год|недел|ноч|сут|день|дн)[а-яё]*)"
    r"|" + _SP + r"*(?:monthly|yearly|annually|weekly|nightly|ежемесячно)(?![^\W\d_])", re.I)
# Слово с заглавной после числа — имя: «1600 Oak Avenue», «2000 Main St».
_NAME_AFTER = re.compile(_SP + r"+[A-ZА-ЯЁ][a-zа-яё]+")
# Но валюта и множитель с заглавной — продолжение цены: «2000 Euro», «2 Million».
_SUFFIX_AFTER = re.compile(
    _SP + r"*(?:(?:" + CURRENCY_WORDS + "|" + _SCALE_WORDS + r")(?![^\W\d_])|"
    r"(?:Per|A|Each)" + _SP + r")", re.I)


def _ascending(low: str, high: str) -> bool:
    try:
        return float(low) < float(high)
    except (TypeError, ValueError):
        return False


def _year_like(number: str) -> bool:
    return number.isdigit() and 1900 <= int(number) <= 2100


# Год буддийской эры — «ปี 2569», «พ.ศ. 2569», «2569 BE» — тоже год, но только
# с подписью эры: голое 2569 бывает и ценой.
_BE_BEFORE = re.compile(r"(?:ปี|พ\.\s?ศ\.)" + _SP + r"*$")
_BE_AFTER = re.compile(_SP + r"*(?:B\.\s?E\.|BE(?![^\W\d_]))")


def _year_at(text: str, start: int, end: int, number: str) -> bool:
    """Год ли число на этом месте: обычный или буддийской эры с подписью."""
    if _year_like(number):
        return True
    return (number.isdigit() and 2400 <= int(number) <= 2700
            and bool(_BE_BEFORE.search(text, max(0, start - 12), start)
                     or _BE_AFTER.match(text, end)))


def _listed_before(text: str, start: int) -> list:
    """Числа перечисления прямо перед числом с единицей — без своей единицы."""
    match = _RANGE_FIRST.search(text, max(0, start - 40), start)
    if match:
        number = _norm_number(match.group(1))
        last = re.match(NUMBER, text[start:])
        if number and not _year_at(text, match.start(1), match.end(1), number) \
                and last and _ascending(number, _norm_number(last.group(0))):
            return [number]
        return []
    out, end, pattern = [], start, _LIST_LAST
    while len(out) < MAX_LISTED:
        match = pattern.search(text, max(0, end - 40), end)
        if not match:
            break
        number = _norm_number(match.group(1))
        if not number:
            break
        # Год в начале перечисления — не его член: «In 2026, 15 or 20 minutes».
        # Посреди перечисления — член: «$1,450, 1950 or 2100 dollars».
        if _year_at(text, match.start(1), match.end(1), number) \
                and not _LIST_MORE.search(text, max(0, match.start() - 40), match.start()):
            break
        out.append(number)
        end, pattern = match.start(), _LIST_MORE
    return out


# Только после оценки: «4.6 out of 5», «4,6 из 5», «4.6/5». «A deposit of 10
# weeks» и «Kaution von 5 Monaten» — не шкала, и число не должно пропадать.
_SCALE = re.compile(r"(\d(?:\s+(?!out\b)[^\W\d_]{1,12})?)(?:\s*\b(?:out\s+of|of|из|von|sur|su|de|na)\s+|\s?/\s?)"
                    r"(?:5|10|100)\b(?!\s?%)", re.I)


# Дата «2026年11月18日», «11월 18일» — не два количества: «November 18»
# второй эшелон тоже не читает (месяцы — в `NON_UNITS`).
_CJK_DATE = re.compile(r"(?<![\d.,])(?:\d{4}" + _SP + r"?[年년]" + _SP + r"?)?(\d{1,2})" + _SP
                       + r"?[月월]" + _SP + r"?(\d{1,2})" + _SP + r"?[日일]")


def _without_cjk_dates(text: str) -> str:
    def blank(match):
        if 1 <= int(match.group(1)) <= 12 and 1 <= int(match.group(2)) <= 31:
            return " "
        return match.group(0)
    return _CJK_DATE.sub(blank, text)


def _generic_numbers_in(text: str) -> dict:
    """«Число + любое слово» — второй эшелон: слабее сигнал, но покрывает всё."""
    found = {}
    # Верх шкалы — «4.6 out of 5», «4,6 из 5», «4.6/5» — постоянная, а не
    # факт строки: на каталоге это давало `check-by-eye` на 164 страницах из 202.
    text = _without_cjk_dates(_SCALE.sub(r"\1 ", _cjk_compounds(_same_signs(text))))
    for match in GENERIC_FACT.finditer(text):
        unit = match.group(2).strip().lower()
        if unit in NON_UNITS or unit.isdigit():
            continue
        # «$2.54M», «2.68M USD»: множитель цены — часть цены первого эшелона.
        if unit in _PRICE_SCALES and (
                _MONEY.search(text[max(0, match.start(1) - 4):match.start(1)])
                or _MONEY.match(text[match.end():match.end() + 6].lstrip(_SP[1:-1]))):
            continue
        factor, _ = _scale_at(text, match.end(1))
        number = _scaled(match.group(1), factor)
        if not number:
            continue
        # Год в тексте — не факт строки: «в 2026 году», «с 1998 г.» Годом
        # считается только голое четырёхзначное число: `1,900` с разделителем
        # разрядов — это тысяча девятьсот чего-то, а не год.
        if re.fullmatch(r"\d{4}", match.group(1)) and _year_at(
                text, match.start(1), match.end(1), number):
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


# Дата и адрес в ячейке — не набор фактов. Колонка «проверено 2026-11-18» или
# источник `https://data.example/2026/11/18/` давали строке числа 11 и 18, а
# одна дата на все строки делала их постоянными сайта: любая страница могла
# написать «залог 11 месяцев» или «18 минут до центра». Числа даты годятся
# только для даты на странице — «11月18日», см. `_date_parts`.
_URL_IN_CELL = re.compile(r"(?<![\w])[a-z][a-z0-9+.\-]*://\S+", re.I)
_TIME_TAIL = r"(?:[T ]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+\-]\d{2}:?\d{2})?)?"
_DATE_IN_CELL = re.compile(
    r"(?<![\d.,\-])(?:(?P<y>\d{4})(?P<s>[\-/.])(?P<m>\d{1,2})(?P=s)(?P<d>\d{1,2})"
    r"|(?P<a>\d{1,2})(?P<t>[\-/.])(?P<b>\d{1,2})(?P=t)(?P<year>\d{4}))" + _TIME_TAIL + r"(?![\d.,]?\d)")


def _dates_in(text: str) -> list:
    """[(начало, конец, (год, месяц, день))] — даты ячейки, в которых не ошибиться."""
    out = []
    for match in _DATE_IN_CELL.finditer(text):
        year = match.group("y") or match.group("year")
        first, second = ((match.group("m"), match.group("d")) if match.group("y")
                         else (match.group("a"), match.group("b")))
        if not 1900 <= int(year) <= 2100:
            continue
        first, second = int(first), int(second)
        if not (1 <= first <= 31 and 1 <= second <= 31 and min(first, second) <= 12):
            continue
        out.append((match.start(), match.end(), (year, str(first), str(second))))
    # Дата словами — «18 Nov 2026», «November 18, 2026» — и короткая —
    # «2026-11», «11/2026», «18/11/26». Раньше её день и год становились числами
    # строки, а одна дата на все строки — постоянными сайта: «залог 18 месяцев»
    # и «$2026» проходили молча.
    for match in _NAMED_DATE_IN_CELL.finditer(text):
        if any(s <= match.start() < e for s, e, _ in out):
            continue
        month = _MONTH_NUMBER.get((match.group("nm") or match.group("mm"))[:3].lower(), "")
        day = match.group("nd") or match.group("md")
        year = match.group("ny") or match.group("my")
        if month and 1 <= int(day) <= 31:
            out.append((match.start(), match.end(), (year, month, str(int(day)))))
    for match in _SHORT_DATE_IN_CELL.finditer(text):
        if any(s <= match.start() < e for s, e, _ in out):
            continue
        if match.group("ym"):
            year, month, rest = match.group("ym"), match.group("mo"), ()
        elif match.group("my2"):
            year, month, rest = match.group("my2"), match.group("mo2"), ()
        else:
            first, second = int(match.group("p")), int(match.group("q"))
            if not (1 <= first <= 31 and 1 <= second <= 31 and min(first, second) <= 12):
                continue
            year, month, rest = "20" + match.group("yy"), str(min(first, second)), (str(max(first, second)),)
        if 1900 <= int(year) <= 2100 and 1 <= int(month) <= 12:
            out.append((match.start(), match.end(), (year, str(int(month))) + rest))
    return sorted(out)


_MONTH_NUMBER = {m: str(i) for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_MONTH_NAME = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
               r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_NAMED_DATE_IN_CELL = re.compile(
    r"(?<![\w.,])(?:(?P<nd>\d{1,2})(?:st|nd|rd|th)?" + _SP + r"+(?P<nm>" + _MONTH_NAME + r")\.?,?"
    + _SP + r"+(?P<ny>\d{4})|(?P<mm>" + _MONTH_NAME + r")\.?" + _SP + r"+(?P<md>\d{1,2})"
    r"(?:st|nd|rd|th)?,?" + _SP + r"+(?P<my>\d{4}))(?![\w.,]?\d)", re.I)
_SHORT_DATE_IN_CELL = re.compile(
    r"(?<![\w.,\-/:])(?:(?P<ym>\d{4})[\-/](?P<mo>\d{1,2})|(?P<mo2>\d{1,2})/(?P<my2>\d{4})"
    r"|(?P<p>\d{1,2})(?P<t>[/.])(?P<q>\d{1,2})(?P=t)(?P<yy>\d{2}))(?![\w.,\-/:]?\d)")
# Время дня в ячейке — «8:30», «9:00-18:00» — не количество минут или часов.
_CLOCK_IN_CELL = re.compile(
    r"(?<![\w.,:])(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:" + _SP + r"?(?:[ap]\.?m\.?)(?!\w))?(?![\w.,:]?\d)",
    re.I)


def _without_dates(text: str) -> str:
    text = _URL_IN_CELL.sub(" ", text)
    text = _CLOCK_IN_CELL.sub(" ", text)
    for start, end, _ in reversed(_dates_in(text)):
        text = text[:start] + " " + text[end:]
    return text


def _date_parts(row: dict) -> set:
    """Год, месяц и день из дат строки — для даты на странице, а не для фактов."""
    out = set()
    for value in (row or {}).values():
        for _, _, parts in _dates_in(_same_signs(str(value))):
            out.update(parts)
    return out


# Иероглиф или кана перед числом — граница слова, а не артикул: «徒歩5分»,
# «押金3个月», «月租4500元» пишут без пробела. Латиница перед числом («A90») —
# по-прежнему артикул.
_CJK_BEFORE_DIGIT = re.compile(r"([\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff])(?=\d)")


def _numbers_of(value) -> list:
    """Числа из одного значения строки — кроме тех, что сидят в артикуле."""
    text, out = _CJK_BEFORE_DIGIT.sub(r"\1 ", _without_dates(str(value))), []
    for match in _GLUED_UNIT.finditer(text):
        out.append(match.group(1))
    for match in ROW_NUMBER.finditer(text):
        chain = (_CHAIN_BACK.search(text[:match.start()]).group(0)
                 + _CHAIN.match(text, match.end()).group(0))
        if re.search(r"[^\W\d_]", chain):
            continue
        out.append(match.group(1))
    return out


@lru_cache(maxsize=4096)
def _column_scale(column) -> int:
    """Множитель из названия колонки — «цена, млн», `price_k` — или 1."""
    words = re.sub(r"[_\W]+", " ", str(column or "")).strip()
    word, factor = _scale_in(words)
    # Колонка, названная одним множителем (`k`), — это ключ, а не тысячи.
    if not word or words.lower() == word:
        return 1
    return factor


# «Free» в ячейке цены — это ноль: «Entry is $0» на такой странице верно.
_FREE = re.compile(r"free|gratis|gratuit[eo]?|gratuita|kostenlos|бесплатно|безкоштовно", re.I)


def _row_numbers(row: dict) -> set:
    out = set()
    for column, value in (row or {}).items():
        text = _same_signs(str(value))
        if _FREE.fullmatch(text.strip()):
            out.add("0")
        # Колонка в тысячах или миллионах — «цена, млн», `price_k`, «价格(万元)»:
        # её число значит и само себя, и себя с множителем. Раньше множитель
        # со страницы снимался с любого числа строки, и «$34k» при «34 minutes»
        # проходило молча.
        header = _column_scale(column)
        for raw in _numbers_of(text):
            number = _norm_number(raw)
            if number:
                out.add(number)
                if header != 1:
                    out.add(_scaled(raw, header))
        # «3万» или «1,5 млн» в самих данных: и как есть, и в единицах. Своё
        # выражение: обычное отбрасывает число, приклеенное к знаку (артикул),
        # а CJK-множитель — тоже знак.
        text = _without_dates(text)
        for match in _SCALED_NUMBER.finditer(text):
            factor, _ = _scale_at(text, match.end(1))
            if factor != 1:
                out.add(_norm_number(match.group(1)))
                out.add(_scaled(match.group(1), factor))
        # «$2.54M», «₹2.5 Cr» в ячейке: множитель цены читается при валюте.
        for number, unit in _numbers_in(text, None).items():
            if _scale_in(unit, price=True)[0]:
                out.add(number)
    return out


def _site_constants(rows: list, share: float = 0.5) -> set:
    return set().union(*_site_constant_columns(rows, share).values())


def _site_constant_columns(rows: list, share: float = 0.5) -> dict:
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
        return {}
    # Считаются не отдельные числа, а набор чисел ячейки: «3-5 days» во всех
    # строках — это постоянные 3 и 5 вместе. Постоянной колонку делает одно
    # значение, которое встречается чаще других. Если два значения делят колонку
    # поровну — «2 months» в половине строк и «3 months» в другой, — это не
    # постоянная, а данные строки: раньше прощались оба, и страница с чужим
    # сроком залога проходила молча.
    per_column = defaultdict(Counter)
    for row in rows:
        for column, value in (row or {}).items():
            # Телефон и адрес на каждой строке — не постоянные: «2000» из
            # «+1 555 010 2000» и «400» из «Suite 400» прощали выдуманные цены.
            if _is_identifier(column, value):
                continue
            numbers = frozenset(n for n in (_norm_number(raw) for raw in _numbers_of(value)) if n)
            if numbers:
                per_column[column][numbers] += 1
    threshold = max(2, int(len(rows) * share))
    out = {}
    for column, counter in per_column.items():
        top = counter.most_common(2)
        if top[0][1] < threshold:
            continue
        # Второе значение, которое встречается не единично, — тоже данные
        # строки: при залоге «3 месяца» в пяти городах из восьми и «2 месяца» в
        # трёх тройка становилась постоянной, и город с двумя месяцами молча
        # получал чужие три. Редкое исключение (одно на пятерых и реже)
        # постоянную не отменяет.
        if len(top) > 1 and top[1][1] >= 2 and top[1][1] * 4 >= top[0][1]:
            continue
        # Исключения, каждое из которых единично, — тоже данные строки, если их
        # больше одного на пятерых: «3 months» в четырёх строках из восьми и
        # 1, 2, 4, 5 в остальных делали тройку постоянной.
        if (sum(counter.values()) - top[0][1]) * 4 > top[0][1]:
            continue
        out[column] = top[0][0]
    return out


# Телефон, адрес, индекс — номер, а не величина: его числа не меряются ничем.
_ID_COLUMN = re.compile(
    r"(?<![^\W\d_])(?:phones?|tel|telephone|mobile|fax|whatsapp|address|addr|street|zip|zipcode|"
    r"postcode|postal|телефон|тел|адрес|улица|индекс)(?![^\W\d_])", re.I)
_PHONE_CELL = re.compile(r"\+?\(?\d[\d \u00a0().\-]{5,}\d")
_ADDRESS_CELL = re.compile(
    r"(?<![^\W\d_])(?:street|avenue|ave|road|suite|blvd|boulevard|lane|floor|"
    r"улица|ул|проспект|офис)(?![^\W\d_])", re.I)


def _is_identifier(column, value) -> bool:
    """Колонка телефона или адреса — или ячейка, похожая на телефон."""
    if _ID_COLUMN.search(re.sub(r"[_\W]+", " ", str(column or ""))):
        return True
    text = _same_signs(str(value or "")).strip()
    if _ADDRESS_CELL.search(text):
        return True
    if not _PHONE_CELL.fullmatch(text) or re.fullmatch(NUMBER, text) or _dates_in(text):
        return False
    return (sum(c.isdigit() for c in text) >= 7
            and (text[0] in "+(" or len(re.findall(r"\d+", text)) >= 3))


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
    from urllib.parse import unquote, urlsplit
    text = (value or "").strip()
    if "://" in text:
        text = urlsplit(text).path
    # `k%C3%B6ln` из выгрузки краулера и `köln` в NFD из macOS — тот же адрес.
    text = unicodedata.normalize("NFC", unquote(text))
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
    by_path, by_last, last_clash, path_clash = {}, {}, set(), set()
    if slug_field:
        for row in rows:
            full, last = _path_forms(row.get(slug_field) or "")
            if not last:
                continue
            # Один адрес у двух строк — та же неоднозначность, что два одинаковых
            # ключа: раньше молча побеждала первая строка.
            if full in by_path and by_path[full] is not row:
                path_clash.add(full)
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
    # Ключ, проставленный шаблоном на всех страницах, — не связь: `<meta
    # name="keyword" content="berlin">` на странице мюнхена сверял её с
    # берлином, и чужие числа на ней проходили молча.
    key_pages = Counter((page.meta.get("keyword") or "").strip().lower() for page in pages)
    slug_bound = defaultdict(list)
    for page in pages:
        key = (page.meta.get("keyword") or "").strip().lower()
        row = by_keyword.get(key) if key else None
        if row is None or key_pages[key] > 1:
            slug_row, clash = None, False
            if slug_field:
                rel = os.path.relpath(page.path, root).replace(os.sep, "/")
                full, last = _path_forms(rel)
                if full in path_clash or (full not in by_path and last in last_clash):
                    clash = True
                else:
                    slug_row = by_path.get(full) or by_last.get(last)
            if slug_row is None and not clash:
                # Папка `Berlin`, `köln`, `аренда-берлин` — тот же ключ, что
                # `berlin`, `koln`, `arenda-berlin`.
                slug = _slug_of(page, root)
                if slug not in by_slug and slug not in slug_clash:
                    slug = slugify(unicodedata.normalize("NFC", slug))
                clash = slug in slug_clash
                slug_row = None if clash else by_slug.get(slug)
            if row is None:
                if clash:
                    ambiguous.append(page.url)
                    continue
                row = slug_row
                if row is not None:
                    slug_bound[id(row)].append(page)
            elif slug_row is not None and slug_row is not row:
                row = slug_row
                slug_bound[id(row)].append(page)
        if row is not None:
            matched[page.url] = row
            claimed.add(id(row))
        else:
            pending.append(page)

    # Одна строка по последнему сегменту у страниц из разных разделов —
    # `/rent/berlin/` и `/buy/berlin/`: строка принадлежит разделу, в котором
    # лежат остальные страницы датасета. Без перевеса неизвестно, чья она.
    def parent(page):
        rel = os.path.relpath(page.path, root).replace(os.sep, "/")
        return _path_forms(rel)[0].rpartition("/")[0]
    sections = Counter(parent(page) for group in slug_bound.values() for page in group)
    for group in slug_bound.values():
        if len(group) < 2:
            continue
        best = max(sections[parent(page)] for page in group)
        winners = [page for page in group if sections[parent(page)] == best]
        for page in group:
            if len(winners) > 1 or page is not winners[0]:
                matched.pop(page.url, None)
                if len(winners) > 1:
                    ambiguous.append(page.url)
    free = sorted(k for k, r in by_keyword.items() if id(r) not in claimed)
    # Основы слов ключей считаются один раз, а не для каждой страницы, и
    # кандидатами берутся только ключи с общим словом: при пороге выше нуля
    # остальные всё равно не проходят. Иначе 4 тысячи страниц шли полторы минуты.
    free_stems = [(k, _stems(k)) for k in free]
    free_stems = [(k, t) for k, t in free_stems if t]
    key_slugs = {k: set(re.findall(r"[a-z]+", slugify(k))) for k, _ in free_stems}
    by_length = {}
    for candidate_key, tokens in free_stems:
        postings = by_length.setdefault(len(tokens), {})
        for token in tokens:
            postings.setdefault(token, []).append(candidate_key)

    for page in pending:
        row = None
        haystack = " ".join([page.title] + [t for _, t in page.headings[:2]]).lower()
        # Ключи из Вордстата в именительном падеже, заголовки — в предложном.
        # Без нормализации словоформ сопоставлялось 10 страниц из 100,
        # и сверка фактов молча выключалась на девяти десятых сайта.
        haystack_tokens = _stems(haystack)
        # Страница, которая называет в заголовке свой адрес, — о нём, а не о
        # ключе: `/rent/potsdam/` с заголовком «Renting in Potsdam near Berlin»
        # сверялась со строкой berlin, и её верные числа становились выдумкой.
        own_slug = slugify(_slug_of(page, root))
        own_slug = set() if own_slug.startswith("p-") else (
            {t for t in re.findall(r"[a-z]+", own_slug) if len(t) > 2}
            & set(re.findall(r"[a-z]+", slugify(haystack, max_len=10 ** 6))))

        def fits(candidate_key):
            return not own_slug or bool(own_slug & key_slugs[candidate_key])

        if cfg["match_min_score"] > 0:
            # Совпадения считаются по спискам ключей с общим словом, отдельно
            # для каждой длины ключа: доля — совпавшие слова / длина.
            best = None
            for length, postings in by_length.items():
                counts = Counter()
                for token in haystack_tokens:
                    counts.update(k for k in postings.get(token, ()) if fits(k))
                if not counts:
                    continue
                top = max(counts.values())
                if best is None or top * best[1] > best[0] * length \
                        or (top * best[1] == best[0] * length and length > best[1]):
                    best = (top, length, counts)
            if best is not None and best[0] / best[1] >= cfg["match_min_score"]:
                values = list(best[2].values())
                if values.count(best[0]) > 1:
                    ambiguous.append(page.url)
                else:
                    row = by_keyword[list(best[2])[values.index(best[0])]]
            if row is not None:
                matched[page.url] = row
            continue
        scored = []
        for candidate_key, key_tokens in free_stems:
            if not fits(candidate_key):
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
    word, factor = _scale_in(unit, price=True)
    if word:
        try:
            raw = _norm_number(repr(round(float(number) / factor, 6)))
        except ValueError:
            raw = ""
        if raw:
            glue = "" if (word[0] in _CJK_SCALES or word in _GLUED_SCALES) \
                and lowered.startswith(word) else " "
            parts = unit.split()
            code = parts[0].upper() in _ALL_CODES
            if unit and (unit[0] in "$€£¥₹₽" or _LOCAL_PREFIX.fullmatch(parts[0]) or code):
                rest = " ".join(parts[1:])
                sign = parts[0] + (" " if code else "")
                # «$1.6k» — множитель в одну букву пишут вплотную.
                if len(rest) == 1:
                    return f"{sign}{raw}{rest}"
                return f"{sign}{raw} {rest}".strip()
            return f"{raw}{glue}{unit}".strip()
    if unit and unit in "$€£¥₹₽":
        return f"{unit}{number}"
    if unit and _LOCAL_PREFIX.fullmatch(unit):
        return f"{unit}{number}" if unit.endswith("$") or len(unit) == 1 else f"{unit} {number}"
    if unit and unit.upper() in _ALL_CODES:
        return f"{unit} {number}"
    return f"{number} {unit}".strip()


# Чем меряется число — по подписи, в которой не ошибиться. Остальные подписи
# мерой не считаются, и число с ними сверяется как раньше, без единицы.
_MEASURES = (
    # Секунды, ночи и десятилетия — тоже мера: без неё «34 seconds» и «2 nights»
    # прощались за «34 minutes» и «2 months».
    ("second", r"secs?|seconds?|секунд[аы]?|сек|sekunden?|secondes?|segundos?|secondi|秒|秒間|초"),
    ("night", r"nights?|ноч[ьи]|ночей|nächte|nacht|nuits?|noches?|nott[ei]|泊|박"),
    ("decade", r"decades?|десятилети[еяй]|jahrzehnte?n?|décennies?|décadas?|decenni?o?"),
    ("minute", r"min|mins|minutes?|минут[аы]?|мин|minuten?|minutos?|minuti|分|分間|分钟|分鐘|분"),
    ("hour", r"hrs?|hours?|час|часа|часов|stunden?|heures?|horas?|ore|ora|時間|小时|小時|시간"),
    ("day", r"days?|день|дня|дней|суток|tage?n?|tag|jours?|d[ií]as?|giorn[oi]|日|日間|天|일"),
    ("week", r"weeks?|недел[яиьюе]|недель|wochen?|semaines?|semanas?|settiman[ae]|週|週間|周|주"),
    ("month", r"mos?|months?|месяц|месяца|месяцев|мес|monate?n?|monat|mois|mes|meses|mesi|mese|"
              r"mês|ヶ月|か月|カ月|ヵ月|ケ月|个月|個月|개월"),
    ("year", r"yrs?|years?|год|года|лет|jahre?n?|jahr|ans?|années?|años?|ann[oi]|anos?|年|년"),
    # Расстояние, площадь и вес: «34 km» при `34 minutes` в строке — тоже
    # перестановка полей шаблона.
    ("km", r"km|kms|kilomet(?:er|re)s?|км|километр(?:а|ов)?|kilómetros?|kilometri"),
    ("m2", r"m²|m2|sqm|sq\.?" + _SP + r"?m|square" + _SP + r"+met(?:er|re)s?|м²|м2|кв\.?" + _SP + r"?м|㎡|平米"),
    ("kg", r"kgs?|kilos?|kilogram(?:me)?s?|кг|килограмм(?:а|ов)?"),
)
# Хинди, бенгали, тайский, индонезийский, арабский, персидский, урду, иврит:
# без них «залог 34 মাস» при «34 মিনিট» в строке проходило молча.
_MEASURES_MORE = {
    "minute": r"मिनट|মিনিট|นาที|menit|دقيقة|دقائق|دقیقه|منٹ|דקות|דקה",
    "hour": r"घंटे|घंटा|ঘণ্টা|ชั่วโมง|jam|ساعة|ساعات|ساعت|گھنٹے|שעות|שעה",
    "day": r"दिन|দিন|วัน|hari|يوم|أيام|روز|دن|ימים|יום",
    "week": r"सप्ताह|हफ्ते|সপ্তাহ|สัปดาห์|minggu|أسبوع|أسابيع|هفته|ہفتے|שבועות|שבוע",
    "month": r"महीने|महीना|माह|মাস|เดือน|bulan|شهر|أشهر|شهور|ماه|مہینے|חודשים|חודש",
    # «ปี», «वर्ष», «tahun», «سال» стоят и перед годом («฿1,450 ปี 2569»):
    # мерой они сделали бы цену сроком. Только счётные формы.
    "year": r"বছর|سنوات|שנים",
}
_MEASURES = tuple((name, words + "|" + _MEASURES_MORE[name] if name in _MEASURES_MORE else words)
                  for name, words in _MEASURES)
_MEASURE = [(name, re.compile(r"(?:" + words + r")\.?", re.I)) for name, words in _MEASURES]


def _measure(unit: str) -> str:
    """`money`, `%`, мера времени — или пусто, если подпись ничего не говорит."""
    text = _same_signs(str(unit or "")).strip(" -\u2010\u2011")
    if not text:
        return ""
    if _MONEY.search(text):
        return "money"
    if "%" in text or PERCENT_WORD.search("1 " + text):
        return "%"
    for name, pattern in _MEASURE:
        if pattern.fullmatch(text):
            return name
    return ""


# Единица в названии колонки: `rent_usd`, `deposit_months`, `commute_minutes`.
# Срок — только во множественном числе последним словом: `price_per_month` и
# `rent_monthly` — цена за месяц, а не число месяцев.
_COLUMN_MONEY = re.compile(r"(?<![^\W\d_])(?:" + CURRENCY_WORDS + "|" + CURRENCY_CODES
                           + r")(?![^\W\d_])|[$€£¥₹₽₪₩₫₺₴₸฿₱₦]", re.I)
_COLUMN_TERMS = {"minutes", "mins", "hours", "hrs", "days", "weeks", "months", "years", "yrs",
                 "минут", "часов", "дней", "суток", "недель", "месяцев", "лет"}


def _column_unit(column) -> str:
    """Единица из названия колонки — или пусто."""
    words = re.sub(r"[_\W]+", " ", str(column or "")).strip().lower().split()
    if not words:
        return ""
    if _COLUMN_MONEY.search(" ".join(words)):
        return "$"
    if words[-1] in _COLUMN_TERMS and (len(words) < 2 or words[-2] not in ("per", "a", "each")):
        return words[-1]
    return ""


def _row_measures(row: dict, fact_pattern) -> dict:
    """
    {число строки: меры, которыми оно записано}. Пустая мера — число записано
    голым или с непонятной подписью: тогда оно годится для любой. Голое число
    берёт меру из названия колонки, число телефона или адреса — меру `id`,
    которая не подходит ни к цене, ни к сроку.
    """
    out = defaultdict(set)
    for column, value in (row or {}).items():
        text = _same_signs(str(value))
        strong = _numbers_in(text, fact_pattern)
        scaled = _column_scale(column) != 1
        # Единица только в названии колонки — `deposit_months: 3`, `rent_usd`:
        # голое число меряется ею. Номер телефона или адреса — мерой `id`,
        # которая не подходит ни к цене, ни к сроку.
        ident = _is_identifier(column, value)
        named = "" if ident else (_column_unit(column) or column_unit(column))
        for raw in _numbers_of(text):
            number = _norm_number(raw)
            if number:
                unit = strong.get(number, "")
                if scaled:
                    out[number].add("")
                    continue
                if ident and not unit:
                    out[number].add("id")
                    continue
                measure = _measure(unit) or _measure(named)
                out[number].add(measure)
                if measure == "money":
                    # Валюта числа: «€1,296» при `$1,296` — не та же цена.
                    out[number].add("cur:" + _currency(unit))
    return out


# Единица времени в конце названия колонки: `deposit_months`, `commute_min`.
# «price_per_month» — цена за месяц, а не месяцы, и сюда не подходит.
_COLUMN_UNIT = re.compile(
    r"(?<![^\W_])(?<!per_)(?<!per )(minutes|mins|hours|hrs|days|weeks|months|years|yrs)$", re.I)


def column_unit(column) -> str:
    """Единица из названия колонки — `deposit_months` → `months` — или пусто."""
    match = _COLUMN_UNIT.search(str(column or "").strip())
    return match.group(1).lower() if match else ""


# Валюты, которые пишут одним знаком или словом: «$» — и доллар США, и
# канадский, и песо; «£» — и фунт, и египетский фунт. Внутри одной семьи
# валюта не сверяется: различаются только явно разные — доллар и евро.
_CURRENCY_FAMILIES = (
    {"USD", "CAD", "AUD", "NZD", "SGD", "HKD", "TWD", "MXN", "COP", "CLP", "ARS", "BRL", "PHP"},
    {"JPY", "CNY"}, {"GBP", "EGP"}, {"INR", "PKR", "LKR", "NPR"},
    {"KR", "SEK", "NOK", "DKK", "ISK"}, {"RON", "MDL"},
    {"DINAR", "KWD", "BHD", "JOD", "IQD", "LYD", "TND", "DZD", "RSD"},
    {"SAR", "QAR", "OMR", "IRR", "YER"}, {"TRY", "LBP", "SYP"}, {"AED", "MAD"},
)


def _currency(unit: str) -> str:
    """Код валюты подписи цены — `USD`, `EUR` — или пусто, если её не прочесть."""
    from .facts import _kind
    code = _kind(unit)
    return code if code != "%" else ""


def _same_currency(one: str, other: str) -> bool:
    if one == other:
        return True
    return any(one in family and other in family for family in _CURRENCY_FAMILIES)


def _bare_numbers(row: dict) -> set:
    """Числа строки, записанные в ячейке голыми, без единицы: `12.5`, `1450`."""
    out = set()
    for value in (row or {}).values():
        text = _same_signs(str(value)).strip()
        if re.fullmatch(NUMBER, text):
            number = _norm_number(text)
            if number:
                out.add(number)
    return out


def _supported(number: str, unit: str, allowed: set, measures: dict = None,
               bare: set = None) -> bool:
    """
    Есть ли число в данных — как есть или до множителя, если до множителя оно
    стоит в строке голым: «12,5 млн» при `price: 12.5`. Число с собственной
    единицей множителя не получает: раньше «$3k» прощалось за «3 месяца»,
    «$34k» — за «34 минуты», а «$1,450k» — за «$1,450». Колонка, в названии
    которой стоит множитель («цена, млн»), учтена в `_row_numbers`.

    С `measures` число должно стоять в строке той же мерой, что на странице:
    «залог 34 месяца» при «34 минутах» и «$34» при «34 минутах» — перестановка
    полей шаблона, а не данные. Число, которое в строке записано голым или с
    непонятной подписью, годится для любой меры.
    """
    if number not in allowed:
        word, factor = _scale_in(unit)
        if word and bare:
            try:
                raw = _norm_number(repr(round(float(number) / factor, 6)))
            except ValueError:
                return False
            return raw in bare
        return False
    if not measures or number not in measures:
        return True
    wanted = _measure(unit)
    if not wanted:
        return True
    have = measures[number]
    if "" in have:
        return True
    if wanted == "money" and wanted in have:
        page = _currency(unit)
        codes = {h[4:] for h in have if h.startswith("cur:")}
        if page and codes and "" not in codes \
                and not any(_same_currency(page, code) for code in codes):
            return False
    return wanted in have


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
    # Сокращения из букв — целым словом: «rs» в «hours» и «rm» в «rms» — не
    # рупии и не ринггиты, иначе срок в часах считался ценой.
    r"(?<![^\W\d_])(?:" + LOCAL_PREFIXES + r")(?![^\W\d_])|[" + CURRENCY_SIGNS + r"]|"
    + CJK_CURRENCY_WORDS + r"|"
    r"(?<![^\W\d_])(?:" + CURRENCY_WORDS + "|" + CURRENCY_CODES + "|(?-i:" + _CASED_CODES
    + r"))(?![^\W\d_])", re.I | re.U)
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
        # «discount: $15» — деньги, а не процент: знак ячейки сильнее колонки.
        kind = _kind(value)
        if kind != "money" and _PERCENT_COLUMN.search(str(column or "")):
            kind = "%"
        # Единица в названии колонки — `rent_usd`, `deposit_months`: так хранят
        # JSON и выгрузки. Без неё $4,350 = 3 × 1450 было критичной находкой,
        # а то же с единицами в ячейках — подсказкой «просмотри глазами».
        # Любое последнее слово единицей не было: `rent_monthly` давало «mont».
        if not kind:
            kind = _kind(_column_unit(column))
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
        priced = any(k == "money" for k in kinds.values())
        for one, other in ((ra, rb), (rb, ra)):
            # Цена на цену — не итог: «$362,500 = $250 × $1,450».
            if kind == "money" and of(one) == "money" and of(other) != "money":
                return True
            # Цена в строке голая (`rent: 1450`), срок — со своей единицей.
            if kind == "money" and not priced and of(one) == "" and of(other) not in ("", "%"):
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


# Число даты на странице: «11月18日», «2026年». Только эти подписи берут
# поддержку из даты строки.
_DATE_UNIT = re.compile(r"[年月日년월일]")


_HOURS_MINUTES = re.compile(
    r"(?<![\w.,])(\d{1,2})" + _SP + r"?(?:hours?|hrs?|h|час(?:а|ов)?|ч)\.?,?" + _SP + r"*(?:and" + _SP
    + r"+|и" + _SP + r"+)?(\d{1,2})" + _SP + r"?(?:minutes?|mins?|минут[аы]?|мин)(?!\w)", re.I)


def _descending_before(text: str, fact_pattern) -> dict:
    """Первые края обратных диапазонов перед числом с единицей проекта."""
    found = {}
    if not fact_pattern:
        return found
    text = _cjk_compounds(_same_signs(text))
    for match in fact_pattern.finditer(text):
        first = _RANGE_FIRST.search(text, max(0, match.start(1) - 40), match.start(1))
        if not first:
            continue
        number = _norm_number(first.group(1))
        if number and not _year_like(number) \
                and not _ascending(number, _norm_number(match.group(1))):
            found.setdefault(number, match.group(0)[len(match.group(1)):]
                             .strip(" -\u2010\u2011\u00a0\u202f"))
    return found


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
    constant_columns = _site_constant_columns(rows)
    # Мера постоянной — та, которой она записана в своей колонке: «3 months»
    # на всех строках не поддерживает «3 minutes», а «$250» — «250 months».
    constant_measures = defaultdict(set)
    for other in rows or ():
        for column, numbers in constant_columns.items():
            if (other or {}).get(column) is None:
                continue
            for number, have in _row_measures({column: other[column]}, fact_pattern).items():
                if number in numbers:
                    constant_measures[number] |= have

    issues = []
    for page in sorted(pages, key=lambda p: p.url):
        row = matched.get(page.url)
        if row is None:
            continue
        # Постоянная не прощает строку, у которой в той же колонке своё
        # значение: «$500» на странице при `fee: $700` — устаревший шаблон.
        constants = set()
        for column, numbers in constant_columns.items():
            own = {n for n in (_norm_number(raw) for raw in _numbers_of(row.get(column) or "")) if n}
            if not own or own == numbers:
                constants |= numbers
        own = _row_numbers(row)
        allowed = own | constants
        # Постоянные сайта сверяются своей мерой — вместе с мерой строки:
        # срок гарантии «12 months» законно стоит и рядом с «12 minutes».
        measures = _row_measures(row, fact_pattern)
        for number in constants:
            measures[number] = measures.get(number, set()) | (constant_measures.get(number) or {""})
        dates = _date_parts(row) - allowed
        bare = _bare_numbers(row)
        # Голое число до множителя прощается, только если цены в строке нет
        # другой: при `price: $1,200,000` «$3k» не берётся из `beds: 3`, а
        # «$4.5M» — из `rating: 4.5`.
        if any(_MONEY.search(str(v)) and re.search(r"\d", str(v)) for v in row.values()):
            bare = set()

        # «1 hour 30 minutes» при `90 minutes`: обе части верны вместе.
        compound = set()
        for match in _HOURS_MINUTES.finditer(_same_signs(_with_head(page))):
            total = _norm_number(str(int(match.group(1)) * 60 + int(match.group(2))))
            if _supported(total, "minutes", allowed, measures, bare):
                compound |= {(_norm_number(match.group(1)), "hour"),
                             (_norm_number(match.group(2)), "minute")}

        def supported(number, unit):
            if (number, _measure(unit)) in compound:
                return True
            if number in dates:
                # «15日です»: после 日 идёт слово, а не другая единица.
                return bool(_DATE_UNIT.fullmatch((unit or "").strip()[:1])) \
                    and not re.search(r"[^\u3040-\u309f]", (unit or "").strip()[1:])
            return _supported(number, unit, allowed, measures, bare)

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

        unknown_strong = {n: u for n, u in strong.items() if not supported(n, u)}
        kinds = _row_kinds(row)
        derived = {n: how for n, u in unknown_strong.items()
                   for how in [_derivation(n, own, kinds, _kind(u))] if how}
        for number in derived:
            weak[number] = unknown_strong.pop(number)
        # Обратный диапазон — «50 to 34 minutes» — не диапазон, но и не повод
        # молчать о числе: раньше оно пропадало из обоих эшелонов.
        for number, unit in _descending_before(text, fact_pattern).items():
            weak.setdefault(number, unit)
        unknown_weak = {n: u for n, u in weak.items()
                        if not supported(n, u) and n not in unknown_strong}

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
    # Крошки и подпись автора — не начало текста. Крошка обычно кончается
    # тем же H1, и начало искалось с названия города; подпись «By the
    # Editorial Team» одинакова у всех статей блога.
    service = [w for w in (tokenize(t) for t in getattr(page, "service", None) or ()) if w]
    if service:
        kept, at, window = [], 0, words[:400]
        while at < len(window):
            for block in service:
                if window[at:at + len(block)] == block:
                    at += len(block)
                    break
            else:
                kept.append(window[at])
                at += 1
        words = kept + words[len(window):]
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


def _inflected(word: str, slots: set) -> bool:
    """
    Слово — другая форма значения из H1: «Москва» в H1 и «в Москве» в
    подзаголовках, «Уфа» и «в Уфе». Отличаться может только окончание: у
    короткого из двух слов — последняя буква, у длинного — до трёх.
    """
    if len(word) < 3 or word.isdigit():
        return False
    for slot in slots:
        if len(slot) < 3 or slot.isdigit():
            continue
        n = len(os.path.commonprefix([word, slot]))
        if (n >= 2 and n >= min(len(word), len(slot)) - 1
                and n >= max(len(word), len(slot)) - 3):
            return True
    return False


def _slot_skeletons(pages: list, skip: set) -> dict:
    """Скелеты заголовков, где слова-подстановки из H1 заменены меткой."""
    h1_words = {}
    df = Counter()
    for page in pages:
        heads = page.headings or []
        h1 = next((t for level, t in heads if level == 1), "")
        # Число — тоже значение подстановки: индекс 90210, «District 3».
        own = {w.lower() for w in tokenize(h1) if len(w) >= 2 or w.isdigit()}
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
            kept = [SLOT_MARK if w in slots or _inflected(w, slots) else w
                    for w in tokens]
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


SECTION_SEAM_MIN = 5
# Доля раздела, с которой скелет считается одним из его шаблонов.
TEMPLATE_PART = 0.3


_SLUG_TOKEN = re.compile(r"[-_.]+")
_SLUG_DEPTH = 8


def _section_counter(pages: list, counted=None):
    """
    Сколько страниц под общим каталогом группы. Порог шаблонности, взятый от
    всего сайта, гас, стоило рядом появиться блогу: двадцать одинаковых
    городских страниц среди семидесяти статей — 22% сайта, но 100% раздела.

    У плоских адресов (`/rent-alpha/`, `/rent-beta/`) общего каталога нет:
    раздел тогда — общее начало адреса (`rent-`) у страниц одного уровня.

    Счёт по готовым таблицам: раньше на каждую группу перебирался весь сайт,
    и на 30 000 страниц с разным началом текста это стоило две минуты.
    """
    paths = {p.url: [x for x in urlsplit(p.url).path.split("/") if x] for p in pages}
    under = Counter()
    by_slug = Counter()
    for p in pages:
        if counted is not None and not counted(p):
            continue
        x = paths[p.url]
        for i in range(1, len(x) + 1):
            under[tuple(x[:i])] += 1
        if x:
            parent = tuple(x[:-1])
            tokens = [t for t in _SLUG_TOKEN.split(x[-1].lower()) if t]
            for i in range(1, min(len(tokens), _SLUG_DEPTH) + 1):
                by_slug[(parent, tuple(tokens[:i]))] += 1

    def slug_section(parts):
        # Только страницы одного уровня с одним родителем: иначе общее
        # начало адреса ничего не значит.
        parents = {tuple(x[:-1]) for x in parts}
        if len(parents) != 1 or not all(parts):
            return 0, ""
        parent = parents.pop()
        slugs = [[t for t in _SLUG_TOKEN.split(x[-1].lower()) if t] for x in parts]
        common = []
        for column in zip(*[t[:_SLUG_DEPTH] for t in slugs]):
            if len(set(column)) != 1:
                break
            common.append(column[0])
        # Начало, равное целому адресу одной из страниц, — не раздел.
        if not common or any(len(t) == len(common) for t in slugs):
            return 0, ""
        size = by_slug[(parent, tuple(common))]
        return size, "/" + "".join(x + "/" for x in parent) + "-".join(common) + "-"

    def section_size(urls):
        parts = [paths[u] for u in urls if u in paths]
        if not parts:
            return 0, ""
        prefix = []
        for column in zip(*[x[:-1] for x in parts]):
            if len(set(column)) != 1:
                break
            prefix.append(column[0])
        if not prefix:
            return slug_section(parts)
        return under[tuple(prefix)], "/" + "/".join(prefix) + "/"
    return section_size


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
    in_section = _section_counter(
        pages, lambda p: sum(1 for level, _ in p.headings if level >= 2) >= 2)

    # Два шаблона в одном каталоге: тридцать страниц аренды и тридцать
    # услуг под /rent/ — у каждого скелета половина раздела, и порог в 70%
    # не брал ни один. Скелеты, каждый из которых занимает заметную долю
    # раздела, складываются: вместе они и есть раздел. Только скелеты из
    # трёх заголовков и больше: «Введение, Итоги» бывают у любых статей.
    covered = Counter()

    def cover(groups):
        for skeleton, urls in groups:
            if len(skeleton) >= 3 and len(urls) >= SECTION_SEAM_MIN:
                size, prefix = in_section(urls)
                if size and len(urls) >= size * TEMPLATE_PART:
                    covered[prefix] += len(urls)

    def stamped_here(urls, skeleton=()):
        if len(urls) >= threshold:
            return True
        if len(urls) < SECTION_SEAM_MIN:
            return False
        size, prefix = in_section(urls)
        if size < cfg["min_pages_for_seams"]:
            return False
        return (len(urls) >= size * cfg["template_share"]
                or (len(skeleton) >= 3 and len(urls) >= size * TEMPLATE_PART
                    and covered[prefix] >= size * cfg["template_share"]))

    cover(skeletons.items())

    stamped_groups = []
    for skeleton, urls in sorted(skeletons.items()):
        if stamped_here(urls, skeleton):
            repeated.append({"headings": list(skeleton), "count": len(urls)})
            stamped.update(urls)
            stamped_groups.append((skeleton, urls))
            for url in sorted(urls):
                issues.append((
                    "warning", url, "template-skeleton",
                    tr("те же {a0} заголовков в том же порядке ещё у {a1} страниц", a0=len(skeleton), a1=len(urls) - 1)))

    # «Сколько стоит в Alpha», «Где искать в Alpha»: подставленное значение
    # стоит и в подзаголовках, и скелеты по точному тексту не совпадали ни у
    # одной пары. Слово из H1, которое есть меньше чем у половины страниц, —
    # значение подстановки; оно заменяется меткой, и скелеты сравниваются
    # ещё раз. Только для страниц, которых точное сравнение не нашло.
    slotted = _slot_skeletons(pages, stamped)
    # Страница не должна попасть в сумму дважды: раз точным скелетом, раз —
    # с меткой подстановки.
    covered.clear()
    cover(stamped_groups)
    cover(slotted.items())
    for skeleton, urls in sorted(slotted.items()):
        if stamped_here(urls, skeleton):
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
    opening_section = _section_counter(pages)

    def same_start(urls):
        if len(urls) >= max(3, int(len(pages) * 0.3)):
            return True
        if len(urls) < SECTION_SEAM_MIN:
            return False
        size, _ = opening_section(urls)
        return size >= cfg["min_pages_for_seams"] and len(urls) >= size * 0.3

    for opening, urls in sorted(openings.items()):
        if same_start(urls):
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
    if "<pre" not in raw and "<code" not in raw:
        return False
    raw = drop_spans(raw, NOT_SHOWN)
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
            if not mojibake:
                # title и description видны в выдаче, а visible_text их не видит.
                mojibake += [s for k, s in find_slots(value, markdown=True) if k == "mojibake"]
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
                           Said(tr("незаполненные места шаблона: {a0}", a0=shown),
                                (f"«{s}»" for s in critical or empty))))
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
        # Строка без ключа называется номером: раньше она шла пустой строкой.
        "rows_without_page": sorted(
            str(r.get(keyword_field) or "").strip() or f"#{n}"
            for matched_ids in [{id(v) for v in matched.values()}]
            for n, r in enumerate(rows or [], 1) if id(r) not in matched_ids),
    }
