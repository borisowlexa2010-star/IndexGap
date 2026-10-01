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
        return _ld_items(json.loads(raw))
    except json.JSONDecodeError:
        return []


def page_dates(page) -> dict:
    """
    Все даты страницы, какие удалось прочитать: {источник: дата}.
    Берётся самая поздняя из «когда заканчивается» — именно она решает,
    протухла страница или нет.
    """
    found = {}
    for key, value in (page.meta or {}).items():
        if key.lower().replace("-", "_") in DATE_FIELDS:
            parsed = _parse_date(value)
            if parsed:
                found[f"frontmatter:{key}"] = parsed

    is_event = bool(found)
    for raw in page.jsonld or ():
        for node in _ld_nodes(raw):
            kinds = node.get("@type")
            kinds = kinds if isinstance(kinds, list) else [kinds]
            event = any("event" in str(k).lower() for k in kinds)
            is_event = is_event or event
            for key, value in node.items():
                if str(key).lower() in DATE_FIELDS:
                    parsed = _parse_date(value)
                    if parsed:
                        found[f"jsonld:{key}"] = parsed
            offers = node.get("offers")
            offers = offers if isinstance(offers, list) else [offers]
            for offer in offers:
                if isinstance(offer, dict):
                    parsed = _parse_date(offer.get("validThrough"))
                    if parsed:
                        found["jsonld:validThrough"] = parsed
            if not event:
                continue
            # Событие по расписанию идёт до конца расписания, а не до первой
            # даты: еженедельная встреча с `endDate` через год объявлялась
            # прошедшей на третьей неделе. Расписание без конца — бессрочное.
            schedules = node.get("eventSchedule")
            schedules = schedules if isinstance(schedules, list) else [schedules]
            for schedule in schedules:
                if not isinstance(schedule, dict):
                    continue
                parsed = _parse_date(schedule.get("endDate"))
                if not parsed:
                    return {}
                found["jsonld:eventSchedule"] = parsed
            parts = node.get("subEvent")
            for part in parts if isinstance(parts, list) else [parts]:
                if isinstance(part, dict):
                    parsed = _parse_date(part.get("endDate") or part.get("startDate"))
                    if parsed:
                        found.setdefault("jsonld:subEvent", parsed)
                        found["jsonld:subEvent"] = max(found["jsonld:subEvent"], parsed)

    # <time> стоит на любой странице: «проверено 2 марта», дата публикации
    # новости. Датой события он становится, только если страница — событие.
    if is_event:
        for match in re.finditer(r"<time[^>]+datetime=[\"']([^\"']+)", page.raw or "", re.I):
            parsed = _parse_date(match.group(1))
            if parsed:
                found.setdefault("time", parsed)
    return found


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
    grace = timedelta(days=cfg["grace_days"])

    issues = []
    dated = 0
    stale = 0
    for page in sorted(pages, key=lambda p: p.url):
        dates = page_dates(page)
        if not dates:
            continue
        dated += 1
        latest = max(dates.values())
        if latest + grace >= today:
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
