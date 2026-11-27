# -*- coding: utf-8 -*-
"""
Свежесть: страницы, у которых кончился срок годности.

Для афиши, расписаний и любого контента с датой это главная проблема,
а вовсе не дубли. Событие прошло, страница осталась открытой для индексации —
и поисковик показывает людям мероприятие, которого уже нет. Это не про трафик,
это про доверие: человек приехал по вашей странице на несуществующий концерт.

Проверяется только то, что можно прочитать локально: даты из JSON-LD
(`Event.startDate`, `endDate`, `offers.validThrough`), из фронтматтера
и из `<time datetime>`. Если даты нет вовсе — это тоже находка: без неё
ни поисковик, ни ИИ-поиск не поймут, актуальна страница или нет.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from .i18n import tr

CONFIG = {
    # Сколько дней после события страница ещё считается уместной в индексе:
    # отчёты, фотографии и «как это было» — законный контент.
    "grace_days": 14,
    # Ниже этой доли страниц с датами проверка не запускается: значит,
    # это не датированный контент, и требовать даты не за что.
    "min_dated_share": 0.3,
}

DATE_FIELDS = ("startdate", "start_date", "date", "event_date", "eventdate",
               "begins", "starts", "validthrough", "enddate", "end_date")

ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _parse_date(value) -> date:
    match = ISO_DATE.search(str(value or ""))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _ld_nodes(raw: str) -> list:
    from .aeo import _ld_items
    try:
        # Событие внутри `WebPage.mainEntity` — главное содержание страницы.
        # Элементы списка (`ItemList`) — нет: архив прошедших событий законен.
        return _ld_items(json.loads(raw), ("mainentity",))
    except (ValueError, RecursionError):
        return []


def _put(found: dict, key: str, parsed) -> None:
    """Самая поздняя дата источника: два события в @graph не затирают друг друга."""
    found[key] = max(found.get(key, parsed), parsed)


def _node_dates(node: dict, event: bool) -> tuple:
    """({источник: дата}, бессрочное ли это событие) для одного узла JSON-LD."""
    found = {}
    for key, value in node.items():
        if str(key).lower() in DATE_FIELDS:
            parsed = _parse_date(value)
            if parsed:
                _put(found, f"jsonld:{key}", parsed)
    offers = node.get("offers")
    offers = offers if isinstance(offers, list) else [offers]
    for offer in offers:
        if isinstance(offer, dict):
            parsed = _parse_date(offer.get("validThrough"))
            if parsed:
                _put(found, "jsonld:validThrough", parsed)
    if not event:
        return found, False
    # Событие по расписанию идёт до конца расписания, а не до первой
    # даты: еженедельная встреча с `endDate` через год объявлялась
    # прошедшей на третьей неделе. Расписание без конца — бессрочное.
    open_ended = False
    schedules = node.get("eventSchedule")
    schedules = schedules if isinstance(schedules, list) else [schedules]
    for schedule in schedules:
        if not isinstance(schedule, dict):
            continue
        parsed = _parse_date(schedule.get("endDate"))
        if parsed:
            _put(found, "jsonld:eventSchedule", parsed)
        else:
            open_ended = True
    parts = node.get("subEvent")
    for part in parts if isinstance(parts, list) else [parts]:
        if isinstance(part, dict):
            parsed = _parse_date(part.get("endDate") or part.get("startDate"))
            if parsed:
                _put(found, "jsonld:subEvent", parsed)
    # Свой `endDate` у события закрывает и бессрочное расписание: серия
    # кончилась тогда, когда сказано.
    if open_ended and _parse_date(node.get("endDate")):
        open_ended = False
    return found, open_ended


def _dates(page) -> tuple:
    """
    ({источник: дата}, [названия бессрочных событий]).

    Бессрочное событие (расписание без конца) пропускается само по себе: его
    `startDate` — первая встреча серии, а не конец. Остальные узлы и
    фронтматтер считаются как обычно — прошедший фестиваль рядом с еженедельной
    встречей раньше пропадал вместе со всеми датами страницы.
    """
    found = {}
    for key, value in (page.meta or {}).items():
        if key.lower().replace("-", "_") in DATE_FIELDS:
            parsed = _parse_date(value)
            if parsed:
                found[f"frontmatter:{key}"] = parsed

    is_event = bool(found)
    ongoing = []
    for raw in page.jsonld or ():
        for node in _ld_nodes(raw):
            kinds = node.get("@type")
            kinds = kinds if isinstance(kinds, list) else [kinds]
            event = any("event" in str(k).lower() for k in kinds)
            is_event = is_event or event
            dates, open_ended = _node_dates(node, event)
            if open_ended:
                ongoing.append(str(node.get("name") or "").strip())
                continue
            for key, parsed in dates.items():
                _put(found, key, parsed)

    # <time> стоит на любой странице: «проверено 2 марта», дата публикации
    # новости. Датой события он становится, только если страница — событие.
    # Рядом с бессрочной серией <time> — обычно дата её ближайшей или первой
    # встречи, и к какому событию он относится, не понять: он не считается.
    if is_event and not ongoing:
        from .core import INERT, NOT_LIVE, drop_spans
        raw = drop_spans(page.raw or "", NOT_LIVE + INERT)
        for match in re.finditer(r"<time\b[^<>]{0,500}?datetime=[\"']([^\"'<>]{1,60})", raw, re.I):
            parsed = _parse_date(match.group(1))
            if parsed:
                # Самая поздняя, как везде: «объявлено в 2024-м» перед датой
                # концерта не делает концерт прошедшим.
                found["time"] = max(found.get("time", parsed), parsed)
    return found, ongoing


def page_dates(page) -> dict:
    """
    Все даты страницы, какие удалось прочитать: {источник: дата}.
    Берётся самая поздняя из «когда заканчивается» — именно она решает,
    протухла страница или нет. Бессрочные события в них не входят.
    """
    return _dates(page)[0]


def check(pages: list, cfg: dict = None, today: date = None) -> dict:
    """
    Находки по срокам годности.

    Возвращает и список находок, и статистику — сколько страниц вообще
    датировано. Без второго числа первое нельзя интерпретировать: ноль
    просроченных на сайте без дат означает не «всё хорошо», а «не проверено».
    """
    from .publish import indexable

    cfg = {**CONFIG, **(cfg or {})}
    today = today or date.today()
    # `endDate: 9999-12-31` у бессрочной выставки и огромный `grace_days`
    # выходят за пределы календаря: такая страница не протухает.
    try:
        cutoff = today - timedelta(days=cfg["grace_days"])
    except OverflowError:
        cutoff = date.min

    issues = []
    dated = 0
    stale = 0
    for page in sorted(pages, key=lambda p: p.url):
        dates, ongoing = _dates(page)
        if not dates and not ongoing:
            continue
        dated += 1
        if not dates:
            continue
        latest = max(dates.values())
        if latest >= cutoff:
            continue
        if ongoing:
            # Страница — действующая серия, а прошло только соседнее событие:
            # закрывать её от индекса не за что, но устаревшую дату стоит убрать.
            if indexable(page):
                issues.append((
                    "warning", page.url, "stale-event-part",
                    tr("дата {a0} прошла более {a1} дней назад, но на странице есть и бессрочная серия ({a2}), "
                       "поэтому сама страница актуальна. Убери прошедшее событие из разметки и текста или "
                       "перенеси его в архив", a0=latest.isoformat(), a1=cfg['grace_days'],
                       a2=", ".join(sorted({n for n in ongoing if n})) or "eventSchedule")))
            continue
        stale += 1
        if indexable(page):
            issues.append((
                "critical", page.url, "stale-event",
                tr("дата {a0} прошла более {a1} дней назад, а страница открыта для индексации — поисковик показывает людям то, чего уже нет. Закрой noindex, поставь редирект на актуальную или перепиши в отчёт о прошедшем", a0=latest.isoformat(), a1=cfg['grace_days'])))
        else:
            issues.append((
                "info", page.url, "stale-closed",
                tr("дата {a0} прошла, страница уже закрыта от индексации — это правильно", a0=latest.isoformat())))

    share = dated / len(pages) if pages else 0
    note = ""
    if pages and share < cfg["min_dated_share"]:
        note = (tr("даты нашлись только у {a0} страниц из {a1}. Для датированного контента это мало: без машиночитаемой даты нельзя ни проверить актуальность, ни показать её в выдаче", a0=dated, a1=len(pages)))
    return {"issues": issues, "dated": dated, "stale": stale, "note": note}
