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
NUMBER = (r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,3}(?:\.\d{3})+(?:,\d+)?|"
          r"\d{1,3}(?:[  \u00a0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")

# Число не начинается с середины другого: перед ним не цифра и не разделитель.
NOT_INSIDE = r"(?<![\d.,])"

PERCENT = re.compile(NOT_INSIDE + r"(" + NUMBER + r")\s*%")

# Цена, записанная по-английски: валюта перед числом. Такие числа не искались
# вовсе, и единственная настоящая выдумка на странице — `$95` при `$60`
# в данных — была единственным, о чём проверка молчала.
CURRENCY_CODES = ("USD|EUR|GBP|JPY|CNY|INR|AUD|CAD|CHF|SGD|AED|RUB|BRL|MXN|KRW|TRY|"
                  "PLN|SEK|NOK|DKK|HKD|NZD|ZAR|THB|IDR|MYR|PHP|VND|SAR|QAR|KZT|UAH")
PREFIX_PRICE = re.compile(
    r"(?<![\w.,])([$€£¥₹₽]|(?:" + CURRENCY_CODES + r")[  \u00a0]?)(" + NUMBER + r")(?![\d])")

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


def build_fact_pattern(units: list):
    """Собирает выражение «число + единица» под единицы конкретного проекта."""
    units = sorted({u.strip() for u in (units or []) if u and u.strip()},
                   key=len, reverse=True)
    if not units:
        return None
    alternatives = "|".join(re.escape(u) for u in units)
    return re.compile(NOT_INSIDE + r"(" + NUMBER + r")[  \u00a0]?(?:" + alternatives +
                      r")(?![^\W\d_])", re.I | re.U)


def _norm_number(raw: str) -> str:
    """
    Нормализует число, различая разделитель разрядов и десятичную запятую.

    «1,500» в английском тексте — это полторы тысячи, «1,5» в русском —
    полтора. Раньше и то и другое становилось 1.5: правильная цена
    объявлялась выдумкой, а ошибка в тысячу раз проходила молча.
    """
    s = re.sub(r"[\s  ]", "", str(raw)).strip(".,")
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


def _numbers_in(text: str, fact_pattern) -> dict:
    """
    Числа, которые в этом тексте выглядят как факт.

    Возвращает {число: единица}. Единица нужна, чтобы в отчёте было написано
    «25 тонн», а не просто «25»: без неё находку невозможно проверить глазами.
    """
    found = {}
    for match in PERCENT.finditer(text or ""):
        number = _norm_number(match.group(1))
        if number:
            found.setdefault(number, "%")
    if fact_pattern:
        for match in fact_pattern.finditer(text or ""):
            number = _norm_number(match.group(1))
            if number:
                found[number] = match.group(0)[len(match.group(1)):].strip()
    for match in PREFIX_PRICE.finditer(text or ""):
        number = _norm_number(match.group(2))
        if number:
            found.setdefault(number, match.group(1).strip())
    return found


_SCALE = re.compile(r"(?:\b(?:out\s+of|of|из|von|sur|su|de|na)\s+|/\s?)(?:5|10|100)\b(?!\s?%)",
                    re.I)


def _generic_numbers_in(text: str) -> dict:
    """«Число + любое слово» — второй эшелон: слабее сигнал, но покрывает всё."""
    found = {}
    # Верх шкалы — «4.6 out of 5», «4,6 из 5», «4.6/5» — постоянная, а не
    # факт строки: на каталоге это давало `check-by-eye` на 164 страницах из 202.
    text = _SCALE.sub(" ", text or "")
    for match in GENERIC_FACT.finditer(text):
        unit = match.group(2).strip().lower()
        if unit in NON_UNITS or unit.isdigit():
            continue
        number = _norm_number(match.group(1))
        if not number:
            continue
        # Год в тексте — не факт строки: «в 2026 году», «с 1998 г.» Годом
        # считается только голое четырёхзначное число: `1,900` с разделителем
        # разрядов — это тысяча девятьсот чего-то, а не год.
        if re.fullmatch(r"\d{4}", match.group(1)) and 1900 <= int(number) <= 2100:
            continue
        found.setdefault(number, match.group(2).strip())
    return found


# Число в данных строки: не приклеенное к буквам, чтобы артикул «A-90-15»
# не выдавал индульгенцию выдуманной цифре 90.
#
# Дефис сам по себе числу не мешает: `3-5 days` — это и 3, и 5, а `2026-03-15`
# — три числа. Мешает буква в той же цепочке через дефис. Раньше любой дефис
# рядом выбрасывал число, и диапазон из данных не поддерживал собственные края.
ROW_NUMBER = re.compile(r"(?<![\w.,])(" + NUMBER + r")(?!\w)")
_CHAIN = re.compile(r"[\w\-–—]*")
_CHAIN_BACK = re.compile(r"[\w\-–—]*$")


def _numbers_of(value) -> list:
    """Числа из одного значения строки — кроме тех, что сидят в артикуле."""
    text, out = str(value), []
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
        for raw in _numbers_of(value):
            number = _norm_number(raw)
            if number:
                out.add(number)
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
    per_column = defaultdict(Counter)
    for row in rows:
        for column, value in (row or {}).items():
            for raw in _numbers_of(value):
                number = _norm_number(raw)
                if number:
                    per_column[column][number] += 1
    threshold = max(2, int(len(rows) * share))
    out = set()
    for counter in per_column.values():
        out |= {number for number, count in counter.items() if count >= threshold}
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
    if unit and unit in "$€£¥₹₽":
        return f"{unit}{number}"
    if unit and unit.upper() in CURRENCY_CODES.split("|"):
        return f"{unit} {number}"
    return f"{number} {unit}".strip()


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
    constants = _site_constants(rows)

    issues = []
    for page in sorted(pages, key=lambda p: p.url):
        row = matched.get(page.url)
        if row is None:
            continue
        allowed = _row_numbers(row) | constants

        strong = _numbers_in(page.text, fact_pattern)
        weak = _generic_numbers_in(page.text)

        unknown_strong = {n: u for n, u in strong.items() if n not in allowed}
        unknown_weak = {n: u for n, u in weak.items()
                        if n not in allowed and n not in unknown_strong}

        if unknown_strong:
            issues.append((
                "critical", page.url, "unsupported-number",
                tr("в тексте есть числа, которых нет в данных: ")
                + ", ".join(_shown(n, u) for n, u in
                            sorted(unknown_strong.items())[:6])
                + (tr(" и ещё") if len(unknown_strong) > 6 else "")))
        if unknown_weak:
            # Одна строка на страницу и уровень «мелочь»: это список
            # для просмотра глазами, а не приговор. Раньше каждое такое
            # число становилось отдельным предупреждением, и 62% отчёта
            # занимал шум вроде «3 шага» и «5 звёзд».
            listed = sorted(unknown_weak.items(),
                            key=lambda kv: (-len(kv[0]), kv[0]))[:8]
            issues.append((
                "info", page.url, "check-by-eye",
                tr("числа, которых нет в данных — просмотри глазами: ")
                + ", ".join(f"{n} {u}".strip() for n, u in listed)
                + (tr(" и ещё {a0}", a0=len(unknown_weak) - len(listed))
                   if len(unknown_weak) > len(listed) else "")))
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
    for skeleton, urls in sorted(skeletons.items()):
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
