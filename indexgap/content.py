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

import os
import re
from collections import Counter, defaultdict
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
NUMBER = r"\d{1,3}(?:[  \u00a0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"

PERCENT = re.compile(r"(" + NUMBER + r")\s*%")

# Общее «число + слово»: ловит «12 лет», «25 тонн», «3500 заказов» —
# то, чего нет в списке единиц проекта, но что всё равно является фактом.
# Отрицательный просмотр назад отсекает «топ-10», «айфон-15», «ГОСТ-12»:
# число, приклеенное к слову дефисом, — часть названия, а не мера.
GENERIC_FACT = re.compile(
    r"(?<![^\W\d_]-)(?<!\d)(" + NUMBER + ")[  \\u00a0]?(м²|м2|km²|[^\\W\\d_]{1,14}|[%°$€£₽¥₹])", re.U)

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
    return re.compile(r"(" + NUMBER + r")[  \u00a0]?(?:" + alternatives +
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
    return found


def _generic_numbers_in(text: str) -> dict:
    """«Число + любое слово» — второй эшелон: слабее сигнал, но покрывает всё."""
    found = {}
    for match in GENERIC_FACT.finditer(text or ""):
        unit = match.group(2).strip().lower()
        if unit in NON_UNITS or unit.isdigit():
            continue
        number = _norm_number(match.group(1))
        if not number:
            continue
        # Год в тексте — не факт строки: «в 2026 году», «с 1998 г.»
        try:
            if 1900 <= float(number) <= 2100 and float(number) == int(float(number)) \
                    and len(number) == 4:
                continue
        except ValueError:
            pass
        found.setdefault(number, match.group(2).strip())
    return found


# Число в данных строки: не приклеенное к буквам, чтобы артикул «A-90-15»
# не выдавал индульгенцию выдуманной цифре 90.
ROW_NUMBER = re.compile(r"(?<![\w\-])(" + NUMBER + r")(?![\w\-])")


def _row_numbers(row: dict) -> set:
    out = set()
    for value in (row or {}).values():
        for match in ROW_NUMBER.finditer(str(value)):
            number = _norm_number(match.group(1))
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
            for match in ROW_NUMBER.finditer(str(value)):
                number = _norm_number(match.group(1))
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

    matched, ambiguous = {}, []
    for page in pages:
        key = (page.meta.get("keyword") or "").strip().lower()
        row = by_keyword.get(key) if key else None

        clashed = False
        if row is None:
            slug = _slug_of(page, root)
            if slug in slug_clash:
                ambiguous.append(page.url)
                clashed = True
            else:
                row = by_slug.get(slug)

        if row is None and not clashed:
            haystack = " ".join([page.title] + [t for _, t in page.headings[:2]]).lower()
            # Ключи из Вордстата в именительном падеже, заголовки — в предложном.
            # Без нормализации словоформ сопоставлялось 10 страниц из 100,
            # и сверка фактов молча выключалась на девяти десятых сайта.
            haystack_tokens = _stems(haystack)
            scored = []
            for candidate_key in sorted(by_keyword):
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
    return {"matched": matched, "ambiguous": sorted(set(ambiguous))}


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
                + ", ".join(f"{n} {u}".strip() for n, u in
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
        words = page.words[:12]
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


BRIEF_MARKERS = ("БРИФ ДЛЯ АГЕНТА", "BRIEF FOR THE AGENT", "<!-- TODO", "TODO:")

# Иероглиф несёт примерно столько же, сколько слово: «中文» — это «на китайском»,
# и по длине его мерить нельзя. На живом сайте виз переключатель языков и ссылки
# на соцсети давали `vague-anchor` на всех 2 970 страницах — сто процентов сайта,
# то есть находка без смысла.
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")
# Короткие анкоры, которые информативны сами по себе: языки и площадки.
KNOWN_SHORT_ANCHORS = {
    "vk", "x", "fb", "ok", "tg", "wa", "yt", "in", "li", "рф",
    "en", "ru", "de", "fr", "es", "it", "pt", "pl", "cs", "tr", "ar", "fa",
    "hi", "bn", "ur", "zh", "id", "ms", "ja", "ko", "th", "vi", "uz", "kk",
}


def _uninformative_length(anchor: str, cfg: dict) -> bool:
    """Короткий анкор — не всегда бессмысленный."""
    text = anchor.strip()
    if text.lower() in KNOWN_SHORT_ANCHORS:
        return False
    if _CJK.search(text):
        # Один иероглиф ≈ два латинских знака: тот же порог, но в своей мере.
        return len(text) * 2 < cfg["min_anchor_chars"]
    return len(text) < cfg["min_anchor_chars"]


def check_brief(pages: list, cfg: dict = None) -> list:
    """Выполнен ли бриф: не остались ли следы заготовки и вменяемы ли анкоры."""
    cfg = {**CONFIG, **(cfg or {})}
    issues = []
    for page in sorted(pages, key=lambda p: p.url):
        raw = page.raw or ""
        if any(marker in raw for marker in BRIEF_MARKERS):
            issues.append(("critical", page.url, "brief-left",
                           "в файле остался блок брифа или TODO — страница не дописана"))
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

    seams = check_template_seams(pages, cfg)
    issues += seams["issues"]
    issues += check_brief(pages, cfg)

    notes = []
    if seams.get("skipped"):
        notes.append(tr("швы шаблона не оценивались: ") + seams["skipped"])
    if ambiguous:
        notes.append(
            tr("{a0} страниц(ы) подошли сразу к нескольким строкам датасета — сверка фактов для них не делалась. Добавь `keyword` во фронтматтер, чтобы связь была однозначной.", a0=len(ambiguous)))

    return {
        "issues": issues,
        "repeated_skeletons": seams["repeated"],
        "matched_rows": len(matched),
        "ambiguous": ambiguous,
        "facts_checked": facts_checked,
        "fact_units": sorted(fact_units or []),
        "notes": notes,
        "unmatched": sorted(p.url for p in pages if p.url not in matched) if rows else [],
    }
