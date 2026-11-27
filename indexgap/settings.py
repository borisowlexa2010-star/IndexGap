# -*- coding: utf-8 -*-
"""
Настройки проекта. В коде остаётся механика, всё, что зависит от ниши,
языка и рынка, живёт здесь и в файле `indexgap.json` рядом со страницами.

Три уровня, каждый следующий перекрывает предыдущий:

  1. значения по умолчанию в модулях (`checks.CONFIG`, `content.CONFIG`, …);
  2. `indexgap.json` в корне проекта;
  3. то, что выведено из самих данных проекта — единицы измерения,
     язык, характерная длина страницы.

Третий уровень важнее, чем кажется. Один и тот же инструмент используют
для виз, недвижимости, юруслуг и каталога станков. Зашивать в код список
валют и слово «дней» — значит сделать его пригодным ровно для одной ниши.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections import Counter
from .core import SourceError
from .i18n import tr

CONFIG_NAMES = ("indexgap.json", ".indexgap.json")

# Дефолты, общие для всего пакета. Модульные CONFIG остаются на своих местах,
# сюда попадает только то, что действительно зависит от проекта.
PROJECT_DEFAULTS = {
    # Единицы, по которым число в тексте считается фактом, а не нумерацией.
    # Пустой список означает «вывести из датасета» — это почти всегда лучше,
    # чем угадывать: в датасете уже лежат ровно те единицы, которыми
    # оперирует этот бизнес.
    "fact_units": [],
    # Дополнительные единицы поверх выведенных — если чего-то в данных нет,
    # а в тексте оно встречается (например «шт.» или «м²»).
    "extra_fact_units": [],
    # Анкоры, которые не несут смысла. Дефолт покрывает русский и английский;
    # для другого языка список задаётся здесь.
    "vague_anchors": [
        "здесь", "тут", "подробнее", "читать", "читать далее", "ссылка", "страница",
        "перейти", "смотреть", "далее",
        "here", "there", "read more", "link", "click here", "more", "this page",
        "learn more", "see more", "details",
    ],
    # Язык влияет на то, как считается объём текста. auto — определить самому.
    "language": "auto",
}

# Языки без пробелов между словами: объём считается в символах, а не в словах.
SCRIPTLESS = {"zh", "ja", "th", "km", "lo", "my"}

# Письменности, где знак несёт примерно столько же, сколько слово, и пробелов
# между словами нет: китайская, японская (кана и кандзи), корейская, тайская,
# кхмерская, лаосская, бирманская.
DENSE_SCRIPT = re.compile(
    "[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\uac00-\ud7af\u0e00-\u0e7f\u1780-\u17ff\u0e80-\u0eff\u1000-\u109f]")

# Письменности, где знак вдвое шире латинского: иероглифы, кана, хангыль.
_WIDE_SCRIPT = re.compile(
    "[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]")

# Сколько символов такого языка примерно соответствует одному «слову»
# в языках с пробелами. Грубо, но лучше, чем считать всю страницу
# за одно слово и объявлять её тонкой.
CHARS_PER_WORD = 2.0


# Насколько высоко над страницами искать конфиг, который назвал их своими:
# `.next/server/app` — три уровня от корня проекта.
_CONFIG_DEPTH = 6


def _pages_of(path: str) -> str:
    """Каталог страниц, записанный в конфиге (`pages`), — абсолютным путём."""
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    pages = data.get("pages")
    if not isinstance(pages, str):
        pages = data.get("content") if isinstance(data.get("content"), str) else ""
    if not pages:
        return ""
    return os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(path)), pages))


def find_config(root: str) -> str:
    """
    Ищет конфиг рядом со страницами, затем на уровень выше.

    Выше этого берётся только конфиг, чей `pages` указывает ровно на эти
    страницы: `indexgap init` в проекте на Next.js пишет
    `"pages": "./.next/server/app"`, и такой конфиг лежит тремя уровнями выше.
    Чужой indexgap.json где-то над каталогом не подхватывается.
    """
    here = os.path.abspath(root)
    for directory in (here, os.path.dirname(here)):
        for name in CONFIG_NAMES:
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                return path
    target = os.path.realpath(here)
    directory = os.path.dirname(here)
    for _ in range(_CONFIG_DEPTH):
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
        for name in CONFIG_NAMES:
            path = os.path.join(directory, name)
            if os.path.isfile(path) and _pages_of(path) == target:
                return path
    return ""


def load_config(root: str = ".", explicit: str = "") -> dict:
    """Читает конфиг проекта. Отсутствие файла — норма, не ошибка."""
    path = explicit or find_config(root)
    config = dict(PROJECT_DEFAULTS)
    if not path:
        return config
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            user = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        # SourceError, а не SystemExit: её ловит и команда, и портфель. Битый
        # конфиг одного проекта обрывал прогон всех остальных.
        raise SourceError(tr("Не удалось прочитать {a0}: {a1}", a0=path, a1=exc))
    if not isinstance(user, dict):
        raise SourceError(tr("{a0}: ожидался объект верхнего уровня.", a0=path))
    # Строка вместо списка (`"fact_units": "minutes"`) разбиралась по буквам:
    # единицами становились «m», «i», «n»…, и сверка фактов молча выключалась.
    for key in ("fact_units", "extra_fact_units", "vague_anchors"):
        value = user.get(key)
        if value is not None and not (isinstance(value, list)
                                      and all(isinstance(v, str) for v in value)):
            raise SourceError(tr("{a0}: значение `{a1}` должно быть списком строк, а там {a2}.",
                                 a0=path, a1=key, a2=json.dumps(value, ensure_ascii=False)[:40]))
    # `null` — «как по умолчанию»: проверка выше его пропускает, и пустое
    # значение затирало список по умолчанию, роняя прогон трассировкой.
    config.update({k: v for k, v in user.items()
                   if not (v is None and k in PROJECT_DEFAULTS)})
    config["_path"] = path
    config["_user_keys"] = sorted(user)
    return config


# ── вывод настроек из данных проекта ──────────────────────────────────────────

# Единица — это то, что стоит сразу после числа: буквы, символ валюты,
# м², %, °C. Намеренно широко: список валют и мер мира в код не помещается
# и устаревает, а в данных проекта нужное уже есть.
UNIT_AFTER_NUMBER = re.compile(
    "\\d[\\d\\s.,]*\\s*([^\\W\\d_]{1,12}|[%°$€£₽¥₹]|м²|м2|km²)",
    re.U)


# Слова, которые стоят после числа, но единицей не являются. Без этого списка
# из описательной колонки вылезали «года», «до», «кв», «ч», и пакет требовал
# объяснить время работы офиса.
NOT_A_UNIT = {
    "и", "или", "а", "но", "в", "во", "на", "по", "из", "с", "со", "до", "от",
    "за", "к", "ко", "о", "об", "при", "для", "же", "ли", "не", "ни", "то",
    "это", "как", "что", "год", "года", "году", "годов", "г", "гг", "стр",
    "and", "or", "the", "a", "an", "of", "in", "on", "at", "to", "for", "by",
    "is", "are", "no", "am", "pm",
    # Порядковые окончания: колонка этажей «4th», «5th» не делает «19th-century»
    # фактом.
    "st", "nd", "rd", "th", "er", "ème", "º", "ª",
}


def units_from_dataset(rows: list, keyword_field: str = None, min_count: int = 2) -> list:
    """
    Достаёт единицы измерения из значений датасета.

    Если в колонке `fee` лежит «30 SGD», а в `area` — «120 м²», то фактами
    для этого проекта являются SGD и м², и никакой настройки не требуется.

    Единица должна встретиться не в одной строке: единичное совпадение —
    это почти всегда кусок описания, а не мера.
    """
    counter = Counter()
    for row in rows or ():
        for field, value in (row or {}).items():
            if keyword_field and field == keyword_field:
                continue
            for match in UNIT_AFTER_NUMBER.finditer(str(value)):
                unit = match.group(1).strip().lower()
                if unit and not unit.isdigit() and unit not in NOT_A_UNIT:
                    counter[unit] += 1
            # Единица только в названии колонки: `deposit_months: 3`.
            if re.fullmatch(r"\s*\d+(?:[.,]\d+)?\s*", str(value)):
                from .content import column_unit
                unit = column_unit(field)
                if unit:
                    counter[unit] += 1
    return [unit for unit, count in counter.most_common() if count >= min_count]


def detect_language(pages: list) -> str:
    """Язык берётся из разметки страниц; при разнобое — самый частый."""
    langs = Counter()
    for page in pages or ():
        code = (page.lang or "").strip().lower()
        if code:
            langs[code.split("-")[0]] += 1
    return langs.most_common(1)[0][0] if langs else ""


def text_volume(page, language: str = "") -> int:
    """
    Объём текста в единицах, сопоставимых между языками.

    Меряется по письменности, а не по объявленному языку, и складывается:
    слова с пробелами считаются словами, иероглифы — по `CHARS_PER_WORD`.
    Так работает и чистый китайский, и чистый английский, и — главное —
    смесь, которой мультиязычные сайты полны: у живого китайского каталога
    виз в заголовках 43% иероглифов, остальное латиница (бренд, «Form B14»,
    «arrival card»). Делить такую строку на два — вдвое занизить латиницу.

    Почему не по языку страницы: язык может быть не объявлен, объявлен неверно
    или объявлен один на десять языковых версий. Письменность видна всегда.

    Цена прежнего подхода измерена: язык проекта определялся как `en` по
    большинству и перебивал язык каждой страницы. Все 289 китайских страниц
    считались по-английски — 201 «слово» вместо 654, и все 174 находки `thin`
    на сайте оказались ложными. Все 174 были китайскими.
    """
    text = page.text or ""
    if not text:
        return 0
    dense = DENSE_SCRIPT.findall(text)
    if dense:
        rest = DENSE_SCRIPT.sub(" ", text)
        words = len(re.findall(r"\w+", rest, flags=re.UNICODE))
        return words + int(len(dense) / CHARS_PER_WORD)
    words = page.word_count
    if words <= 3:
        # Письменность без пробелов, которую мы не распознали как плотную:
        # лучше грубая оценка, чем «страница из двух слов».
        chars = len(re.sub(r"\s+", "", text))
        if chars > 40:
            return int(chars / CHARS_PER_WORD)
    return words


def display_width(text: str) -> int:
    """
    Ширина строки в «латинских» знаках: иероглиф занимает примерно два.

    Длины title и description — это про то, сколько влезет в выдачу, а влезает
    ширина, а не число символов. Один порог, посчитанный по ширине, работает
    для латиницы, иероглифики и смеси разом; отдельный множитель «для CJK»
    на смешанной строке ошибался в обе стороны.
    """
    if not text:
        return 0
    # Широки только иероглифы, кана и хангыль. Тайское, лаосское, кхмерское и
    # бирманское письмо — обычной ширины, а их надстрочные гласные и тоны
    # (и любые комбинируемые знаки) места в строке не занимают: тайский
    # заголовок из 35 видимых знаков считался шириной 90.
    wide = len(_WIDE_SCRIPT.findall(text))
    marks = sum(1 for ch in text if unicodedata.category(ch) in ("Mn", "Me", "Cf"))
    return len(text) + wide - marks


def resolve(root: str, pages: list = None, rows: list = None,
            keyword_field: str = None, explicit: str = "") -> dict:
    """Собирает итоговые настройки: файл проекта плюс выведенное из данных."""
    config = load_config(root, explicit)

    units = list(config.get("fact_units") or [])
    derived = []
    if not units and rows:
        derived = units_from_dataset(rows, keyword_field)
        units = derived
    units += list(config.get("extra_fact_units") or [])
    config["fact_units"] = sorted({u.lower() for u in units if u})
    config["_derived_units"] = derived

    language = config.get("language") or "auto"
    if language == "auto":
        language = detect_language(pages) or ""
    config["language"] = language

    return config


# ── проверка того, что вписано руками ─────────────────────────────────────────

# Поля верхнего уровня, которые кто-то читает. Опечатка в имени раздела
# (`chekcs`, `profil`) раньше тихо не действовала: пороги и профиль
# оставались по умолчанию, и в отчёте об этом не было ни слова.
KNOWN_KEYS = ("profile", "site", "pages", "dataset", "home", "checks", "content", "aeo",
              "freshness", "ignore", "cite", "fact_units", "extra_fact_units",
              "vague_anchors", "language")

# Пороги-доли в разделах; остальные пороги — счёт (не меньше 1). У каждой
# пары: можно ли ноль.
_SHARES = {"template_share": False, "match_min_score": False,
           "question_share": True, "min_dated_share": True}
_ZERO_OK = {"min_anchor_chars", "grace_days"}


def _section_defaults(section: str) -> dict:
    if section == "content":
        from .content import CONFIG
    elif section == "aeo":
        from .aeo import CONFIG
    else:
        from .freshness import CONFIG
    return CONFIG


def check_section(section: str, values) -> list:
    """
    Пороги разделов `content`, `aeo` и `freshness` — так же, как `checks`.

    `template_share: 70` вместо `0.7` молча убирало все находки о скелете
    шаблона, а число строкой роняло прогон трассировкой. Возвращает заметки
    о незнакомых ключах; на невозможное значение отвечает ошибкой со словами.
    """
    import difflib
    if values is None:
        return []
    if not isinstance(values, dict):
        raise SourceError(
            tr("В настройках проекта раздел `{a0}` должен быть объектом с порогами, а не {a1}.\n    Путь к страницам записывается полем `pages`, не `content` — поправь indexgap.json.", a0=section, a1=type(values).__name__))
    defaults = _section_defaults(section)
    notes = []
    for key, value in values.items():
        if key.startswith("_"):
            continue
        name = f"{section}.{key}"
        if key not in defaults:
            close = difflib.get_close_matches(key, list(defaults), n=1, cutoff=0.7)
            notes.append(tr("настройка «{a0}» мне не знакома и не действует", a0=name)
                         + (tr(" — возможно, имелось в виду «{a0}»", a0=close[0]) if close else ""))
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SourceError(tr("настройка «{a0}» должна быть числом, а в конфиге стоит {a1}",
                                 a0=name, a1=json.dumps(value, ensure_ascii=False)))
        if key in _SHARES:
            low_ok = _SHARES[key]
            if not ((0 <= value if low_ok else 0 < value) and value <= 1):
                raise SourceError(tr("настройка «{a0}» = {a1}: {a2}", a0=name, a1=value,
                                     a2=tr("нужна доля от 0 до 1 — например 0.8, а не 80")))
        elif value < (0 if key in _ZERO_OK else 1):
            raise SourceError(tr("настройка «{a0}» = {a1}: {a2}", a0=name, a1=value,
                                 a2=tr("нужно целое число не меньше 1") if key not in _ZERO_OK
                                 else tr("нужно число не меньше 0")))
    if section == "aeo":
        merged = {**defaults, **{k: v for k, v in values.items() if k in defaults}}
        if merged["answer_min"] >= merged["answer_max"]:
            raise SourceError(tr("настройка «{a0}» = {a1}: {a2}", a0="aeo.answer_max",
                                 a1=merged["answer_max"],
                                 a2=tr("верхняя граница должна быть больше нижней")))
    return notes


def unknown_keys(config: dict) -> list:
    """Заметки о полях верхнего уровня, которых пакет не читает."""
    import difflib
    notes = []
    for key in sorted(config.get("_user_keys") or ()):
        if key.startswith("_") or key in KNOWN_KEYS:
            continue
        close = difflib.get_close_matches(key, list(KNOWN_KEYS), n=1, cutoff=0.7)
        notes.append(tr("поле «{a0}» в indexgap.json мне не знакомо и не действует", a0=key)
                     + (tr(" — возможно, имелось в виду «{a0}»", a0=close[0]) if close else ""))
    return notes
