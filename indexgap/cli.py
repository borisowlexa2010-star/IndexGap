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
            f"{path} не читается: {exc}.\n"
            f"    Это файл настроек проекта. Поправь его или удали "
            f"и запусти `indexgap init` заново.")
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
            "Не хватает данных о проекте.\n"
            "    Либо укажи их явно: indexgap check ./content --site https://example.com\n"
            "    Либо один раз выполни `indexgap init` в корне проекта — тогда\n"
            "    ежедневная команда станет просто `indexgap check`.")
    site = check_site_url(args.site)
    args.site = site
    pages, problems = load_pages(args.root, site)
    for problem in problems:
        print(f"  ! {problem}")
    if not pages:
        if not os.path.exists(args.root):
            raise SourceError(f"Каталога {args.root} нет. Проверь путь.")
        if os.path.isfile(args.root):
            raise SourceError(f"{args.root} — это файл, а нужен каталог со страницами.")
        raise SourceError(
            f"В {args.root} нет ни одной страницы (.html, .htm, .md, .markdown).\n"
            f"    Если страницы лежат глубже — укажи нужный подкаталог.")
    print(f"Разобрано страниц: {len(pages)}")
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
        raise SourceError(f"--out {path} — это каталог. Укажи имя файла, "
                          f"например {os.path.join(path, 'indexgap-check.html')}")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                head = fh.read(4096)
        except OSError:
            head = ""
        if REPORT_MARK not in head:
            raise SourceError(
                f"--out {path} уже существует и это не отчёт пакета.\n"
                f"    Перезаписывать чужой файл я не буду — укажи другое имя.")
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
            f"Колонки «{args.keyword}» в {path} нет.\n"
            f"    Есть: {', '.join(fields)}\n"
            f"    Укажи нужную: --keyword <имя колонки>")
    guess = sources.guess_column(fields, sources.KEYWORD_COLUMN_HINTS)
    if guess >= 0:
        found = fields[guess]
        print(f"  ! колонка с ключом не названа `keyword` — взята «{found}». "
              f"Если это не она, укажи явно: --keyword <имя колонки>")
        args.keyword = found
        return found
    raise SourceError(
        f"Колонки с ключевым словом в {path} не нашлось.\n"
        f"    Есть: {', '.join(fields)}\n"
        f"    Укажи нужную: --keyword <имя колонки>")


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
        print(f"Индексация — {summary}")
    if by_source:
        summary = ", ".join(
            f"{n} ({sources.KIND_TITLE[sources.kind_of(n)]}): {len(u)}"
            for n, u in sorted(by_source.items()))
        print(f"Прочие источники — {summary}")
    for line in sources.describe(list(by_engine) + list(by_source)):
        print(f"  что это доказывает → {line}")
    for note in engines.describe_coverage(list(by_engine)):
        print(f"  не покрыто → {note}")
    return by_engine, by_source


def _describe_project(project: dict, rows: list) -> None:
    """Показывает, что пакет понял про проект. Молчаливая автонастройка опаснее явной."""
    parts = []
    language = project.get("language")
    parts.append(f"язык: {language or 'не определён'}")
    units = project.get("fact_units") or []
    if units:
        origin = "из датасета" if project.get("_derived_units") else "из конфига"
        parts.append(f"единицы фактов ({origin}): {', '.join(units[:8])}"
                     + (" …" if len(units) > 8 else ""))
    elif rows:
        parts.append("единиц измерения в датасете нет — сверка идёт по всем числам")
    if project.get("_path"):
        parts.append(f"конфиг: {os.path.basename(project['_path'])}")
    print("Проект — " + "; ".join(parts))


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
    print(f"Профиль — {project['_profile_title']} ({project['_profile']})")

    analysis = checks.run_all(pages, home_url=_home_url(args, pages),
                              cfg=project.get("checks"),
                              language=project.get("language", ""))
    notes = list(analysis.get("notes") or [])

    content_result = None
    if project["_skip_facts"]:
        notes.append("сверка фактов и швов шаблона выключена профилем "
                     f"«{project['_profile']}»: страницы не порождаются датасетом, "
                     "сверять не с чем. Молчание здесь — не «всё хорошо»")
    elif not args.no_content:
        cfg = dict(project.get("content") or {})
        cfg["vague_anchors"] = project.get("vague_anchors", [])
        content_result = content.run(pages, rows, args.keyword, args.root,
                                     cfg=cfg, fact_units=project.get("fact_units"))
        analysis["issues"] += content_result["issues"]
        notes += content_result.get("notes") or []
        if rows:
            print(f"Сверено с датасетом: {content_result['matched_rows']} из {len(pages)}")
            if content_result["unmatched"]:
                print(f"  не сопоставлено: {len(content_result['unmatched'])} "
                      f"(проверь keyword во фронтматтере или имена папок)")

    if project["_checks_freshness"]:
        fresh = freshness.check(pages)
        analysis["issues"] += fresh["issues"]
        print(f"Датировано страниц: {fresh['dated']} из {len(pages)}"
              + (f", просрочено {fresh['stale']}" if fresh["stale"] else ""))
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
            print(f"  ! sitemap не прочитан: {sm['error']}")
            print("    Сверка с sitemap пропущена — это не значит, что страниц в нём нет.")
        else:
            sitemap_urls = sm["urls"]
    if sitemap_urls is not None or by_engine or by_source:
        funnel_result = doctor.funnel(pages, sitemap_urls, None,
                                      by_engine=by_engine, by_source=by_source)
        causes = doctor.explain(funnel_result, analysis)
        cross = doctor.cross_engine(funnel_result, pages)

    analysis["issues"] = checks.sort_issues(analysis["issues"])
    notes += checks.template_wide(analysis["issues"], len(pages))

    html_path = report.build(analysis, funnel_result, causes,
                             out_path=check_out_path(args.out), site=args.site,
                             cross=cross, notes=notes,
                             title="Проверка перед публикацией")
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
    print(f"Критично: {crit}   Внимание: {warn}   "
          f"Сирот: {reported}   "
          f"Похожих пар: {len(analysis['duplicates'])}")
    _print_first_things(analysis["issues"])
    print(f"Отчёт: {html_path}\nДанные: {json_path}")
    return 1 if (crit and args.strict) else 0


def _print_first_things(issues):
    """Три числа, с которых начинают. Скилл обещает их — теперь они есть."""
    from collections import Counter
    counts = Counter(code for level, _, code, _ in issues if level == "critical")
    if not counts:
        return
    print("Чинить в этом порядке:")
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
        print("  ! манифест был повреждён и прочитан как пустой — "
              "у всех страниц будет сегодняшний lastmod")
    result = publish.build_sitemap(pages, args.out_dir or args.root, args.site,
                                   manifest=manifest,
                                   public_prefix=args.public_prefix)
    save_manifest(manifest_path, result["manifest"])
    print(f"Включено: {result['included']}   "
          f"Исключено (noindex, canonical, черновики): {result['excluded']}")
    if result["drafts"]:
        print(f"  черновиков не опубликовано: {len(result['drafts'])} "
              f"(status: draft во фронтматтере)")
    for path in result["files"]:
        print(f"  {path}")
    for path in result["removed"]:
        print(f"  удалён устаревший шард: {path}")
    if args.out_dir and not args.public_prefix and result["included"] > publish.MAX_URLS_PER_FILE:
        print("  ! шардов больше одного: если ./public не корень сайта, "
              "укажи --public-prefix, иначе индекс будет ссылаться не туда")
    return 0


def cmd_notify(args):
    apply_project_defaults(args)
    pages = _load(args)
    key = publish.check_key(args.key)
    manifest_path = os.path.join(args.root, MANIFEST)
    manifest = load_manifest(manifest_path)
    if manifest.pop("_broken", False):
        print("  ! манифест повреждён и прочитан как пустой — очередь считается "
              "с нуля.")
        print("    С --send это отправит ВЕСЬ сайт. Если это не то, что нужно, "
              "восстанови .indexgap-manifest.json из истории.")
    diff = publish.diff_changed(pages, manifest)

    urls = diff["new"] + diff["changed"]
    print(f"Новых: {len(diff['new'])}   Изменённых: {len(diff['changed'])}   "
          f"Без изменений: {len(diff['unchanged'])}   Пропало: {len(diff['removed'])}")
    if not urls:
        print("Отправлять нечего.")
        return 0

    registry = engines.fetch_participants(offline=args.offline)
    names = ", ".join(sorted(registry["participants"]))
    print(f"Получат уведомление ({registry['source']}): {names}")
    for note in engines.describe_coverage(list(registry["participants"])):
        print(f"  не получат → {note}")

    if args.write_key:
        target = args.key_dir or args.out_dir
        if not target:
            print("  ! --write-key без --key-dir: файл ключа должен лежать в КОРНЕ САЙТА, "
                  "а не рядом с исходниками.")
            print("    Укажи каталог публикации: --key-dir ./public")
            return 1
        path = publish.write_key_file(target, key)
        print(f"Файл ключа: {path}")
        print(f"  он должен открываться как {args.site.rstrip('/')}/{key}.txt")

    outcome = publish.submit_indexnow(urls, args.site, key,
                                      key_location=args.key_location,
                                      dry_run=not args.send)
    for r in outcome["results"]:
        status = r.get("status")
        line = f"  батч {r.get('batch')}: {status}"
        if r.get("error"):
            line += f" — {r['error']}"
        print(line)

    if not args.send:
        print(f"Это пробный прогон: {len(urls)} URL готовы к отправке. "
              f"Чтобы отправить — добавь --send.")
        return 0

    accepted = outcome["accepted"]
    if accepted:
        save_manifest(manifest_path,
                      publish.mark_notified(manifest, pages, accepted))
    if len(accepted) == len(urls):
        print("Отправлено, очередь очищена.")
        return 0
    print(f"Принято {len(accepted)} из {len(urls)}. Принятые отмечены и повторно "
          f"не поедут; остальные останутся в очереди.")
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
                f"sitemap не прочитан: {sm['error']}\n"
                f"    Пока он не читается, сверять не с чем — «потеряно всё» "
                f"в такой ситуации было бы враньём.")
        sitemap_urls = sm["urls"]
    by_engine, by_source = _collect_indexed(args)
    if sitemap_urls is None and not by_engine:
        raise SourceError(
            "Нужен хотя бы --sitemap или --indexed, иначе сверять не с чем.\n"
            "    --sitemap ./public/sitemap.xml\n"
            "    --indexed google=gsc.csv --indexed bing=bing.csv")

    funnel_result = doctor.funnel(pages, sitemap_urls, None,
                                  by_engine=by_engine, by_source=by_source)
    causes = doctor.explain(funnel_result, analysis)
    cross = doctor.cross_engine(funnel_result, pages)

    print()
    for step in funnel_result["steps"]:
        lost = f"  (потеряно {step['lost']}: {step['why']})" if step.get("lost") else ""
        print(f"  {step['name']:<28} {step['count']:>6}{lost}")

    if cross:
        print("\nСравнение поисковиков:")
        for c in cross:
            if c["count"]:
                print(f"  {c['count']:>5}  {c['kind']}")
                print(f"         {c['note']}")

    for note in funnel_result.get("foreign") or ():
        print(f"\n  ! {note}")

    if causes:
        print("\nПочему страницы не в индексе:")
        for c in causes:
            print(f"  {c['count']:>5}  {c['cause']}\n         → {c['fix']}")

    for note in notes:
        print(f"  ! {note}")

    path = report.build(analysis, funnel_result, causes,
                        out_path=check_out_path(args.out),
                        site=args.site, cross=cross, notes=notes,
                        title="Разбор потерь")
    json_path = os.path.splitext(args.out)[0] + ".json"
    _write_json(json_path, {"site": args.site, "funnel": funnel_result,
                            "causes": causes, "cross_engine": cross,
                            "notes": notes})
    print(f"\nОтчёт: {path}\nДанные: {json_path}")
    print("Проверки текста здесь не запускались — это делает `indexgap check`.")
    return 0


def cmd_plan(args):
    data = generate.read_dataset(args.dataset)
    rows, fields = data["rows"], data["fields"]
    for problem in data["problems"]:
        print(f"  ! {problem}")
    if data["encoding"] not in ("utf-8", "utf-8-sig"):
        print(f"  ! файл прочитан как {data['encoding']}; для надёжности "
              f"пересохрани его в UTF-8")
    if not rows:
        raise SourceError(f"{args.dataset}: ни одной строки с данными.")
    resolve_keyword_field(args, fields, args.dataset)

    generate.check_pattern(args.pattern, fields)

    cfg = {"min_fields_filled": args.min_filled} if args.min_filled else None
    audit = generate.audit_dataset(rows, fields, args.keyword, cfg)
    print(f"Строк в датасете: {audit['total']}")
    print(f"К генерации:      {len(audit['keep'])}")
    print(f"Отбраковано:      {len(audit['rejected'])}")
    reasons = {}
    for r in audit["rejected"]:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>5}  {reason}")
    for warning in audit["warnings"]:
        print(f"  ! {warning}")
    if audit["near_synonyms"]:
        print(f"\nОдин интент, разные формулировки "
              f"(показаны первые 10 из {len(audit['near_synonyms'])}):")
        for a, b, _ in audit["near_synonyms"][:10]:
            print(f"    «{a}»  ↔  «{b}»")
        print("    Оставлена первая. Если это разные страницы — поправь ключи.")

    if args.json:
        _write_json(args.json, {
            "total": audit["total"],
            "keep": [{"row": i + 2, "keyword": k, "slug": s} for i, k, s, _ in audit["keep"]],
            "rejected": audit["rejected"],
            "near_synonyms": [{"kept": a, "dropped": b} for a, b, _ in audit["near_synonyms"]],
            "warnings": audit["warnings"],
        })
        print(f"Разбор целиком: {args.json}")

    if args.write:
        brief = generate.DEFAULT_BRIEF
        if args.brief:
            from .core import read_text
            brief, _ = read_text(args.brief)
        result = generate.write_tasks(audit, args.out_dir, args.keyword,
                                      path_pattern=args.pattern,
                                      brief=brief,
                                      min_words=args.min_words)
        print(f"\nСоздано заготовок: {len(result['written'])} в {args.out_dir}")
        if result["skipped"]:
            print(f"Пропущено (файл уже есть): {len(result['skipped'])}")
        for failure in result["failed"][:10]:
            print(f"  ! «{failure['keyword']}»: {failure['reason']}")
        if result["failed"]:
            print(f"  Не записано строк: {len(result['failed'])}")
        if result["written"]:
            print("Дальше: попроси агента заполнить их по брифу внутри каждого файла.")
    else:
        print("\nЭто разбор без записи. Чтобы создать заготовки — добавь --write.")
    return 0


def cmd_init(args):
    """Установка в проект: скиллы для агента и конфиг с тем, что отличает проект."""
    result = install.run(args.dir, site=args.site, content=args.content,
                         profile=args.profile, dataset=args.dataset,
                         force=args.force, agents=args.agents)
    d = result["detected"]

    print(f"Проект: {result['root']}\n")
    print("Что понято про проект:")
    print(f"  страницы   {d['content']}"
          + ("   (угадано — проверь)" if d["content_guessed"] else ""))
    print(f"  сайт       {d['site'] or 'НЕ НАЙДЕН — впиши в indexgap.json'}"
          + ("   (угадано — проверь)" if d["site"] and d["site_guessed"] else ""))
    print(f"  тип        {d['profile']}   ({d['profile_why']})")
    if d["dataset"]:
        print(f"  датасет    {d['dataset']}")
    else:
        print("  датасет    не найден — сверка фактов работать не будет")

    print("\nЧто установлено:")
    for path in result["skills"]:
        print(f"  {path}")
    print(f"  {os.path.basename(result['config'])}"
          + ("" if result["config_written"] else "   (уже был, не тронут)"))
    if result["gitignore"]:
        print("  .gitignore — дописаны служебные файлы")
    if result["agents"]:
        print(f"  {os.path.basename(result['agents'])} — блок для Codex")

    print("\nСкиллы подхватит агент в этом проекте: Claude Code читает "
          ".claude/skills сам.")
    if not result["agents"]:
        print("Если работаешь в Codex — добавь блок в AGENTS.md: "
              "`indexgap init --agents`")

    if not d["site"]:
        print("\n! Адрес сайта определить не удалось. Впиши его в indexgap.json "
              "полем `site`, иначе проверять нечего.")
        return 1

    print("\nСледующая команда:")
    dataset = f" --dataset {d['dataset']}" if d["dataset"] else ""
    print(f"  indexgap check {d['content']} --site {d['site'].rstrip('/')}{dataset}")
    if args.key:
        key = install.new_indexnow_key()
        print(f"\nНовый ключ IndexNow для ЭТОГО проекта: {key}")
        print("  Он привязан к домену файлом в корне сайта. Ключ от другого "
              "проекта здесь не сработает — протокол ответит 403.")
        print(f"  indexgap notify {d['content']} --site {d['site'].rstrip('/')} "
              f"--key {key} --write-key --key-dir <каталог публикации>")
    return 0


def cmd_portfolio(args):
    specs = portfolio.read_portfolio(args.portfolio)
    print(f"Проектов в портфеле: {len(specs)}")
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
        print(f"  · {spec['name']:<20} {result['pages']:>6} стр.  "
              f"критично {counts.get('critical', 0):>4}  "
              f"внимание {counts.get('warning', 0):>4}  "
              f"[{result['profile']}]")

    patterns = portfolio.common_patterns(results)
    uniques = portfolio.unique_findings(results)

    page_patterns = [p for p in patterns if p.get("scope", "page") == "page"]
    site_patterns = [p for p in patterns if p.get("scope") == "site"]
    if page_patterns:
        print("\nОбщие грабли на страницах (доля страниц проекта):")
        for p in page_patterns[:10]:
            shares = ", ".join(f"{n} {p['detail'][n]['share']:.0%}" for n in p["projects"])
            mark = "  ← похоже на непонастроенный порог" if p.get("threshold_suspect") else ""
            print(f"  {p['code']:<24} {p['project_count']} проекта: {shares}{mark}")
        if any(p.get("threshold_suspect") for p in page_patterns):
            print("    Порог, срабатывающий почти на всех страницах всех проектов, —"
                  "\n    это вопрос к порогу, а не к страницам. Правится в indexgap.json"
                  "\n    или профилем: `indexgap profiles`.")
    else:
        print("\nНи одна страничная находка не повторилась в двух проектах.")
    if site_patterns:
        print("\nОбщее в настройке сайтов:")
        for p in site_patterns[:6]:
            print(f"  {p['code']:<24} {', '.join(p['projects'])}")

    path = report.build_portfolio(results, patterns, uniques, out_path=args.out)
    json_path = os.path.splitext(args.out)[0] + ".json"
    _write_json(json_path, {
        "projects": [{k: v for k, v in r.items() if k != "issues"} for r in results],
        "patterns": patterns,
        "unique": uniques,
    })
    print(f"\nСводный отчёт: {path}\nДанные: {json_path}")
    failed = [r for r in results if r["error"]]
    if failed:
        print(f"Не проверено проектов: {len(failed)}")
    total_critical = sum((r.get("counts") or {}).get("critical", 0) for r in results)
    return 1 if (args.strict and (failed or total_critical)) else 0


def cmd_profiles(args):
    print("Профили типов контента:\n")
    for name in sorted(profiles.PROFILES):
        profile = profiles.PROFILES[name]
        print(f"  {name}  —  {profile['title']}")
        print(f"      {profile['about']}")
        for note in profile["notes"]:
            print(f"      · {note}")
        print()
    return 0


# ── разбор аргументов ─────────────────────────────────────────────────────────

def build_parser():
    ap = argparse.ArgumentParser(
        prog="indexgap", description="Контроль качества programmatic-конвейера")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("root", nargs="?", default="",
                       help="каталог со страницами; по умолчанию из indexgap.json")
        p.add_argument("--site", default="",
                       help="адрес сайта целиком; по умолчанию из indexgap.json")
        p.add_argument("--home", help="URL главной; по умолчанию — сам --site")
        p.add_argument("--config", default="",
                       help="путь к indexgap.json; по умолчанию ищется рядом со страницами")
        p.add_argument("--profile", default="",
                       help="тип контента: catalog, events, ugc, product. "
                            "Меняет пороги и набор проверок — см. `indexgap profiles`")

    p = sub.add_parser("init",
                       help="установить в проект: скиллы для агента и конфиг")
    p.add_argument("dir", nargs="?", default=".", help="каталог проекта")
    p.add_argument("--site", default="", help="адрес сайта, если определить не удалось")
    p.add_argument("--content", default="", help="каталог со страницами")
    p.add_argument("--profile", default="",
                   help="тип контента: catalog, events, ugc, product")
    p.add_argument("--dataset", default="", help="CSV с семантикой")
    p.add_argument("--key", action="store_true",
                   help="сгенерировать новый ключ IndexNow для этого проекта")
    p.add_argument("--agents", action="store_true",
                   help="создать AGENTS.md для Codex, если его нет")
    p.add_argument("--force", action="store_true",
                   help="перезаписать существующий indexgap.json")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("plan", help="разобрать семантику и разложить заготовки под генерацию")
    p.add_argument("dataset", help="CSV с семантикой")
    p.add_argument("--keyword", default="keyword", help="колонка с ключом")
    p.add_argument("--out-dir", default="content", help="куда класть заготовки")
    p.add_argument("--pattern", default="{slug}/index.md", help="шаблон пути")
    p.add_argument("--min-words", type=int, default=350)
    p.add_argument("--min-filled", type=float, default=0.0,
                   help="доля заполненных колонок, ниже которой строка отбраковывается "
                        "(по умолчанию 0 — не отбраковывать)")
    p.add_argument("--brief", help="файл со своим шаблоном брифа вместо стандартного")
    p.add_argument("--json", help="куда записать разбор целиком")
    p.add_argument("--write", action="store_true", help="действительно создать файлы")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("check", help="все локальные проверки и отчёт")
    common(p)
    p.add_argument("--sitemap", help="путь или URL sitemap.xml для сверки")
    p.add_argument("--indexed", action="append", metavar="[источник=]файл",
                   help="выгрузка со списком страниц: панель вебмастера, Ahrefs, "
                        "Semrush, Screaming Frog, GA4 и другие. CSV, XLSX, JSON "
                        "или список адресов. Можно указывать несколько раз: "
                        "--indexed google=gsc.csv --indexed ahrefs=pages.xlsx. "
                        "Источник определяется сам; метка нужна, когда имя файла "
                        "ни о чём не говорит")
    p.add_argument("--gsc", help="то же, что --indexed google=... (для совместимости)")
    p.add_argument("--out", default="indexgap-check.html")
    p.add_argument("--dataset", help="семантика (CSV или XLSX) — включает сверку фактов с данными строк")
    p.add_argument("--keyword", default="keyword", help="колонка с ключом в датасете")
    p.add_argument("--robots", help="путь к robots.txt проекта")
    p.add_argument("--no-content", action="store_true", help="пропустить проверки текста")
    p.add_argument("--no-aeo", action="store_true",
                   help="пропустить проверки машинной читаемости")
    p.add_argument("--strict", action="store_true",
                   help="ненулевой код возврата при критичных находках — для CI")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("sitemap", help="собрать sitemap с шардингом и честным lastmod")
    common(p)
    p.add_argument("--out-dir", help="куда писать; по умолчанию рядом со страницами")
    p.add_argument("--public-prefix", default="",
                   help="путь, по которому файлы будут доступны на сайте, "
                        "если --out-dir не корень публикации")
    p.set_defaults(func=cmd_sitemap)

    p = sub.add_parser("notify", help="сообщить об изменившихся страницах через IndexNow")
    common(p)
    p.add_argument("--key", required=True,
                   help="ключ IndexNow: 8–128 символов латиницы и цифр, "
                        "который ты придумываешь сам")
    p.add_argument("--key-location", help="URL файла ключа, если он не в корне")
    p.add_argument("--out-dir", help="каталог публикации")
    p.add_argument("--key-dir", help="куда положить файл ключа — это КОРЕНЬ САЙТА")
    p.add_argument("--write-key", action="store_true", help="создать файл ключа")
    p.add_argument("--send", action="store_true",
                   help="действительно отправить; без него — пробный прогон")
    p.add_argument("--offline", action="store_true",
                   help="не ходить за реестром участников, взять встроенный список")
    p.set_defaults(func=cmd_notify)

    p = sub.add_parser("portfolio",
                       help="один прогон по нескольким проектам и сводный разбор")
    p.add_argument("portfolio", help="JSON с описанием проектов")
    p.add_argument("--out", default="indexgap-portfolio.html")
    p.add_argument("--reports", default="",
                   help="каталог для отдельных отчётов по каждому проекту")
    p.add_argument("--strict", action="store_true",
                   help="ненулевой код возврата при критичных находках — для CI")
    p.set_defaults(func=cmd_portfolio)

    p = sub.add_parser("profiles", help="какие бывают типы контента и чем отличаются")
    p.set_defaults(func=cmd_profiles)

    p = sub.add_parser("doctor", help="воронка: сгенерировано → sitemap → индексы поисковиков")
    common(p)
    p.add_argument("--sitemap", help="путь или URL sitemap.xml")
    p.add_argument("--indexed", action="append", metavar="[движок=]файл.csv",
                   help="выгрузка индексации; несколько раз для разных поисковиков")
    p.add_argument("--gsc", help="то же, что --indexed google=... (для совместимости)")
    p.add_argument("--out", default="indexgap-doctor.html")
    p.set_defaults(func=cmd_doctor)
    return ap


def main(argv=None):
    _setup_output()
    args = build_parser().parse_args(argv)
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
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
