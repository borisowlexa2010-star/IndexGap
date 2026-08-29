# -*- coding: utf-8 -*-
"""
Портфель: один прогон по нескольким проектам сразу и сводный разбор.

Зачем это отдельный режим, а не «запусти пять раз». Отдельные отчёты отвечают
на вопрос «что не так у этого сайта». Портфель отвечает на другой, который
в отдельных отчётах не виден вовсе: **что ломается одинаково везде.**

Одна и та же дыра в перелинковке на четырёх разных нишах — это уже не баг
конкретного проекта, а свойство того, как эти проекты собираются. Чинить нужно
не страницу, а привычку; и рассказывать об этом на курсе нужно как о типовых
граблях, а не как о частном случае визового справочника.

Формат описания портфеля — обычный JSON:

    {
      "projects": [
        {"name": "visa", "root": "…/content", "site": "https://…",
         "profile": "catalog", "dataset": "keywords.csv"},
        {"name": "events", "root": "…/pages", "site": "https://…",
         "profile": "events"},
        {"name": "feed", "root": "…/posts", "site": "https://…",
         "profile": "ugc"}
      ]
    }

Пути внутри — относительно самого файла описания, чтобы портфель можно было
положить рядом с репозиториями и не переписывать при переезде.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

from . import aeo, checks, content, doctor, freshness, profiles, report, settings
from .core import SourceError, check_site_url, load_pages, read_text, url_key
from .i18n import tr

REQUIRED = ("name", "root", "site")

# Находки, которые целиком зависят от настраиваемого порога. Если такая
# срабатывает почти везде, вопрос к порогу, а не к страницам.
THRESHOLD_CODES = {"thin", "low-uniqueness", "title-short", "title-long",
                   "description-length", "answer-short", "answer-long",
                   "deep", "similar", "near-duplicate", "template-skeleton"}


def read_portfolio(path: str) -> list:
    """Читает описание портфеля и превращает пути в абсолютные."""
    if not os.path.exists(path):
        raise SourceError(tr("Файл портфеля {a0} не найден.", a0=path))
    text, _ = read_text(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceError(tr("{a0}: не разбирается как JSON ({a1}, строка {a2}).", a0=path, a1=exc.msg, a2=exc.lineno))

    specs = data.get("projects") if isinstance(data, dict) else data
    if not isinstance(specs, list) or not specs:
        raise SourceError(tr("{a0}: ожидался список проектов в поле `projects`.", a0=path))

    base = os.path.dirname(os.path.abspath(path)) or "."
    out = []
    seen = set()
    for i, spec in enumerate(specs, 1):
        if not isinstance(spec, dict):
            raise SourceError(tr("{a0}: проект №{a1} — не объект.", a0=path, a1=i))
        missing = [k for k in REQUIRED if not str(spec.get(k) or "").strip()]
        if missing:
            raise SourceError(
                tr("{a0}: у проекта №{a1} нет полей ", a0=path, a1=i) + ", ".join(missing)
                + tr(".\n    Обязательные: name (имя), root (каталог со страницами), site (адрес сайта со схемой)."))
        name = str(spec["name"]).strip()
        if name in seen:
            raise SourceError(tr("{a0}: имя проекта «{a1}» повторяется.", a0=path, a1=name))
        seen.add(name)

        resolved = dict(spec)
        resolved["name"] = name
        resolved["site"] = check_site_url(str(spec["site"]))
        for key in ("root", "dataset", "sitemap", "robots", "config", "out"):
            value = spec.get(key)
            if value:
                resolved[key] = os.path.normpath(os.path.join(base, str(value)))
        resolved["indexed"] = [
            (s if "=" not in s else
             s.split("=", 1)[0] + "=" + os.path.normpath(os.path.join(base, s.split("=", 1)[1])))
            for s in (spec.get("indexed") or [])
        ]
        out.append(resolved)
    return out


def run_one(spec: dict, quiet: bool = False) -> dict:
    """
    Прогоняет один проект. Ошибка одного проекта не роняет портфель:
    она записывается в результат, и остальные считаются дальше.
    """
    from . import generate

    name = spec["name"]
    result = {"name": name, "profile": spec.get("profile") or profiles.DEFAULT_PROFILE,
              "site": spec["site"], "root": spec["root"], "error": "",
              "pages": 0, "issues": [], "notes": [], "counts": {}, "report": ""}
    try:
        pages, problems = load_pages(spec["root"], spec["site"])
        if not pages:
            raise SourceError(tr("в {a0} нет ни одной страницы", a0=spec['root']))
        result["pages"] = len(pages)
        result["notes"] += problems

        rows = []
        if spec.get("dataset"):
            data = generate.read_dataset(spec["dataset"])
            rows = data["rows"]
            result["notes"] += data["problems"]

        project = settings.resolve(spec["root"], pages, rows,
                                   spec.get("keyword", "keyword"),
                                   spec.get("config", ""))
        project = profiles.apply(project, result["profile"])
        result["profile_title"] = project["_profile_title"]
        result["profile_notes"] = project["_profile_notes"]

        if project["_expects_dataset"] and not rows:
            result["notes"].append(
                tr("профиль «{a0}» рассчитан на страницы из датасета, но датасет не указан — сверка фактов не выполнялась", a0=result['profile']))

        home = spec.get("home") or (spec["site"]
                                    if url_key(spec["site"]) in {p.key for p in pages}
                                    else None)
        analysis = checks.run_all(pages, home_url=home, cfg=project.get("checks"),
                                  language=project.get("language", ""))
        result["notes"] += analysis.get("notes") or []

        if not project["_skip_facts"]:
            cfg = dict(project.get("content") or {})
            cfg["vague_anchors"] = project.get("vague_anchors", [])
            text_result = content.run(pages, rows, spec.get("keyword", "keyword"),
                                      spec["root"], cfg=cfg,
                                      fact_units=project.get("fact_units"))
            analysis["issues"] += text_result["issues"]
            result["notes"] += text_result.get("notes") or []
            result["matched_rows"] = text_result["matched_rows"]
        else:
            result["notes"].append(
                tr("сверка фактов и швов шаблона выключена профилем: страницы не порождаются датасетом, сверять не с чем"))

        robots = spec.get("robots") or _guess_robots(spec["root"])
        analysis["issues"] += aeo.run(pages, robots, cfg=project.get("aeo"))["issues"]

        if project["_checks_freshness"]:
            fresh = freshness.check(pages, spec.get("freshness"))
            analysis["issues"] += fresh["issues"]
            result["dated_pages"] = fresh["dated"]
            if fresh["note"]:
                result["notes"].append(fresh["note"])

        if spec.get("sitemap"):
            sm = doctor.read_sitemap(spec["sitemap"])
            if sm["error"]:
                result["notes"].append(tr("sitemap не прочитан: {a0}", a0=sm['error']))
            else:
                funnel = doctor.funnel(pages, sm["urls"], None)
                result["funnel"] = funnel["steps"]

        analysis["issues"] = checks.sort_issues(analysis["issues"])
        result["issues"] = analysis["issues"]
        result["counts"] = dict(Counter(i[0] for i in analysis["issues"]))
        result["orphans"] = len(analysis["graph"]["orphans"])
        result["duplicates"] = len(analysis["duplicates"])
        result["page_urls"] = sorted(p.url for p in pages)

        if spec.get("out"):
            result["report"] = report.build(
                analysis, out_path=spec["out"], site=spec["site"],
                notes=result["notes"], title=tr("Проверка — {a0}", a0=name))
    except SourceError as exc:
        result["error"] = str(exc)
    return result


def _guess_robots(root: str) -> str:
    for candidate in (os.path.join(root, "robots.txt"),
                      os.path.join(os.path.dirname(os.path.abspath(root)), "robots.txt")):
        if os.path.isfile(candidate):
            return candidate
    return ""


def common_patterns(results: list, min_projects: int = 2) -> list:
    """
    Что ломается одинаково в разных проектах.

    Смысл именно в доле страниц, а не в абсолютном числе: сто находок
    на проекте из трёх тысяч страниц и десять на проекте из двадцати —
    это одна и та же болезнь разной громкости. Сортировка идёт по числу
    затронутых проектов, потом по средней доле.
    """
    per_code = defaultdict(dict)
    site_level = set()
    for r in results:
        if r["error"] or not r["pages"]:
            continue
        page_urls = set(r.get("page_urls") or ())
        touched = defaultdict(set)
        levels = {}
        for level, url, code, _ in r["issues"]:
            touched[code].add(url)
            levels.setdefault(code, level)
            # Находка вроде «в robots.txt закрыт краулер» относится к сайту,
            # а не к странице. Считать её «долей затронутых страниц» —
            # бессмыслица: получится 1/16 вместо «есть».
            if url not in page_urls:
                site_level.add(code)
        for code, urls in touched.items():
            per_code[code][r["name"]] = {
                "pages": len(urls),
                "share": round(len(urls) / r["pages"], 3),
                "level": levels[code],
            }

    out = []
    for code, by_project in per_code.items():
        if len(by_project) < min_projects:
            continue
        shares = [v["share"] for v in by_project.values()]
        # Код, сработавший почти на всех страницах всех проектов, — это почти
        # всегда не общая беда, а порог, не настроенный под ваш контент.
        # Молчать об этом нельзя: человек пойдёт «чинить» тысячи страниц.
        near_total = (len(by_project) >= 2
                      and min(shares) >= 0.9
                      and code in THRESHOLD_CODES)
        out.append({
            "code": code,
            "level": sorted(v["level"] for v in by_project.values())[0],
            "scope": "site" if code in site_level else "page",
            "threshold_suspect": near_total,
            "projects": sorted(by_project),
            "project_count": len(by_project),
            "avg_share": round(sum(shares) / len(shares), 3),
            "max_share": round(max(shares), 3),
            "detail": by_project,
        })
    order = {"critical": 0, "warning": 1, "info": 2}
    out.sort(key=lambda p: (p["scope"] != "page", -p["project_count"],
                            order.get(p["level"], 3), -p["avg_share"], p["code"]))
    return out


def unique_findings(results: list) -> list:
    """Обратная сторона: что встречается ровно в одном проекте — его личное."""
    seen = defaultdict(set)
    for r in results:
        if r["error"]:
            continue
        for _, _, code, _ in r["issues"]:
            seen[code].add(r["name"])
    out = []
    for r in results:
        if r["error"]:
            continue
        own = sorted({code for _, _, code, _ in r["issues"] if len(seen[code]) == 1})
        if own:
            out.append({"name": r["name"], "codes": own})
    return out
