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
from collections import Counter

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

# Сколько символов такого языка примерно соответствует одному «слову»
# в языках с пробелами. Грубо, но лучше, чем считать всю страницу
# за одно слово и объявлять её тонкой.
CHARS_PER_WORD = 2.0


def find_config(root: str) -> str:
    """Ищет конфиг рядом со страницами, затем на уровень выше."""
    candidates = []
    for directory in (root, os.path.dirname(os.path.abspath(root))):
        for name in CONFIG_NAMES:
            candidates.append(os.path.join(directory, name))
    for path in candidates:
        if os.path.isfile(path):
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
        raise SystemExit(f"Не удалось прочитать {path}: {exc}")
    if not isinstance(user, dict):
        raise SystemExit(f"{path}: ожидался объект верхнего уровня.")
    config.update(user)
    config["_path"] = path
    return config


# ── вывод настроек из данных проекта ──────────────────────────────────────────

# Единица — это то, что стоит сразу после числа: буквы, символ валюты,
# м², %, °C. Намеренно широко: список валют и мер мира в код не помещается
# и устаревает, а в данных проекта нужное уже есть.
UNIT_AFTER_NUMBER = re.compile(
    r"\d[\d\s.,]*\s*([^\W\d_]{1,12}|[%°$€£₽¥₹]|м²|м2|km²)",
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

    Для японского, китайского, тайского и подобных пробелов между словами нет,
    и обычный подсчёт даёт единицы вместо сотен — страница ошибочно
    объявляется тонкой.
    """
    code = (language or page.lang or "").split("-")[0].lower()
    if code in SCRIPTLESS:
        chars = len(re.sub(r"\s+", "", page.text or ""))
        return int(chars / CHARS_PER_WORD)
    words = page.word_count
    if words <= 3 and page.text:
        # язык не объявлен, но пробелов почти нет — считаем как иероглифический
        chars = len(re.sub(r"\s+", "", page.text))
        if chars > 40:
            return int(chars / CHARS_PER_WORD)
    return words


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
