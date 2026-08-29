# -*- coding: utf-8 -*-
"""
Поисковики. Их больше одного, и ведут они себя по-разному.

Две отдельные задачи, которые легко перепутать:

  * **сообщить об обновлении.** IndexNow транслирует один запрос всем
    участникам протокола — их состав меняется, поэтому список тянется
    из реестра, а не зашит в код. Google в протоколе НЕ участвует
    и никогда не участвовал: для него работают только sitemap и Search Console.

  * **проверить, попало ли в индекс.** У каждого поисковика свой индекс
    и свои критерии. Страница может быть в Bing и не быть в Google —
    и это ценный диагностический сигнал, а не мелочь: значит краулер
    её обошёл и принял, а спор идёт о качестве, не о технике.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

REGISTRY_URL = "https://www.indexnow.org/searchengines.json"
REGISTRY_CACHE = "engines.json"
CACHE_TTL = 7 * 24 * 3600


def cache_dir() -> str:
    """
    Кэш реестра живёт в домашнем каталоге пользователя, а не рядом со страницами.
    Служебный файл в каталоге контента уезжает в сборку статического сайта
    и попадает на прод — этого быть не должно.
    """
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache")
    path = os.path.join(base, "indexgap")
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError:
        import tempfile
        return tempfile.gettempdir()

# Состав на момент написания. Используется, когда реестр недоступен —
# например, в CI без сети. Актуальный список всё равно берётся из реестра.
FALLBACK_PARTICIPANTS = {
    "bing": "https://www.bing.com/indexnow",
    "yandex": "https://yandex.com/indexnow",
    "seznam": "https://search.seznam.cz/indexnow",
    "naver": "https://searchadvisor.naver.com/indexnow",
    "yep": "https://indexnow.yep.com/indexnow",
    "internetarchive": "https://web-static.archive.org/indexnow",
    "amazonbot": "https://indexnow.amazonbot.amazon/indexnow",
}

# Кто НЕ участвует и что с этим делать. Показывается человеку явно:
# молчаливое «отправлено» создаёт ложное ощущение, что покрыты все.
NON_PARTICIPANTS = {
    "google": "не поддерживает IndexNow. Остаются sitemap и Search Console — "
              "проверка индексации в отчёте, отправка через интерфейс.",
    "baidu": "своя система подачи, требует отдельной регистрации.",
}


def fetch_participants(cache_path_dir: str = None, timeout: int = 15,
                       offline: bool = False) -> dict:
    """
    Кто сегодня принимает IndexNow. Реестр кэшируется на неделю:
    он меняется редко, а в CI сети может не быть вовсе.
    """
    cache_path = os.path.join(cache_path_dir or cache_dir(), REGISTRY_CACHE)
    if os.path.exists(cache_path):
        try:
            age = time.time() - os.path.getmtime(cache_path)
            with open(cache_path, "r", encoding="utf-8") as fh:
                cached = json.load(fh)
            if age < CACHE_TTL and isinstance(cached, dict) and cached:
                return {"participants": cached, "source": "кэш"}
        except (OSError, json.JSONDecodeError):
            pass

    if offline:
        return {"participants": dict(FALLBACK_PARTICIPANTS), "source": "встроенный список"}

    try:
        with urllib.request.urlopen(REGISTRY_URL, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, dict) and data:
            try:
                with open(cache_path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False, indent=2)
            except OSError:
                pass
            return {"participants": data, "source": "реестр indexnow.org"}
    except (urllib.error.URLError, json.JSONDecodeError, ValueError, TimeoutError):
        pass

    return {"participants": dict(FALLBACK_PARTICIPANTS), "source": "встроенный список"}


# ── распознавание выгрузок из панелей вебмастера ──────────────────────────────

# Каждая панель выгружает своё. Заголовки различаются, а иногда их нет вовсе.
EXPORT_SIGNATURES = {
    "google": (
        ("top pages", "страницы", "самые популярные страницы", "page"),
        ("clicks", "клики", "impressions", "показы", "ctr", "position", "позиция"),
    ),
    "bing": (
        ("url", "адрес", "page"),
        ("clicks", "impressions", "avg. click position", "avg click position"),
    ),
    "yandex": (
        ("url", "адрес страницы", "страница"),
        ("показы", "клики", "позиция", "переходы", "статус"),
    ),
}

KNOWN_ENGINES = ("google", "bing", "yandex", "naver", "seznam", "yep", "baidu", "duckduckgo")


def guess_engine(path: str, header: list) -> tuple:
    """
    Пытается понять, чей это экспорт: по имени файла, затем по заголовкам.

    Возвращает (движок, уверенно ли). Ошибка здесь не безобидна: если две
    выгрузки получают одну метку, они сливаются в один индекс, и сравнение
    поисковиков — главная ценность отчёта — исчезает бесследно. Поэтому
    при ничьей по заголовкам ответ честный: «не знаю».
    """
    name = os.path.basename(path).lower()
    for engine in KNOWN_ENGINES:
        if engine in name:
            return engine, True
    if "gsc" in name or "search-console" in name or "searchconsole" in name:
        return "google", True
    if "wmt" in name or "webmaster" in name:
        return "bing", True
    if "вебмастер" in name:
        return "yandex", True

    normalized = {str(h).strip().lower() for h in (header or [])}
    scores = {}
    for engine, (url_hints, metric_hints) in EXPORT_SIGNATURES.items():
        score = sum(1 for h in normalized if any(hint in h for hint in url_hints))
        score += sum(1 for h in normalized if any(hint in h for hint in metric_hints))
        scores[engine] = score
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked or ranked[0][1] < 2:
        return "", False
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return "", False           # ничья — не выдумываем движок
    return ranked[0][0], False


def parse_source(spec: str) -> tuple:
    """
    `google=exports/gsc.csv` -> ("google", "exports/gsc.csv")
    `exports/bing.csv`       -> ("", "exports/bing.csv") — движок определится сам
    """
    if "=" in spec:
        engine, _, path = spec.partition("=")
        engine = engine.strip().lower()
        if engine and not os.path.exists(engine):   # защита от путей вида C:=...
            return engine, path.strip()
    return "", spec.strip()


def describe_coverage(engines_seen: list) -> list:
    """Что осталось непокрытым — говорим прямо, а не умалчиваем."""
    notes = []
    seen = {e.lower() for e in engines_seen if e}
    for engine, why in NON_PARTICIPANTS.items():
        if engine not in seen:
            notes.append(f"{engine}: {why}")
    return notes
