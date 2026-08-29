# -*- coding: utf-8 -*-
"""
Шаг «техническая обвязка»: sitemap и сообщение поисковикам об изменениях.

Две вещи, которые на конвейере из сотен страниц ломаются предсказуемо:

  * sitemap. Лимит — 50 000 URL и 50 МБ на файл, поэтому нужен индекс и шардинг.
    И lastmod: если он проставляется датой сборки, то у всех страниц он одинаков
    и бесполезен. Здесь lastmod меняется только когда реально изменился текст.

  * IndexNow. Отправлять весь sitemap на каждый деплой — расход краул-квоты
    впустую. Отправляется только то, что изменилось по содержимому,
    и только то, что вообще индексируемо.

Главный урок аудита: **состояние sitemap и состояние отправки — разные вещи.**
Сборка sitemap раньше пересобирала манифест с нуля и стирала отметки
об отправке, поэтому после каждой сборки в IndexNow уезжал весь сайт.
Теперь запись в манифест только дополняет существующую.
"""

from __future__ import annotations

import glob
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from .core import SourceError, url_key
from .i18n import tr

MAX_URLS_PER_FILE = 45000          # запас к лимиту 50 000
INDEXNOW_BATCH = 10000             # лимит протокола
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"

KEY_RE = re.compile(r"^[A-Za-z0-9-]{8,128}$")


def check_key(key: str) -> str:
    """
    Ключ протокола становится именем файла в корне сайта, поэтому он обязан
    быть безобидным. Раньше в него можно было передать путь с `../`.

    Исключение — `SourceError`, а не `ValueError`: текст сообщения написан
    для человека, и он должен доходить до него без питоновского стека.
    """
    key = (key or "").strip()
    if not KEY_RE.match(key):
        raise SourceError(
            tr("Ключ IndexNow — это 8–128 символов из латиницы, цифр и дефиса, которые ты придумываешь сам (например uuid без скобок).\n    Он же станет именем файла в корне сайта: /<ключ>.txt"))
    return key


def _days_between(a: str, b: str) -> int:
    try:
        return abs((date.fromisoformat(b) - date.fromisoformat(a)).days)
    except (ValueError, TypeError):
        return 0


DRAFT_STATUSES = {"draft", "черновик", "todo", "wip", "unpublished"}


def indexable(page) -> bool:
    """Страница, которую вообще имеет смысл показывать поисковику."""
    if page.noindex:
        return False
    # Черновик не публикуется. Раньше страница со `status: draft` спокойно
    # уезжала и в sitemap, и в очередь IndexNow: проверка смотрела только
    # на noindex и canonical, а `status` ставит в каждую заготовку сам пакет.
    if str(page.meta.get("status", "")).strip().lower() in DRAFT_STATUSES:
        return False
    if page.canonical:
        # Сравнение по ключу: относительный canonical `/visa/` — это та же
        # страница, а не «другая». Раньше такие страницы молча выпадали
        # из sitemap, хотя с ними всё в порядке.
        return url_key(page.canonical) == page.key
    return True


def _shard_loc(base_url: str, public_prefix: str, name: str) -> str:
    prefix = (public_prefix or "").strip("/")
    parts = [base_url.rstrip("/")]
    if prefix:
        parts.append(prefix)
    parts.append(name)
    return "/".join(parts)


def build_sitemap(pages: list, out_dir: str, base_url: str,
                  manifest: dict = None, today: str = None,
                  public_prefix: str = "") -> dict:
    """
    Пишет sitemap.xml (или sitemap.xml-индекс + шарды) в out_dir.

    `public_prefix` — путь, по которому шарды будут доступны на сайте, если
    out_dir не совпадает с корнем публикации. Без него индекс ссылается
    на корень, файлы лежат в подпапке, и ни один URL не доезжает.

    Манифест дополняется, а не переписывается: поле `notified` принадлежит
    команде notify и не должно исчезать при сборке sitemap.
    """
    today = today or date.today().isoformat()
    manifest = dict(manifest or {})
    included = sorted([p for p in pages if indexable(p)], key=lambda p: p.url)

    new_manifest = {k: dict(v) for k, v in manifest.items() if isinstance(v, dict)}
    live = {p.url for p in pages}
    # Записи удалённых страниц не копятся вечно: на каталоге с ротацией
    # манифест разрастался до тысяч мёртвых URL, а «Пропало: 1530»
    # в каждом прогоне превращалось в шум. Держим месяц — на случай,
    # если страницу вернут, — и убираем.
    for url, entry in list(new_manifest.items()):
        if url in live:
            entry.pop("missing_since", None)
            continue
        since = entry.get("missing_since") or today
        if _days_between(since, today) > 30:
            del new_manifest[url]
        else:
            entry["missing_since"] = since
    entries = []
    for p in included:
        h = p.content_hash
        prev = manifest.get(p.url) or {}
        lastmod = prev.get("lastmod") if prev.get("hash") == h else None
        lastmod = lastmod or today
        entry = dict(prev)
        entry["hash"] = h
        entry["lastmod"] = lastmod
        new_manifest[p.url] = entry
        entries.append((p.url, lastmod))

    os.makedirs(out_dir, exist_ok=True)
    written = []

    def write_urlset(path, chunk):
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for url, lastmod in chunk:
            lines.append(f"  <url><loc>{escape(url)}</loc><lastmod>{lastmod}</lastmod></url>")
        lines.append("</urlset>")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        written.append(path)

    # Старые шарды от прошлой, более крупной сборки нужно убрать: иначе
    # поисковик продолжит ходить по файлам с несуществующими URL.
    # Но убирать можно ТОЛЬКО то, что пакет создал сам и записал в манифест:
    # поиск по маске сносил чужие sitemap-news.xml и sitemap-images.xml.
    stale = {os.path.join(out_dir, name)
             for name in (manifest.get("_shards") or [])
             if isinstance(name, str)}

    if len(entries) <= MAX_URLS_PER_FILE:
        write_urlset(os.path.join(out_dir, "sitemap.xml"), entries)
    else:
        shards = [entries[i:i + MAX_URLS_PER_FILE]
                  for i in range(0, len(entries), MAX_URLS_PER_FILE)]
        for i, chunk in enumerate(shards, 1):
            path = os.path.join(out_dir, f"sitemap-{i}.xml")
            write_urlset(path, chunk)
            stale.discard(path)
        index_lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                       '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for i, chunk in enumerate(shards, 1):
            loc = _shard_loc(base_url, public_prefix, f"sitemap-{i}.xml")
            newest = max(lastmod for _, lastmod in chunk)
            index_lines.append(
                f"  <sitemap><loc>{escape(loc)}</loc><lastmod>{newest}</lastmod></sitemap>")
        index_lines.append("</sitemapindex>")
        path = os.path.join(out_dir, "sitemap.xml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(index_lines) + "\n")
        written.append(path)

    removed = []
    for path in sorted(stale):
        if os.path.basename(path) == "sitemap.xml":
            continue
        try:
            os.remove(path)
            removed.append(path)
        except OSError:
            pass
    new_manifest["_shards"] = sorted(os.path.basename(p) for p in written)

    return {
        "manifest": new_manifest,
        "files": written,
        "removed": removed,
        "included": len(entries),
        "excluded": len(pages) - len(entries),
        "drafts": sorted(p.url for p in pages
                         if str(p.meta.get("status", "")).strip().lower()
                         in DRAFT_STATUSES),
    }


def diff_changed(pages: list, manifest: dict) -> dict:
    """
    Что изменилось с прошлой ОТПРАВКИ — по содержимому, не по дате файла.

    Сравнение идёт с полем `notified`, а не с `hash`: сборка sitemap обновляет
    `hash` и не должна при этом «съедать» очередь на отправку.
    """
    manifest = manifest or {}
    new, changed, unchanged = [], [], []
    for p in pages:
        if not indexable(p):
            continue
        prev = (manifest.get(p.url) or {}).get("notified")
        if prev is None:
            new.append(p.url)
        elif prev != p.content_hash:
            changed.append(p.url)
        else:
            unchanged.append(p.url)
    known = {u for u in manifest if not u.startswith("_")}
    removed = sorted(known - {p.url for p in pages})
    return {"new": sorted(new), "changed": sorted(changed),
            "unchanged": sorted(unchanged), "removed": removed}


def mark_notified(manifest: dict, pages: list, urls: list) -> dict:
    """Отмечает успешно отправленные URL. Вызывается только после реальной отправки."""
    manifest = dict(manifest or {})
    by_url = {p.url: p for p in pages}
    for url in urls:
        page = by_url.get(url)
        if page is None:
            continue
        entry = dict(manifest.get(url) or {})
        entry["notified"] = page.content_hash
        manifest[url] = entry
    return manifest


def write_key_file(out_dir: str, key: str) -> str:
    """Файл подтверждения владения, который требует протокол."""
    key = check_key(key)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{key}.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(key)
    return path


def submit_indexnow(urls: list, base_url: str, key: str,
                    key_location: str = None, dry_run: bool = True,
                    timeout: int = 30) -> dict:
    """
    Отправляет URL батчами. По умолчанию dry_run — ничего не шлёт, только показывает,
    что ушло бы: на конвейере ошибиться и залить мусор проще, чем кажется.

    Возвращает и результаты батчей, и список реально принятых URL. Раньше отказ
    на середине обнулял всю очередь, включая подтверждённые батчи, — и они
    уезжали повторно на следующем запуске.
    """
    key = check_key(key)
    host = urlparse(base_url).netloc
    key_location = key_location or f"{base_url.rstrip('/')}/{key}.txt"
    results, accepted = [], []

    for i in range(0, len(urls), INDEXNOW_BATCH):
        batch = urls[i:i + INDEXNOW_BATCH]
        payload = {"host": host, "key": key, "keyLocation": key_location, "urlList": batch}
        if dry_run:
            results.append({"batch": len(batch), "status": "dry-run", "sample": batch[:3]})
            continue
        req = urllib.request.Request(
            INDEXNOW_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                results.append({"batch": len(batch), "status": resp.status})
                if 200 <= resp.status < 300:
                    accepted.extend(batch)
        except urllib.error.HTTPError as e:
            results.append({"batch": len(batch), "status": e.code,
                            "error": _explain_indexnow(e.code)})
            # Ошибка ключа или формата повторится на каждом батче — смысла
            # долбить сервер двадцатью заведомо провальными запросами нет.
            if e.code in (400, 403, 422, 429) or e.code >= 500:
                results.append({"batch": 0, "status": "stopped",
                                "error": tr("остановился, чтобы не усугублять; принятые батчи сохранены")})
                break
        except Exception as e:                       # noqa: BLE001
            # urlopen оборачивает в URLError не всё: таймаут чтения прилетает
            # голым TimeoutError, обрыв keep-alive — RemoteDisconnected,
            # и раньше они уносили наружу весь результат вместе с уже
            # подтверждёнными батчами.
            reason = getattr(e, "reason", e)
            results.append({"batch": len(batch), "status": "network",
                            "error": f"{type(e).__name__}: {reason}"})
            break
    return {"results": results, "accepted": accepted}


def _explain_indexnow(code: int) -> str:
    return {
        400: tr("неверный формат запроса"),
        403: tr("ключ не найден по keyLocation — проверь, что файл лежит в корне и доступен"),
        422: tr("URL не принадлежат указанному host, либо ключ не совпадает"),
        429: tr("слишком часто — притормози и повтори позже"),
    }.get(code, tr("неизвестная ошибка"))
