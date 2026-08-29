# -*- coding: utf-8 -*-
"""
Сверка трёх множеств — ответ на вопрос «конвейер отработал, а трафика нет, почему».

    сгенерировано  →  попало в sitemap  →  попало в индекс  →  даёт показы

Каждый переход теряет страницы, и потери на разных переходах лечатся по-разному.
Без этой воронки причина не видна: в интерфейсе Search Console страницы просто
«обнаружены, но не проиндексированы», без объяснения.

Данные об индексации берутся из экспорта панели вебмастера. Никаких ключей и API.

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


URL_COLUMN_HINTS = ("url", "страниц", "page", "адрес", "address", "top pages",
                    "landing", "링크", "주소", "odkaz", "stránka", "ページ", "网址")


def _read_rows(csv_path: str) -> tuple:
    if not os.path.exists(csv_path):
        raise SourceError(f"Файл не найден: {csv_path}")
    text, encoding = read_text(csv_path)
    if text[:2] == "PK":
        raise SourceError(
            f"{csv_path} — это xlsx или zip-архив. Search Console отдаёт архив: "
            f"распакуй его и передай CSV изнутри.")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(io.StringIO(text, newline=""), dialect)), encoding


def read_indexed_header(csv_path: str) -> list:
    """Заголовки экспорта — нужны, чтобы понять, чья это выгрузка."""
    try:
        rows, _ = _read_rows(csv_path)
    except SourceError:
        return []
    return rows[0] if rows else []


def read_indexed(csv_path: str) -> dict:
    """
    Экспорт любой панели вебмастера: Search Console, Bing, Яндекс, Naver.
    Колонка с URL ищется по заголовку, а если заголовки непонятные —
    по содержимому первой строки. Формат у всех разный, URL есть у всех.
    """
    rows, encoding = _read_rows(csv_path)
    if not rows:
        raise SourceError(f"{csv_path}: файл пустой.")

    header = [str(c).strip().lower() for c in rows[0]]
    col = next((i for i, h in enumerate(header)
                if any(hint in h for hint in URL_COLUMN_HINTS)), None)
    start = 1
    if col is None:
        col = next((i for i, c in enumerate(rows[0])
                    if str(c).startswith(("http://", "https://"))), None)
        start = 0
    if col is None:
        raise SourceError(
            f"{csv_path}: не нашёл колонку с адресами страниц.\n"
            f"    Заголовки файла: " + ", ".join(rows[0][:8]) + "\n"
            f"    Нужен экспорт, где есть столбец с полными URL "
            f"(в Search Console — «Страницы», не «Запросы»).")

    out, seen = [], set()
    for row in rows[start:]:
        if col >= len(row):
            continue
        value = str(row[col]).strip()
        if value.startswith(("http://", "https://")) and value not in seen:
            seen.add(value)
            out.append(value)
    if not out:
        raise SourceError(
            f"{csv_path}: колонка «{rows[0][col] if col < len(rows[0]) else col}» "
            f"нашлась, но ни одного полного URL в ней нет.")
    return {"urls": out, "encoding": encoding}


def read_sources(specs: list) -> dict:
    """
    Читает несколько выгрузок сразу: {"google": {...urls}, "bing": {...urls}}.
    Спека — либо `движок=путь`, либо просто путь (движок определится сам).
    """
    from . import engines

    out, notes, unlabeled = {}, [], set()
    for spec in specs or ():
        engine, path = engines.parse_source(spec)
        header = read_indexed_header(path)
        if not engine:
            guessed, confident = engines.guess_engine(path, header)
            engine = guessed or os.path.splitext(os.path.basename(path))[0].lower()
            if not confident:
                unlabeled.add(engine)
                notes.append(
                    f"{os.path.basename(path)}: не удалось уверенно определить "
                    f"поисковик, файл засчитан как «{engine}». Если это не так, "
                    f"укажи явно: --indexed движок={path}")
        urls = set(read_indexed(path)["urls"])
        if engine in out:
            notes.append(f"две выгрузки помечены как «{engine}» — они объединены; "
                         f"если это разные поисковики, задай метки явно")
            out[engine] |= urls
        else:
            out[engine] = urls
    return {"by_engine": out, "notes": notes, "unlabeled": sorted(unlabeled)}


def funnel(pages: list, sitemap_urls: list = None, indexed_urls: list = None,
           by_engine: dict = None) -> dict:
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
    engines_keys = {name: _keys(urls) for name, urls in (by_engine or {}).items() if urls}
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
        steps.append({"name": "Хотя бы в одном индексе", "count": len(known & in_index),
                      "lost": len(known - in_index),
                      "why": "поисковик знает про URL, но не добавил в индекс"})
        for name in sorted(engines_keys):
            hit = engines_keys[name] & known
            steps.append({"name": f"  из них в {name}", "count": len(hit),
                          "lost": len((known & in_index) - hit),
                          "why": f"есть в других индексах, но не в {name}",
                          "engine": name})

    foreign = []
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
    """
    from .publish import indexable

    by_engine = {name: set(keys)
                 for name, keys in (funnel_result.get("engine_keys") or {}).items()}
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
