# -*- coding: utf-8 -*-
"""
Командная строка. Восемь команд, каждая делает ровно одну вещь.

    indexgap init                                    ← первое, что делает человек
    indexgap plan    keywords.csv --keyword keyword
    indexgap check   ./content --site https://example.com
    indexgap sitemap ./content --site https://example.com --out-dir ./public
    indexgap notify  ./content --site https://example.com --key <свой-ключ>
    indexgap doctor  ./content --site https://example.com --sitemap ./public/sitemap.xml

Ничего не отправляется наружу без явного флага --send.

Правила вывода, добытые аудитом: никаких трейсбеков там, где виновата опечатка
в пути; никаких молчаливых нулей; отчёты разных команд не затирают друг друга.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import (aeo, checks, content, doctor, engines, freshness, generate,
               install, portfolio, profiles, publish, report, settings, sources)
from . import i18n
from .i18n import tr
from .core import (SourceError, check_site_url, load_manifest, load_pages,
                   save_manifest, url_key)

MANIFEST = ".indexgap-manifest.json"


def _setup_output():
    """
    Русский вывод не должен ронять консоль Windows.

    cp866 — кодировка cmd.exe по умолчанию, cp1251 Python берёт, когда stdout
    уходит в пайп, то есть при запуске через агента. Раньше первая же строка
    с тире валила команду с UnicodeEncodeError, и отчёт не создавался вовсе.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


PROJECT_FILES = ("indexgap.json", ".indexgap.json")


def apply_project_defaults(args) -> str:
    """
    Подставляет то, что записал `indexgap init`, вместо обязательных аргументов.

    Смысл установки в проект именно в этом: после неё ежедневная команда —
    `indexgap check`, без путей и флагов. Явный аргумент всегда сильнее конфига.
    """
    path = ""
    for directory in (os.getcwd(), os.path.dirname(os.getcwd())):
        for name in PROJECT_FILES:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                path = candidate
                break
        if path:
            break
    if not path:
        return ""
    try:
        from .core import read_text
        text, _ = read_text(path)
        data = json.loads(text)
    except (SourceError, json.JSONDecodeError) as exc:
        raise SourceError(
            tr("{a0} не читается: {a1}.\n    Это файл настроек проекта. Поправь его или удали и запусти `indexgap init` заново.", a0=path, a1=exc))
    if not isinstance(data, dict):
        return ""

    base = os.path.dirname(path)
    pages = data.get("pages")
    if not isinstance(pages, str):
        legacy = data.get("content")
        pages = legacy if isinstance(legacy, str) else ""
    if not getattr(args, "root", None) and pages:
        args.root = pages if os.path.isabs(pages) else os.path.join(base, pages)
    if not getattr(args, "site", None) and data.get("site"):
        args.site = data["site"]
    if hasattr(args, "dataset") and not args.dataset and data.get("dataset"):
        args.dataset = os.path.join(base, data["dataset"])
    if hasattr(args, "profile") and not args.profile and data.get("profile"):
        args.profile = data["profile"]
    return path


def _load(args):
    if not args.root or not args.site:
        raise SourceError(
            tr("Не хватает данных о проекте.\n    Либо укажи их явно: indexgap check ./content --site https://example.com\n    Либо один раз выполни `indexgap init` в корне проекта — тогда\n    ежедневная команда станет просто `indexgap check`."))
    site = check_site_url(args.site)
    args.site = site
    pages, problems = load_pages(args.root, site)
    for problem in problems:
        print(f"  ! {problem}")
    if not pages:
        if not os.path.exists(args.root):
            raise SourceError(tr("Каталога {a0} нет. Проверь путь.", a0=args.root))
        if os.path.isfile(args.root):
            raise SourceError(tr("{a0} — это файл, а нужен каталог со страницами.", a0=args.root))
        raise SourceError(
            tr("В {a0} нет ни одной страницы (.html, .htm, .md, .markdown).\n    Если страницы лежат глубже — укажи нужный подкаталог.", a0=args.root))
    print(tr("Разобрано страниц: {a0}", a0=len(pages)))
    return pages


def _home_url(args, pages):
    """
    Главная — это адрес сайта, а не самый короткий URL из найденных.
    Прежний способ на каталоге раздела объявлял недостижимыми все страницы,
    кроме одной случайно выбранной.
    """
    if getattr(args, "home", None):
        return args.home
    keys = {p.key for p in pages}
    return args.site if url_key(args.site) in keys else None


REPORT_MARK = "<!-- indexgap-report -->"


def check_out_path(path: str) -> str:
    """
    Отчёт не должен затирать чужой файл.

    `--out ./content/p1/index.html` молча заменял страницу сайта отчётом
    и бодро сообщал «Отчёт записан». Просьба «положи отчёт рядом со страницами»
    — ровно то, что человек говорит агенту.
    """
    if os.path.isdir(path):
        raise SourceError(tr("--out {a0} — это каталог. Укажи имя файла, например {a1}", a0=path, a1=os.path.join(path, 'indexgap-check.html')))
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                head = fh.read(4096)
        except OSError:
            head = ""
        if REPORT_MARK not in head:
            raise SourceError(
                tr("--out {a0} уже существует и это не отчёт пакета.\n    Перезаписывать чужой файл я не буду — укажи другое имя.", a0=path))
    return path


def _serialize_issues(issues):
    return [{"level": l, "url": u, "code": c, "message": m} for l, u, c, m in issues]


def resolve_keyword_field(args, fields: list, path: str) -> str:
    """
    Находит колонку с ключом, как бы её ни назвал экспорт.

    Датасет редко делают руками: он приезжает из Ahrefs («Keyword»),
    Semrush («Keyword»), Вордстата («Фраза»), Keys.so («Запрос»),
    Serpstat («Ключевая фраза»). Требовать колонку ровно `keyword` —
    значит отправлять человека переименовывать столбец перед каждой командой.
    Явный `--keyword` всегда сильнее догадки.
    """
    if args.keyword in fields:
        return args.keyword
    if args.keyword != "keyword":            # человек назвал колонку сам
        raise SourceError(
            tr("Колонки «{a0}» в {a1} нет.\n    Есть: {a2}\n    Укажи нужную: --keyword <имя колонки>", a0=args.keyword, a1=path, a2=', '.join(fields)))
    guess = sources.guess_column(fields, sources.KEYWORD_COLUMN_HINTS)
    if guess >= 0:
        found = fields[guess]
        print(tr("  ! колонка с ключом не названа `keyword` — взята «{a0}». Если это не она, укажи явно: --keyword <имя колонки>", a0=found))
        args.keyword = found
        return found
    raise SourceError(
        tr("Колонки с ключевым словом в {a0} не нашлось.\n    Есть: {a1}\n    Укажи нужную: --keyword <имя колонки>", a0=path, a1=', '.join(fields)))


def _collect_indexed(args) -> tuple:
    """
    Собирает выгрузки из --indexed (можно несколько) и --gsc.

    Возвращает две части: панели вебмастера и всё остальное — Ahrefs, Semrush,
    краулеры, аналитику. Смешивать их в одну кучу нельзя: у них разный смысл,
    и отчёт обязан называть вещи своими именами.
    """
    specs = list(getattr(args, "indexed", None) or [])
    if getattr(args, "gsc", None):
        specs.append(f"google={args.gsc}")
    if not specs:
        return {}, {}
    result = doctor.read_sources(specs, site=getattr(args, "site", "") or "")
    by_engine, by_source = result["by_engine"], result["by_source"]
    for note in result["notes"]:
        print(f"  ! {note}")
    if by_engine:
        summary = ", ".join(f"{n}: {len(u)}" for n, u in sorted(by_engine.items()))
        print(tr("Индексация — {a0}", a0=summary))
    if by_source:
        summary = ", ".join(
            f"{n} ({sources.KIND_TITLE[sources.kind_of(n)]}): {len(u)}"
            for n, u in sorted(by_source.items()))
        print(tr("Прочие источники — {a0}", a0=summary))
    for line in sources.describe(list(by_engine) + list(by_source)):
        print(tr("  что это доказывает → {a0}", a0=line))
    for note in engines.describe_coverage(list(by_engine)):
        print(tr("  не покрыто → {a0}", a0=note))
    return by_engine, by_source


def _describe_project(project: dict, rows: list) -> None:
    """Показывает, что пакет понял про проект. Молчаливая автонастройка опаснее явной."""
    parts = []
    language = project.get("language")
    parts.append(tr("язык: {a0}", a0=language or tr("не определён")))
    units = project.get("fact_units") or []
    if units:
        origin = tr("из датасета") if project.get("_derived_units") else tr("из конфига")
        parts.append(tr("единицы фактов ({a0}): {a1}", a0=origin, a1=', '.join(units[:8]))
                     + (" …" if len(units) > 8 else ""))
    elif rows:
        parts.append(tr("единиц измерения в датасете нет — сверка идёт по всем числам"))
    if project.get("_path"):
        parts.append(tr("конфиг: {a0}", a0=os.path.basename(project['_path'])))
    print(tr("Проект — ") + "; ".join(parts))


def _read_rows(args):
    if not getattr(args, "dataset", None):
        return []
    data = generate.read_dataset(args.dataset)
    for problem in data["problems"]:
        print(f"  ! {problem}")
    resolve_keyword_field(args, data["fields"], args.dataset)
    return data["rows"]


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)


# ── команды ───────────────────────────────────────────────────────────────────

def cmd_check(args):
    apply_project_defaults(args)
    pages = _load(args)
    rows = _read_rows(args)
    project = settings.resolve(args.root, pages, rows, args.keyword, args.config)
    project = profiles.apply(project, args.profile or project.get("profile"))
    _describe_project(project, rows)
    print(tr("Профиль — {a0} ({a1})", a0=project['_profile_title'], a1=project['_profile']))

    analysis = checks.run_all(pages, home_url=_home_url(args, pages),
                              cfg=project.get("checks"),
                              language=project.get("language", ""))
    notes = list(analysis.get("notes") or [])

    content_result = None
    if project["_skip_facts"]:
        notes.append(tr("сверка фактов и швов шаблона выключена профилем «{a0}»: страницы не порождаются датасетом, сверять не с чем. Молчание здесь — не «всё хорошо»", a0=project['_profile']))
    elif not args.no_content:
        cfg = dict(project.get("content") or {})
        cfg["vague_anchors"] = project.get("vague_anchors", [])
        content_result = content.run(pages, rows, args.keyword, args.root,
                                     cfg=cfg, fact_units=project.get("fact_units"))
        analysis["issues"] += content_result["issues"]
        notes += content_result.get("notes") or []
        if rows:
            print(tr("Сверено с датасетом: {a0} из {a1}", a0=content_result['matched_rows'], a1=len(pages)))
            if content_result["unmatched"]:
                print(tr("  не сопоставлено: {a0} (проверь keyword во фронтматтере или имена папок)", a0=len(content_result['unmatched'])))

    if project["_checks_freshness"]:
        fresh = freshness.check(pages)
        analysis["issues"] += fresh["issues"]
        print(tr("Датировано страниц: {a0} из {a1}", a0=fresh['dated'], a1=len(pages))
              + (tr(", просрочено {a0}", a0=fresh['stale']) if fresh["stale"] else ""))
        if fresh["note"]:
            notes.append(fresh["note"])

    aeo_result = None
    if not args.no_aeo:
        robots_path = args.robots or _guess_robots(args)
        aeo_result = aeo.run(pages, robots_path, cfg=project.get("aeo"))
        analysis["issues"] += aeo_result["issues"]

    funnel_result = causes = cross = None
    sitemap_urls = None
    by_engine, by_source = _collect_indexed(args)
    if args.sitemap:
        sm = doctor.read_sitemap(args.sitemap)
        if sm["error"]:
            print(tr("  ! sitemap не прочитан: {a0}", a0=sm['error']))
            print(tr("    Сверка с sitemap пропущена — это не значит, что страниц в нём нет."))
        else:
            sitemap_urls = sm["urls"]
    if sitemap_urls is not None or by_engine or by_source:
        funnel_result = doctor.funnel(pages, sitemap_urls, None,
                                      by_engine=by_engine, by_source=by_source)
        causes = doctor.explain(funnel_result, analysis)
        cross = doctor.cross_engine(funnel_result, pages)

    analysis["issues"] = checks.sort_issues(analysis["issues"])
    notes += checks.template_wide(analysis["issues"], len(pages), pages=pages)

    html_path = report.build(analysis, funnel_result, causes,
                             out_path=check_out_path(args.out), site=args.site,
                             cross=cross, notes=notes,
                             title=tr("Проверка перед публикацией"))
    json_path = os.path.splitext(args.out)[0] + ".json"
    _write_json(json_path, {
        "site": args.site,
        "pages": len(pages),
        "notes": notes,
        "issues": _serialize_issues(analysis["issues"]),
        "orphans": analysis["graph"]["orphans"],
        "unreachable": analysis["graph"]["unreachable"],
        "duplicates": [{"a": a.url, "b": b.url, "jaccard": j}
                       for a, b, j in analysis["duplicates"]],
        "duplicate_method": analysis.get("duplicate_method"),
        "unique_share": analysis["unique_share"],
        "funnel": funnel_result,
        "causes": causes,
        "cross_engine": cross,
        "repeated_skeletons": (content_result or {}).get("repeated_skeletons"),
        "unmatched": (content_result or {}).get("unmatched"),
        "robots": (aeo_result or {}).get("robots"),
    })

    for note in notes:
        print(f"  ! {note}")

    crit = sum(1 for i in analysis["issues"] if i[0] == "critical")
    warn = sum(1 for i in analysis["issues"] if i[0] == "warning")
    # Сироты и похожие пары считаются по тексту и ссылкам. У пустой оболочки
    # ни того, ни другого нет, поэтому показывать её в этих счётчиках —
    # значит четыре раза сообщить об одной беде.
    reported = sum(1 for i in analysis["issues"] if i[2] == "orphan")
    print(tr("Критично: {a0}   Внимание: {a1}   Сирот: {a2}   Похожих пар: {a3}", a0=crit, a1=warn, a2=reported, a3=len(analysis['duplicates'])))
    _print_first_things(analysis["issues"])
    print(tr("Отчёт: {a0}\nДанные: {a1}", a0=html_path, a1=json_path))
    return 1 if (crit and args.strict) else 0


def _print_first_things(issues):
    """Три числа, с которых начинают. Скилл обещает их — теперь они есть."""
    from collections import Counter
    counts = Counter(code for level, _, code, _ in issues if level == "critical")
    if not counts:
        return
    print(tr("Чинить в этом порядке:"))
    for code, count in counts.most_common(3):
        print(f"  {count:>5}  {code} — {report.CODE_HELP.get(code, '')[:80]}")


def _guess_robots(args):
    for candidate in (os.path.join(args.root, "robots.txt"),
                      os.path.join(os.path.dirname(os.path.abspath(args.root)),
                                   "robots.txt")):
        if os.path.isfile(candidate):
            return candidate
    return ""


def cmd_sitemap(args):
    apply_project_defaults(args)
    pages = _load(args)
    manifest_path = os.path.join(args.root, MANIFEST)
    manifest = load_manifest(manifest_path)
    if manifest.pop("_broken", False):
        print(tr("  ! манифест был повреждён и прочитан как пустой — у всех страниц будет сегодняшний lastmod"))
    result = publish.build_sitemap(pages, args.out_dir or args.root, args.site,
                                   manifest=manifest,
                                   public_prefix=args.public_prefix)
    save_manifest(manifest_path, result["manifest"])
    print(tr("Включено: {a0}   Исключено (noindex, canonical, черновики): {a1}", a0=result['included'], a1=result['excluded']))
    if result["drafts"]:
        print(tr("  черновиков не опубликовано: {a0} (status: draft во фронтматтере)", a0=len(result['drafts'])))
    for path in result["files"]:
        print(f"  {path}")
    for path in result["removed"]:
        print(tr("  удалён устаревший шард: {a0}", a0=path))
    if args.out_dir and not args.public_prefix and result["included"] > publish.MAX_URLS_PER_FILE:
        print(tr("  ! шардов больше одного: если ./public не корень сайта, укажи --public-prefix, иначе индекс будет ссылаться не туда"))
    return 0


def cmd_notify(args):
    apply_project_defaults(args)
    pages = _load(args)
    key = publish.check_key(args.key)
    manifest_path = os.path.join(args.root, MANIFEST)
    manifest = load_manifest(manifest_path)
    if manifest.pop("_broken", False):
        print(tr("  ! манифест повреждён и прочитан как пустой — очередь считается с нуля."))
        print(tr("    С --send это отправит ВЕСЬ сайт. Если это не то, что нужно, восстанови .indexgap-manifest.json из истории."))
    diff = publish.diff_changed(pages, manifest)

    urls = diff["new"] + diff["changed"]
    print(tr("Новых: {a0}   Изменённых: {a1}   Без изменений: {a2}   Пропало: {a3}", a0=len(diff['new']), a1=len(diff['changed']), a2=len(diff['unchanged']), a3=len(diff['removed'])))
    if not urls:
        print(tr("Отправлять нечего."))
        return 0

    registry = engines.fetch_participants(offline=args.offline)
    names = ", ".join(sorted(registry["participants"]))
    print(tr("Получат уведомление ({a0}): {a1}", a0=registry['source'], a1=names))
    for note in engines.describe_coverage(list(registry["participants"])):
        print(tr("  не получат → {a0}", a0=note))

    if args.write_key:
        target = args.key_dir or args.out_dir
        if not target:
            print(tr("  ! --write-key без --key-dir: файл ключа должен лежать в КОРНЕ САЙТА, а не рядом с исходниками."))
            print(tr("    Укажи каталог публикации: --key-dir ./public"))
            return 1
        path = publish.write_key_file(target, key)
        print(tr("Файл ключа: {a0}", a0=path))
        print(tr("  он должен открываться как {a0}/{a1}.txt", a0=args.site.rstrip('/'), a1=key))

    outcome = publish.submit_indexnow(urls, args.site, key,
                                      key_location=args.key_location,
                                      dry_run=not args.send)
    for r in outcome["results"]:
        status = r.get("status")
        line = tr("  батч {a0}: {a1}", a0=r.get('batch'), a1=status)
        if r.get("error"):
            line += f" — {r['error']}"
        print(line)

    if not args.send:
        print(tr("Это пробный прогон: {a0} URL готовы к отправке. Чтобы отправить — добавь --send.", a0=len(urls)))
        return 0

    accepted = outcome["accepted"]
    if accepted:
        save_manifest(manifest_path,
                      publish.mark_notified(manifest, pages, accepted))
    if len(accepted) == len(urls):
        print(tr("Отправлено, очередь очищена."))
        return 0
    print(tr("Принято {a0} из {a1}. Принятые отмечены и повторно не поедут; остальные останутся в очереди.", a0=len(accepted), a1=len(urls)))
    return 1


def cmd_doctor(args):
    apply_project_defaults(args)
    pages = _load(args)
    project = settings.resolve(args.root, pages, explicit=args.config)
    analysis = checks.run_all(pages, home_url=_home_url(args, pages),
                              cfg=project.get("checks"),
                              language=project.get("language", ""))
    notes = list(analysis.get("notes") or [])

    sitemap_urls = None
    if args.sitemap:
        sm = doctor.read_sitemap(args.sitemap)
        if sm["error"]:
            raise SourceError(
                tr("sitemap не прочитан: {a0}\n    Пока он не читается, сверять не с чем — «потеряно всё» в такой ситуации было бы враньём.", a0=sm['error']))
        sitemap_urls = sm["urls"]
    by_engine, by_source = _collect_indexed(args)
    if sitemap_urls is None and not by_engine:
        raise SourceError(
            tr("Нужен хотя бы --sitemap или --indexed, иначе сверять не с чем.\n    --sitemap ./public/sitemap.xml\n    --indexed google=gsc.csv --indexed bing=bing.csv"))

    funnel_result = doctor.funnel(pages, sitemap_urls, None,
                                  by_engine=by_engine, by_source=by_source)
    causes = doctor.explain(funnel_result, analysis)
    cross = doctor.cross_engine(funnel_result, pages)

    print()
    for step in funnel_result["steps"]:
        lost = tr("  (потеряно {a0}: {a1})", a0=step['lost'], a1=step['why']) if step.get("lost") else ""
        print(f"  {step['name']:<28} {step['count']:>6}{lost}")

    if cross:
        print(tr("\nСравнение поисковиков:"))
        for c in cross:
            if c["count"]:
                print(f"  {c['count']:>5}  {c['kind']}")
                print(f"         {c['note']}")

    for note in funnel_result.get("foreign") or ():
        print(f"\n  ! {note}")

    if causes:
        print(tr("\nПочему страницы не в индексе:"))
        for c in causes:
            print(f"  {c['count']:>5}  {c['cause']}\n         → {c['fix']}")

    for note in notes:
        print(f"  ! {note}")

    path = report.build(analysis, funnel_result, causes,
                        out_path=check_out_path(args.out),
                        site=args.site, cross=cross, notes=notes,
                        title=tr("Разбор потерь"))
    json_path = os.path.splitext(args.out)[0] + ".json"
    _write_json(json_path, {"site": args.site, "funnel": funnel_result,
                            "causes": causes, "cross_engine": cross,
                            "notes": notes})
    print(tr("\nОтчёт: {a0}\nДанные: {a1}", a0=path, a1=json_path))
    print(tr("Проверки текста здесь не запускались — это делает `indexgap check`."))
    return 0


def cmd_plan(args):
    data = generate.read_dataset(args.dataset)
    rows, fields = data["rows"], data["fields"]
    for problem in data["problems"]:
        print(f"  ! {problem}")
    if data["encoding"] not in ("utf-8", "utf-8-sig"):
        print(tr("  ! файл прочитан как {a0}; для надёжности пересохрани его в UTF-8", a0=data['encoding']))
    if not rows:
        raise SourceError(tr("{a0}: ни одной строки с данными.", a0=args.dataset))
    resolve_keyword_field(args, fields, args.dataset)

    generate.check_pattern(args.pattern, fields)

    cfg = {"min_fields_filled": args.min_filled} if args.min_filled else None
    audit = generate.audit_dataset(rows, fields, args.keyword, cfg)
    print(tr("Строк в датасете: {a0}", a0=audit['total']))
    print(tr("К генерации:      {a0}", a0=len(audit['keep'])))
    print(tr("Отбраковано:      {a0}", a0=len(audit['rejected'])))
    reasons = {}
    for r in audit["rejected"]:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>5}  {reason}")
    for warning in audit["warnings"]:
        print(f"  ! {warning}")
    if audit["near_synonyms"]:
        print(tr("\nОдин интент, разные формулировки (показаны первые 10 из {a0}):", a0=len(audit['near_synonyms'])))
        for a, b, _ in audit["near_synonyms"][:10]:
            print(f"    «{a}»  ↔  «{b}»")
        print(tr("    Оставлена первая. Если это разные страницы — поправь ключи."))

    if args.json:
        _write_json(args.json, {
            "total": audit["total"],
            "keep": [{"row": i + 2, "keyword": k, "slug": s} for i, k, s, _ in audit["keep"]],
            "rejected": audit["rejected"],
            "near_synonyms": [{"kept": a, "dropped": b} for a, b, _ in audit["near_synonyms"]],
            "warnings": audit["warnings"],
        })
        print(tr("Разбор целиком: {a0}", a0=args.json))

    if args.write:
        brief = generate.DEFAULT_BRIEF
        if args.brief:
            from .core import read_text
            brief, _ = read_text(args.brief)
        result = generate.write_tasks(audit, args.out_dir, args.keyword,
                                      path_pattern=args.pattern,
                                      brief=brief,
                                      min_words=args.min_words)
        print(tr("\nСоздано заготовок: {a0} в {a1}", a0=len(result['written']), a1=args.out_dir))
        if result["skipped"]:
            print(tr("Пропущено (файл уже есть): {a0}", a0=len(result['skipped'])))
        for failure in result["failed"][:10]:
            print(f"  ! «{failure['keyword']}»: {failure['reason']}")
        if result["failed"]:
            print(tr("  Не записано строк: {a0}", a0=len(result['failed'])))
        if result["written"]:
            print(tr("Дальше: попроси агента заполнить их по брифу внутри каждого файла."))
    else:
        print(tr("\nЭто разбор без записи. Чтобы создать заготовки — добавь --write."))
    return 0


def cmd_init(args):
    """Установка в проект: скиллы для агента и конфиг с тем, что отличает проект."""
    result = install.run(args.dir, site=args.site, content=args.content,
                         profile=args.profile, dataset=args.dataset,
                         force=args.force, agents=args.agents)
    d = result["detected"]

    print(tr("Проект: {a0}\n", a0=result['root']))
    print(tr("Что понято про проект:"))
    print(tr("  страницы   {a0}", a0=d['content'])
          + (tr("   (угадано — проверь)") if d["content_guessed"] else ""))
    print(tr("  сайт       {a0}", a0=d['site'] or 'НЕ НАЙДЕН — впиши в indexgap.json')
          + (tr("   (угадано — проверь)") if d["site"] and d["site_guessed"] else ""))
    print(tr("  тип        {a0}   ({a1})", a0=d['profile'], a1=d['profile_why']))
    if d["dataset"]:
        print(tr("  датасет    {a0}", a0=d['dataset']))
    else:
        print(tr("  датасет    не найден — сверка фактов работать не будет"))

    print(tr("\nЧто установлено:"))
    for path in result["skills"]:
        print(f"  {path}")
    print(f"  {os.path.basename(result['config'])}"
          + ("" if result["config_written"] else tr("   (уже был, не тронут)")))
    if result["gitignore"]:
        print(tr("  .gitignore — дописаны служебные файлы"))
    if result["agents"]:
        print(tr("  {a0} — блок для Codex", a0=os.path.basename(result['agents'])))

    print(tr("\nСкиллы подхватит агент в этом проекте: Claude Code читает .claude/skills сам."))
    if not result["agents"]:
        print(tr("Если работаешь в Codex — добавь блок в AGENTS.md: `indexgap init --agents`"))

    if not d["site"]:
        print(tr("\n! Адрес сайта определить не удалось. Впиши его в indexgap.json полем `site`, иначе проверять нечего."))
        return 1

    print(tr("\nСледующая команда:"))
    dataset = f" --dataset {d['dataset']}" if d["dataset"] else ""
    print(f"  indexgap check {d['content']} --site {d['site'].rstrip('/')}{dataset}")
    if args.key:
        key = install.new_indexnow_key()
        print(tr("\nНовый ключ IndexNow для ЭТОГО проекта: {a0}", a0=key))
        print(tr("  Он привязан к домену файлом в корне сайта. Ключ от другого проекта здесь не сработает — протокол ответит 403."))
        print(tr("  indexgap notify {a0} --site {a1} --key {a2} --write-key --key-dir <каталог публикации>", a0=d['content'], a1=d['site'].rstrip('/'), a2=key))
    return 0


def cmd_portfolio(args):
    specs = portfolio.read_portfolio(args.portfolio)
    print(tr("Проектов в портфеле: {a0}", a0=len(specs)))
    results = []
    for spec in specs:
        if not spec.get("out") and args.reports:
            spec["out"] = os.path.join(args.reports, f"{spec['name']}.html")
        result = portfolio.run_one(spec)
        results.append(result)
        if result["error"]:
            print(f"  ✗ {spec['name']}: {result['error'].splitlines()[0]}")
            continue
        counts = result["counts"]
        print(tr("  · {a0:<20} {a1:>6} стр.  критично {a2:>4}  внимание {a3:>4}  [{a4}]", a0=spec['name'], a1=result['pages'], a2=counts.get('critical', 0), a3=counts.get('warning', 0), a4=result['profile']))

    patterns = portfolio.common_patterns(results)
    uniques = portfolio.unique_findings(results)

    page_patterns = [p for p in patterns if p.get("scope", "page") == "page"]
    site_patterns = [p for p in patterns if p.get("scope") == "site"]
    if page_patterns:
        print(tr("\nОбщие грабли на страницах (доля страниц проекта):"))
        for p in page_patterns[:10]:
            shares = ", ".join(f"{n} {p['detail'][n]['share']:.0%}" for n in p["projects"])
            mark = tr("  ← похоже на непонастроенный порог") if p.get("threshold_suspect") else ""
            print(tr("  {a0:<24} {a1} проекта: {a2}{a3}", a0=p['code'], a1=p['project_count'], a2=shares, a3=mark))
        if any(p.get("threshold_suspect") for p in page_patterns):
            print(tr("    Порог, срабатывающий почти на всех страницах всех проектов, —\n    это вопрос к порогу, а не к страницам. Правится в indexgap.json\n    или профилем: `indexgap profiles`."))
    else:
        print(tr("\nНи одна страничная находка не повторилась в двух проектах."))
    if site_patterns:
        print(tr("\nОбщее в настройке сайтов:"))
        for p in site_patterns[:6]:
            print(f"  {p['code']:<24} {', '.join(p['projects'])}")

    path = report.build_portfolio(results, patterns, uniques, out_path=args.out)
    json_path = os.path.splitext(args.out)[0] + ".json"
    _write_json(json_path, {
        "projects": [{k: v for k, v in r.items() if k != "issues"} for r in results],
        "patterns": patterns,
        "unique": uniques,
    })
    print(tr("\nСводный отчёт: {a0}\nДанные: {a1}", a0=path, a1=json_path))
    failed = [r for r in results if r["error"]]
    if failed:
        print(tr("Не проверено проектов: {a0}", a0=len(failed)))
    total_critical = sum((r.get("counts") or {}).get("critical", 0) for r in results)
    return 1 if (args.strict and (failed or total_critical)) else 0


def cmd_profiles(args):
    print(tr("Профили типов контента:\n"))
    for name in sorted(profiles.PROFILES):
        profile = profiles.PROFILES[name]
        print(f"  {name}  —  {profile['title']}")
        print(f"      {profile['about']}")
        for note in profile["notes"]:
            print(f"      · {note}")
        print()
    return 0


# ── разбор аргументов ─────────────────────────────────────────────────────────

def preset_language(argv=None):
    """
    Язык надо знать ДО того, как построен разборщик аргументов.

    Тексты `--help` вычисляются в момент сборки парсера, то есть раньше, чем
    argparse доберётся до `--lang`. Поэтому флаг вычитывается из argv руками:
    иначе `indexgap --lang en check --help` печатал бы русскую справку.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    lang = ""
    for i, item in enumerate(argv):
        if item.startswith("--lang="):
            lang = item.split("=", 1)[1]
        elif item == "--lang" and i + 1 < len(argv):
            lang = argv[i + 1]
    return i18n.set_lang(lang)


def build_parser():
    ap = argparse.ArgumentParser(
        prog="indexgap", description=tr("Контроль качества programmatic-конвейера"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("root", nargs="?", default="",
                       help=tr("каталог со страницами; по умолчанию из indexgap.json"))
        p.add_argument("--site", default="",
                       help=tr("адрес сайта целиком; по умолчанию из indexgap.json"))
        p.add_argument("--home", help=tr("URL главной; по умолчанию — сам --site"))
        p.add_argument("--config", default="",
                       help=tr("путь к indexgap.json; по умолчанию ищется рядом со страницами"))
        p.add_argument("--profile", default="",
                       help=tr("тип контента: catalog, events, ugc, product. Меняет пороги и набор проверок — см. `indexgap profiles`"))

    p = sub.add_parser("init",
                       help=tr("установить в проект: скиллы для агента и конфиг"))
    p.add_argument("dir", nargs="?", default=".", help=tr("каталог проекта"))
    p.add_argument("--site", default="", help=tr("адрес сайта, если определить не удалось"))
    p.add_argument("--content", default="", help=tr("каталог со страницами"))
    p.add_argument("--profile", default="",
                   help=tr("тип контента: catalog, events, ugc, product"))
    p.add_argument("--dataset", default="", help=tr("CSV с семантикой"))
    p.add_argument("--key", action="store_true",
                   help=tr("сгенерировать новый ключ IndexNow для этого проекта"))
    p.add_argument("--agents", action="store_true",
                   help=tr("создать AGENTS.md для Codex, если его нет"))
    p.add_argument("--force", action="store_true",
                   help=tr("перезаписать существующий indexgap.json"))
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("plan", help=tr("разобрать семантику и разложить заготовки под генерацию"))
    p.add_argument("dataset", help=tr("CSV с семантикой"))
    p.add_argument("--keyword", default="keyword", help=tr("колонка с ключом"))
    p.add_argument("--out-dir", default="content", help=tr("куда класть заготовки"))
    p.add_argument("--pattern", default="{slug}/index.md", help=tr("шаблон пути"))
    p.add_argument("--min-words", type=int, default=350)
    p.add_argument("--min-filled", type=float, default=0.0,
                   help=tr("доля заполненных колонок, ниже которой строка отбраковывается (по умолчанию 0 — не отбраковывать)"))
    p.add_argument("--brief", help=tr("файл со своим шаблоном брифа вместо стандартного"))
    p.add_argument("--json", help=tr("куда записать разбор целиком"))
    p.add_argument("--write", action="store_true", help=tr("действительно создать файлы"))
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("check", help=tr("все локальные проверки и отчёт"))
    common(p)
    p.add_argument("--sitemap", help=tr("путь или URL sitemap.xml для сверки"))
    p.add_argument("--indexed", action="append", metavar=tr("[источник=]файл"),
                   help=tr("выгрузка со списком страниц: панель вебмастера, Ahrefs, Semrush, Screaming Frog, GA4 и другие. CSV, XLSX, JSON или список адресов. Можно указывать несколько раз: --indexed google=gsc.csv --indexed ahrefs=pages.xlsx. Источник определяется сам; метка нужна, когда имя файла ни о чём не говорит"))
    p.add_argument("--gsc", help=tr("то же, что --indexed google=... (для совместимости)"))
    p.add_argument("--out", default="indexgap-check.html")
    p.add_argument("--dataset", help=tr("семантика (CSV или XLSX) — включает сверку фактов с данными строк"))
    p.add_argument("--keyword", default="keyword", help=tr("колонка с ключом в датасете"))
    p.add_argument("--robots", help=tr("путь к robots.txt проекта"))
    p.add_argument("--no-content", action="store_true", help=tr("пропустить проверки текста"))
    p.add_argument("--no-aeo", action="store_true",
                   help=tr("пропустить проверки машинной читаемости"))
    p.add_argument("--strict", action="store_true",
                   help=tr("ненулевой код возврата при критичных находках — для CI"))
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("sitemap", help=tr("собрать sitemap с шардингом и честным lastmod"))
    common(p)
    p.add_argument("--out-dir", help=tr("куда писать; по умолчанию рядом со страницами"))
    p.add_argument("--public-prefix", default="",
                   help=tr("путь, по которому файлы будут доступны на сайте, если --out-dir не корень публикации"))
    p.set_defaults(func=cmd_sitemap)

    p = sub.add_parser("notify", help=tr("сообщить об изменившихся страницах через IndexNow"))
    common(p)
    p.add_argument("--key", required=True,
                   help=tr("ключ IndexNow: 8–128 символов латиницы и цифр, который ты придумываешь сам"))
    p.add_argument("--key-location", help=tr("URL файла ключа, если он не в корне"))
    p.add_argument("--out-dir", help=tr("каталог публикации"))
    p.add_argument("--key-dir", help=tr("куда положить файл ключа — это КОРЕНЬ САЙТА"))
    p.add_argument("--write-key", action="store_true", help=tr("создать файл ключа"))
    p.add_argument("--send", action="store_true",
                   help=tr("действительно отправить; без него — пробный прогон"))
    p.add_argument("--offline", action="store_true",
                   help=tr("не ходить за реестром участников, взять встроенный список"))
    p.set_defaults(func=cmd_notify)

    p = sub.add_parser("portfolio",
                       help=tr("один прогон по нескольким проектам и сводный разбор"))
    p.add_argument("portfolio", help=tr("JSON с описанием проектов"))
    p.add_argument("--out", default="indexgap-portfolio.html")
    p.add_argument("--reports", default="",
                   help=tr("каталог для отдельных отчётов по каждому проекту"))
    p.add_argument("--strict", action="store_true",
                   help=tr("ненулевой код возврата при критичных находках — для CI"))
    p.set_defaults(func=cmd_portfolio)

    p = sub.add_parser("profiles", help=tr("какие бывают типы контента и чем отличаются"))
    p.set_defaults(func=cmd_profiles)

    p = sub.add_parser("doctor", help=tr("воронка: сгенерировано → sitemap → индексы поисковиков"))
    common(p)
    p.add_argument("--sitemap", help=tr("путь или URL sitemap.xml"))
    p.add_argument("--indexed", action="append", metavar=tr("[движок=]файл.csv"),
                   help=tr("выгрузка индексации; несколько раз для разных поисковиков"))
    p.add_argument("--gsc", help=tr("то же, что --indexed google=... (для совместимости)"))
    p.add_argument("--out", default="indexgap-doctor.html")
    p.set_defaults(func=cmd_doctor)
    ap._subparsers_map = dict(sub.choices)
    return ap


def main(argv=None):
    _setup_output()
    preset_language(argv)
    parser = build_parser()
    # `--lang` принимается и до команды, и после неё: человек пишет
    # `indexgap --lang en check` и `indexgap check --lang en` примерно поровну.
    lang_help = tr("язык вывода: en или ru. По умолчанию — из INDEXGAP_LANG "
                   "или системной локали, иначе английский")
    parser.add_argument("--lang", choices=i18n.LANGS, help=lang_help)
    for subparser in getattr(parser, "_subparsers_map", {}).values():
        subparser.add_argument("--lang", choices=i18n.LANGS, help=lang_help)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SourceError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        # `indexgap check … | head` — обычная идиома. Отчёт на диск уже записан,
        # и ненулевой код агент прочитает как «команда упала».
        try:
            sys.stdout.close()
        except Exception:                      # noqa: BLE001
            pass
        return 0
    except KeyboardInterrupt:
        print(tr("\nПрервано."), file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
