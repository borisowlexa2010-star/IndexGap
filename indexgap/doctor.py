# -*- coding: utf-8 -*-
"""
Сверка трёх множеств — ответ на вопрос «конвейер отработал, а трафика нет, почему».

    сгенерировано  →  попало в sitemap  →  попало в индекс  →  даёт показы

Каждый переход теряет страницы, и потери на разных переходах лечатся по-разному.
Без этой воронки причина не видна: в интерфейсе Search Console страницы просто
«обнаружены, но не проиндексированы», без объяснения.

Данные берутся из выгрузок, а не из API: никаких ключей и подписок. Панель
вебмастера — прямой источник, но её нет не у всех, поэтому читаются и выгрузки
из Ahrefs, Semrush, Screaming Frog, Sitebulb, GA4, Matomo и других — в CSV,
XLSX, JSON или просто списком адресов. Что каждый источник доказывает, а что
нет, разбирает `sources.py`, и подпись шага воронки меняется вместе
с источником: «хотя бы в одном индексе» и «известно Ahrefs» — разные строки.

Три вещи, исправленные после аудита:

  * **сравнение по ключу URL.** Search Console экспортирует кириллические
    адреса в процент-кодировании, и раньше ни один из них не сходился
    с адресом страницы: воронка показывала «в индексе 0» на живом сайте;
  * **никакого молчаливого нуля.** Нечитаемый sitemap рисовал «потеряно всё»,
    а неопознанная колонка URL просто убирала раздел индексации из отчёта.
    Теперь и то и другое — явное сообщение;
  * **экспорт «Страницы» из Search Console — это отчёт о показах**, а не
    об индексации. Страница в индексе без показов туда не попадает, и на новом
    сайте воронка систематически завышает потери. Об этом сказано вслух.
"""

from __future__ import annotations

import csv
import io
import os
import urllib.error
import urllib.request
from xml.etree import ElementTree

from . import sources
from .core import read_text, url_key, SourceError

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def _keys(urls) -> set:
    return {url_key(u) for u in urls if u}


def read_sitemap(source: str, _depth: int = 0, _seen: set = None) -> dict:
    """
    Читает sitemap с диска или по URL, разворачивает sitemap-index.

    Возвращает {"urls": [...], "error": "..."} — раньше при любой ошибке
    возвращался пустой список, и опечатка в пути выглядела как «сайт
    не попал в sitemap целиком».
    """
    if _depth > 3:
        return {"urls": [], "error": "слишком глубокая вложенность sitemap-индексов"}
    # Индекс, ссылающийся сам на себя, раскручивался в сотни тысяч разборов
    # и мегабайты текста ошибки — а по сети это были бы столько же запросов.
    _seen = set() if _seen is None else _seen
    if source in _seen:
        return {"urls": [], "error": ""}
    _seen.add(source)
    try:
        if source.startswith(("http://", "https://")):
            with urllib.request.urlopen(source, timeout=30) as resp:
                data = resp.read()
        else:
            if not os.path.exists(source):
                return {"urls": [], "error": f"файл {source} не найден"}
            with open(source, "rb") as fh:
                data = fh.read()
    except urllib.error.HTTPError as exc:
        return {"urls": [], "error": f"{source} отдал {exc.code}"}
    except (urllib.error.URLError, OSError) as exc:
        return {"urls": [], "error": f"{source} не читается: {exc}"}

    if data[:2] == b"\x1f\x8b":
        import gzip
        try:
            data = gzip.decompress(data)
        except OSError as exc:
            return {"urls": [], "error": f"{source}: не удалось распаковать gzip ({exc})"}

    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        return {"urls": [], "error": f"{source}: это не похоже на XML ({exc})"}

    tag = root.tag.rsplit("}", 1)[-1]
    if tag == "sitemapindex":
        urls, errors = [], []
        for sm in [e for e in root
                   if e.tag.rsplit("}", 1)[-1] == "sitemap"]:
            loc = next((c.text for c in sm
                        if c.tag.rsplit("}", 1)[-1] == "loc" and c.text), "")
            if not loc:
                continue
            loc = loc.strip()
            child = loc
            if not source.startswith("http"):
                sibling = os.path.join(os.path.dirname(source), os.path.basename(loc))
                if os.path.exists(sibling):
                    child = sibling
            result = read_sitemap(child, _depth + 1, _seen)
            urls.extend(result["urls"])
            if result["error"] and result["error"] not in errors:
                errors.append(result["error"])
        return {"urls": urls, "error": "; ".join(errors[:5])}

    urls = [el.text.strip() for el in root.iter()
            if el.text and el.tag.rsplit("}", 1)[-1] == "loc"]
    if not urls:
        return {"urls": [], "error": f"{source}: в файле нет ни одного <loc>"}
    return {"urls": urls, "error": ""}


URL_COLUMN_HINTS = sources.URL_COLUMN_HINTS


def _read_rows(csv_path: str) -> tuple:
    """CSV, XLSX, JSON, NDJSON, XML или список адресов — всё через `sources`."""
    return sources.read_table(csv_path)


def read_indexed_header(csv_path: str) -> list:
    """Заголовки экспорта — нужны, чтобы понять, чья это выгрузка."""
    try:
        rows, _ = _read_rows(csv_path)
    except SourceError:
        return []
    return rows[0] if rows else []


def read_indexed(csv_path: str, site: str = "") -> dict:
    """
    Выгрузка чего угодно, где есть адреса страниц: панель вебмастера, Ahrefs,
    Semrush, Screaming Frog, GA4, Matomo, просто список.

    Колонка с адресом ищется по заголовку, а если заголовки непонятные —
    по содержимому первой строки. Формат у всех разный, адрес есть у всех.

    Отдельно про относительные пути: GA4 и Matomo выгружают `/guide/visa/`,
    а не полный адрес. Без `site` такая выгрузка читалась как пустая, и отчёт
    уверенно сообщал «в индексе ноль» — худший вид ошибки. Теперь путь
    достраивается до адреса, а если `site` не передан, об этом говорится вслух.
    """
    rows, encoding = _read_rows(csv_path)
    if not rows:
        raise SourceError(f"{csv_path}: файл пустой.")

    found = sources.guess_column(rows[0], URL_COLUMN_HINTS)
    col = found if found >= 0 else None
    start = 1
    if col is None:
        col = next((i for i, c in enumerate(rows[0])
                    if str(c).startswith(("http://", "https://", "/"))), None)
        start = 0
    if col is None:
        raise SourceError(
            f"{csv_path}: не нашёл колонку с адресами страниц.\n"
            f"    Заголовки файла: " + ", ".join(str(c) for c in rows[0][:8]) + "\n"
            f"    Нужен экспорт, где есть столбец с адресами "
            f"(в Search Console — «Страницы», не «Запросы»).")

    base = (site or "").rstrip("/")
    out, seen, relative, skipped = [], set(), 0, 0
    for row in rows[start:]:
        if col >= len(row):
            continue
        value = str(row[col]).strip().strip('"')
        if not value:
            continue
        if value.startswith("/"):
            relative += 1
            if not base:
                skipped += 1
                continue
            value = base + value
        elif not value.startswith(("http://", "https://")):
            continue
        if value not in seen:
            seen.add(value)
            out.append(value)

    notes = []
    if relative and base:
        notes.append(f"{os.path.basename(csv_path)}: {relative} адресов были "
                     f"относительными путями — достроены до {base}/…")
    if skipped:
        notes.append(f"{os.path.basename(csv_path)}: {skipped} строк содержат "
                     f"пути вида /guide/… без домена, а --site не задан — "
                     f"они пропущены. Передай --site, чтобы их учесть.")
    if not out:
        raise SourceError(
            f"{csv_path}: колонка «{rows[0][col] if col < len(rows[0]) else col}» "
            f"нашлась, но ни одного адреса в ней нет."
            + ("\n    В файле только относительные пути — передай --site."
               if relative else ""))
    return {"urls": out, "encoding": encoding, "notes": notes}


def read_sources(specs: list, site: str = "") -> dict:
    """
    Читает несколько выгрузок сразу и помнит, чем каждая является.

    Спека — либо `имя=путь`, либо просто путь. Имя может быть поисковиком
    (`google=`, `bing=`) или инструментом (`ahrefs=`, `screamingfrog=`, `ga4=`):
    от этого зависит не метка в отчёте, а смысл шага воронки.

    Возвращает `by_engine` (только панели вебмастера — то, что вправе называться
    индексом) и `by_source` (всё подряд, включая краулеры и сторонние сервисы).
    """
    out, extra, notes, unlabeled, kinds = {}, {}, [], set(), {}
    for spec in specs or ():
        name, path = sources.parse_spec(spec)
        header = read_indexed_header(path)
        if name:
            kind = sources.kind_of(name)
        else:
            guessed, kind, confident = sources.identify(path, header)
            name = guessed or os.path.splitext(os.path.basename(path))[0].lower()
            kind = kind or sources.LIST
            if not confident:
                unlabeled.add(name)
                notes.append(
                    f"{os.path.basename(path)}: не удалось уверенно определить "
                    f"источник, файл засчитан как «{name}» "
                    f"({sources.KIND_TITLE[kind]}). Если это не так, укажи явно: "
                    f"--indexed google={path} или --indexed ahrefs={path}")
        result = read_indexed(path, site)
        notes += result.get("notes", [])
        urls = set(result["urls"])
        kinds[name] = kind
        target = out if kind == sources.INDEX else extra
        if name in target:
            notes.append(f"две выгрузки помечены как «{name}» — они объединены; "
                         f"если это разные источники, задай метки явно")
            target[name] |= urls
        else:
            target[name] = urls

    if not out and extra:
        notes.append(
            "панели вебмастера среди выгрузок нет. Воронка построена на том, "
            "что есть, но подпись шага это учитывает: "
            + "; ".join(sources.describe(list(extra))) + ".")
    return {"by_engine": out, "by_source": extra, "kinds": kinds,
            "notes": notes, "unlabeled": sorted(unlabeled)}


def funnel(pages: list, sitemap_urls: list = None, indexed_urls: list = None,
           by_engine: dict = None, by_source: dict = None) -> dict:
    """
    Строит воронку и, главное, объясняет каждую потерю.
    Возвращает как числа, так и конкретные списки URL — чинить надо адресно.

    Всё сравнение идёт по ключу URL: `/виза/`, `/%D0%B2%D0%B8%D0%B7%D0%B0/`
    и `/виза/index.html` — одна страница.
    """
    from .publish import indexable

    display = {url_key(p.url): p.url for p in pages}
    generated = set(display)
    publishable = {url_key(p.url) for p in pages if indexable(p)}
    blocked = generated - publishable

    def show(keys):
        return sorted(display.get(k, k) for k in keys)

    in_sitemap = _keys(sitemap_urls or []) if sitemap_urls is not None else None
    # Панели вебмастера и всё остальное считаются вместе, но помнят, кто есть кто:
    # от состава зависит, как честно назвать шаг.
    panels = {name: _keys(urls) for name, urls in (by_engine or {}).items() if urls}
    others = {name: _keys(urls) for name, urls in (by_source or {}).items() if urls}
    engines_keys = dict(panels)
    engines_keys.update(others)
    if engines_keys and indexed_urls is None:
        in_index = set().union(*engines_keys.values())
    elif indexed_urls is not None:
        in_index = _keys(indexed_urls)
    else:
        in_index = None

    missing_from_sitemap = show(publishable - in_sitemap) if in_sitemap is not None else []
    stale_in_sitemap = sorted(in_sitemap - generated) if in_sitemap is not None else []

    known = in_sitemap & publishable if in_sitemap is not None else publishable
    not_indexed = show(known - in_index) if in_index is not None else []
    indexed_unknown = sorted(in_index - generated) if in_index is not None else []

    steps = [
        {"name": "Сгенерировано", "count": len(generated)},
        {"name": "Пригодно к индексации", "count": len(publishable),
         "lost": len(blocked),
         "why": "noindex или canonical на другую страницу"},
    ]
    if in_sitemap is not None:
        steps.append({"name": "В sitemap", "count": len(in_sitemap & publishable),
                      "lost": len(publishable - in_sitemap),
                      "why": "страница есть на диске, но в sitemap не попала"})
    if in_index is not None:
        # Счёт и потери берутся от одного множества `known`, иначе воронка
        # росла: закрытая от индексации страница, ещё сидящая в индексе,
        # давала «в индексе 3» после «в sitemap 2».
        label = sources.index_grade(list(engines_keys)) or "Хотя бы в одном индексе"
        steps.append({"name": label, "count": len(known & in_index),
                      "lost": len(known - in_index),
                      "why": "источник знает про URL, но страницы в нём нет"})
        for name in sorted(engines_keys):
            hit = engines_keys[name] & known
            kind = sources.kind_of(name)
            suffix = "" if kind == sources.INDEX else f" ({sources.KIND_TITLE[kind]})"
            steps.append({"name": f"  из них в {name}{suffix}", "count": len(hit),
                          "lost": len((known & in_index) - hit),
                          "why": f"есть в других источниках, но не в {name}",
                          "engine": name, "kind": kind})

    foreign = []
    # Краулер и сторонний сервис поднимают цифру шага, не поднимая индексацию.
    # Без этой оговорки добавление выгрузки Screaming Frog выглядело бы как
    # улучшение — самый дорогой вид уверенной неправды.
    if panels and others:
        foreign.append(
            "в шаг засчитаны источники, которые индексом не являются "
            f"({', '.join(sorted(others))}). Реальную индексацию показывают "
            f"строки панелей: {', '.join(sorted(panels))}.")
    elif others and not panels:
        foreign.append(
            "панели вебмастера среди выгрузок нет, поэтому строгого ответа "
            "«в индексе или нет» здесь не будет: "
            + "; ".join(sources.describe(list(others))) + ".")
    if in_index is not None and generated and not (in_index & generated) and in_index:
        foreign.append(
            f"ни один из {len(in_index)} адресов выгрузки не совпал с адресами сайта. "
            f"Скорее всего, это экспорт другого проекта или другой домен "
            f"(проверь --site). Раздел индексации ниже смысла не имеет.")

    return {
        "steps": steps,
        "foreign": foreign,
        "by_engine": {name: show(keys & generated) for name, keys in engines_keys.items()},
        "engine_keys": {name: sorted(keys) for name, keys in engines_keys.items()},
        "panel_keys": {name: sorted(keys) for name, keys in panels.items()},
        "kinds": {name: sources.kind_of(name) for name in engines_keys},
        "proves": sources.describe(list(engines_keys)),
        "display": display,
        "blocked": show(blocked),
        "missing_from_sitemap": missing_from_sitemap,
        "stale_in_sitemap": stale_in_sitemap,
        "not_indexed": not_indexed,
        "indexed_unknown": indexed_unknown,
        "has_sitemap": in_sitemap is not None,
        "has_index": in_index is not None,
    }


def cross_engine(funnel_result: dict, pages: list) -> list:
    """
    Сравнивает индексы разных поисковиков. Это меняет диагноз.

    Страница, которой нет НИГДЕ, — почти всегда техническая проблема:
    её не обошли или отбраковали по формальным признакам.
    Страница, которая есть в одном индексе и нет в другом, — уже другое:
    краулер её обошёл и принял, значит дело не в технике, а в оценке
    качества конкретным поисковиком либо в разной скорости индексации.

    Страницы, закрытые от индексации намеренно, в «нигде» не попадают:
    раньше сознательный noindex выглядел как авария.

    Сравниваются только панели вебмастера. Ставить в один ряд «есть в Google»
    и «Screaming Frog дошёл» нельзя: это утверждения о разных вещах, и вывод
    «страница есть у одного и нет у другого» из такой пары был бы бессмыслицей,
    поданной уверенным тоном.
    """
    from .publish import indexable

    panels = funnel_result.get("panel_keys")
    if panels is None:                      # старый вызов без разделения
        panels = funnel_result.get("engine_keys") or {}
    by_engine = {name: set(keys) for name, keys in panels.items()}
    if len(by_engine) < 2:
        return []

    display = funnel_result.get("display") or {}
    expected = {url_key(p.url) for p in pages if indexable(p)}
    everywhere = set.intersection(*by_engine.values()) & expected
    anywhere = set.union(*by_engine.values()) & expected

    def show(keys):
        return sorted(display.get(k, k) for k in keys)

    out = [{
        "kind": "везде",
        "count": len(everywhere),
        "note": "во всех подключённых индексах — здесь вопросов нет",
        "urls": [],
    }]

    for name, keys in sorted(by_engine.items()):
        missing = (anywhere - keys)
        if missing:
            out.append({
                "kind": f"нет только в {name}",
                "count": len(missing),
                "note": f"другие поисковики страницу приняли, значит она доступна "
                        f"и валидна. Причина на стороне {name}: оценка качества "
                        f"или более медленная индексация — техническими правками "
                        f"это обычно не лечится",
                "urls": show(missing)[:50],
            })

    nowhere = expected - anywhere
    if nowhere:
        out.append({
            "kind": "нигде",
            "count": len(nowhere),
            "note": "ни один поисковик не добавил в индекс — это техническая "
                    "проблема, ищите причину в разделе ниже",
            "urls": show(nowhere)[:50],
        })
    return out


def explain(funnel_result: dict, analysis: dict) -> list:
    """
    Связывает потери с найденными причинами: не просто «40 страниц не в индексе»,
    а «из них 31 сирота, 6 почти-дубли». Это и есть то, что нельзя нагуглить.

    Страница может попасть сразу в несколько причин — так и есть в жизни,
    и раньше вторая причина терялась вместе с нужной правкой.
    """
    out = []
    not_indexed = _keys(funnel_result.get("not_indexed", []))
    if not not_indexed:
        return out

    display = funnel_result.get("display") or {}
    graph = analysis["graph"]
    config = analysis["config"]

    orphans = _keys(set(graph["orphans"]) | set(graph["unreachable"]))
    # Только настоящие дубли: «похожа на 57%» — не повод ставить canonical,
    # а раньше разбор потерь предписывал именно это.
    near = analysis["config"].get("near_duplicate", 0.8)
    dupes = _keys({p.url for pair in analysis["duplicates"]
                   if pair[2] >= near for p in pair[:2]})
    thin = _keys({p.url for p in analysis["pages"]
                  if p.word_count < config["thin_words"]})
    deep = _keys({u for u, d in graph["depth"].items() if d > config["max_click_depth"]})
    no_title = _keys({p.url for p in analysis["pages"] if not p.title})

    buckets = [
        ("сироты и недостижимые от главной", not_indexed & orphans,
         "добавить ссылки на них с хабовых страниц раздела"),
        ("почти-дубли других страниц", not_indexed & dupes,
         "переписать под разные интенты или оставить одну, а с остальных "
         "поставить canonical на неё — связывать их ссылками между собой нельзя"),
        ("тонкие страницы", not_indexed & thin,
         "добавить содержимое или убрать из индекса"),
        ("глубже допустимого клика", not_indexed & deep,
         "поднять выше в структуре"),
        ("без title", not_indexed & no_title,
         "заполнить title — без него страница почти не имеет шансов"),
    ]
    explained = set()
    for name, keys, fix in buckets:
        if keys:
            explained |= keys
            out.append({"cause": name, "count": len(keys), "fix": fix,
                        "urls": sorted(display.get(k, k) for k in keys)[:50]})

    rest = not_indexed - explained
    if rest:
        out.append({"cause": "причина не установлена локально",
                    "count": len(rest),
                    "fix": "проверить в Search Console статус конкретных URL "
                           "и время с публикации",
                    "urls": sorted(display.get(k, k) for k in rest)[:50]})
    return out
