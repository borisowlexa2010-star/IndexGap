# -*- coding: utf-8 -*-
"""
Сравнение двух сборок одного сайта: что сломает этот деплой.

`check` судит одну сборку. Но самые дорогие поломки видны только в сравнении:
страница была в индексе и исчезла — на живом сайте это 404 по адресу, у
которого были показы; шаблон получил noindex — и закрылся целый раздел;
правка в генераторе срезала текст вдвое на тысяче страниц. В каждой сборке
по отдельности всё это выглядит прилично.

Сравнение идёт по ключу адреса (`url_key`), как и всё в пакете: старая и
новая сборка могли писать один и тот же адрес по-разному.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from urllib.parse import urlsplit

from .checks import _url_pattern, redirect_target
from .core import read_text, url_key
from .i18n import tr
from .publish import indexable, is_draft

# Шаблоном, а не единичной правкой, изменение считается с этой доли страниц
# шаблона и с этого их числа: пять заголовков из шести — уже правка шаблона.
TEMPLATE_SHARE = 0.5
TEMPLATE_MIN = 5
# Падение текста считается с половины. Страницы короче этого порога не
# сравниваются: 12 слов против 5 — шум, а не потеря содержания.
SHRINK_SHARE = 0.5
SHRINK_MIN_WORDS = 50
OTHER = "other"

FIELDS = ("title", "h1", "description")


# ── редиректы новой сборки ────────────────────────────────────────────────────

def _rule(source: str):
    """
    Шаблон адреса из правила редиректа → регулярное выражение.

    `*` и `:splat*` / `:path*` — хвост пути, `:name` — один сегмент. Хвостовой
    `/` не различается: Netlify и Vercel приводят его сами.
    """
    source = source.strip()
    if "://" in source:
        source = urlsplit(source).path or "/"
    out = []
    for token in re.split(r"(\*|:[A-Za-z_]\w*\*?|\(\.\*\))", source.rstrip("/") or "/"):
        if token in ("*", "(.*)") or (token.startswith(":") and token.endswith("*")):
            out.append(".*")
        elif token.startswith(":") and len(token) > 1:
            out.append("[^/]+")
        else:
            out.append(re.escape(token))
    return re.compile("^" + "".join(out) + "/?$")


def _netlify_lines(text: str, origin: str) -> list:
    rules = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        parts = line.split()
        if len(parts) < 2 or not parts[0].startswith("/"):
            continue
        target = next((p for p in parts[1:] if p.startswith(("/", "http://", "https://"))), "")
        status = next((p for p in parts[1:] if re.match(r"^\d{3}!?$", p)), "301")
        if not target or status.startswith("404"):
            continue
        rules.append((_rule(parts[0]), target, origin))
    return rules


_TOML_BLOCK = re.compile(r"^\s*\[\[\s*redirects\s*\]\]\s*$", re.M)
_TOML_KEY = re.compile(r"^\s*(from|to|status)\s*=\s*[\"']?([^\"'\n#]+)", re.M)


def _netlify_toml(text: str, origin: str) -> list:
    """`[[redirects]]` из netlify.toml: tomllib есть не во всех поддерживаемых Python."""
    rules = []
    starts = [m.end() for m in _TOML_BLOCK.finditer(text)]
    for start in starts:
        block = text[start:]
        nxt = re.search(r"^\s*\[", block, re.M)
        block = block[:nxt.start()] if nxt else block
        keys = {k: v.strip() for k, v in _TOML_KEY.findall(block)}
        if keys.get("from") and keys.get("to") and not keys.get("status", "").startswith("404"):
            rules.append((_rule(keys["from"]), keys["to"], origin))
    return rules


def _vercel(text: str, origin: str) -> list:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    rules = []
    if not isinstance(data, dict):
        return rules
    for section in ("redirects", "rewrites"):
        for item in data.get(section) or []:
            if isinstance(item, dict) and isinstance(item.get("source"), str) \
                    and isinstance(item.get("destination"), str):
                rules.append((_rule(item["source"]), item["destination"], origin))
    return rules


REDIRECT_FILES = (("_redirects", _netlify_lines), ("netlify.toml", _netlify_toml),
                  ("vercel.json", _vercel))


def read_redirects(root: str) -> tuple:
    """
    Правила редиректов новой сборки: `_redirects` в корне публикации,
    netlify.toml и vercel.json — там же или уровнем выше, в корне проекта.

    Возвращает (правила, имена прочитанных файлов).
    """
    rules, found = [], []
    places = [os.path.abspath(root), os.path.dirname(os.path.abspath(root))]
    for name, parse in REDIRECT_FILES:
        for place in places:
            path = os.path.join(place, name)
            if not os.path.isfile(path):
                continue
            try:
                text, _ = read_text(path)
            except Exception:                    # noqa: BLE001 — нечитаемый файл = нет правил
                continue
            got = parse(text, name)
            if got:
                rules += got
                try:
                    found.append(os.path.relpath(path))
                except ValueError:               # другой диск в Windows
                    found.append(path)
            break
    return rules, found


def redirect_for(rules: list, url: str) -> str:
    """Куда правила переводят адрес; пусто — никуда, на живом сайте будет 404."""
    path = urlsplit(url).path or "/"
    for pattern, target, _ in rules:
        if pattern.match(path.rstrip("/") or "/") or pattern.match(path):
            return target
    return ""


# ── сравнение ─────────────────────────────────────────────────────────────────

def _h1(page) -> str:
    for level, text in getattr(page, "headings", None) or ():
        if level == 1:
            return text
    return ""


def _field(page, name: str) -> str:
    value = _h1(page) if name == "h1" else getattr(page, name, "") or ""
    return " ".join(str(value).split())


def _why_closed(page) -> tuple:
    """Почему новая страница выпала из индекса: (код причины, подробность)."""
    if redirect_target(page):
        return "redirect", redirect_target(page)
    if page.noindex:
        return "noindex", page.robots
    if is_draft(page):
        return "draft", ""
    if page.canonical and url_key(page.canonical) != page.key:
        return "canonical", page.canonical
    return "other", ""


def _patterns(urls) -> dict:
    """Адрес → шаблон; шаблоны меньше TEMPLATE_MIN страниц уходят в `other`."""
    groups = defaultdict(list)
    for url in urls:
        groups[_url_pattern(url) or OTHER].append(url)
    out = {}
    for pattern, members in groups.items():
        name = pattern if len(members) >= TEMPLATE_MIN else OTHER
        for url in members:
            out[url] = name
    return out


def compare(old_pages: list, new_pages: list, rules: list = None) -> dict:
    """
    Разница двух сборок, разложенная по видам. Уровни — как у находок:
    critical ломает индекс, warning стоит проверить, info — к сведению.
    """
    rules = rules or []
    old = {p.key: p for p in old_pages}
    new = {p.key: p for p in new_pages}
    new_keys = set(new)

    removed = []
    for key in sorted(set(old) - new_keys):
        page = old[key]
        was_open = indexable(page)
        target = redirect_for(rules, page.url)
        level = "critical" if was_open and not target else "info"
        missing_target = ""
        if target and was_open and target.startswith("/") and not re.search(r"[:*]", target):
            site = urlsplit(page.url)
            full = f"{site.scheme}://{site.netloc}{target.split('?')[0].split('#')[0]}"
            if url_key(full) not in new_keys:
                level, missing_target = "warning", full
        removed.append({"url": page.url, "level": level, "indexable_before": was_open,
                        "redirect": target or None,
                        "redirect_missing": missing_target or None})

    closed, opened, nosnippet, shrunk = [], [], [], []
    both = sorted(set(old) & new_keys)
    for key in both:
        a, b = old[key], new[key]
        was, now = indexable(a), indexable(b)
        if was and not now:
            reason, detail = _why_closed(b)
            closed.append({"url": b.url, "reason": reason, "detail": detail,
                           "level": "info" if reason == "redirect" else "critical"})
        elif now and not was:
            opened.append(b.url)
        if now and b.nosnippet and not a.nosnippet:
            nosnippet.append(b.url)
        before, after = a.word_count, b.word_count
        if now and before >= SHRINK_MIN_WORDS and after < before * (1 - SHRINK_SHARE):
            shrunk.append({"url": b.url, "old_words": before, "new_words": after,
                           "drop": round(1 - after / before, 3)})

    pattern_of = _patterns(new[k].url for k in both)
    totals = Counter(pattern_of.values())
    changed = defaultdict(list)
    for key in both:
        a, b = old[key], new[key]
        for name in FIELDS:
            before, after = _field(a, name), _field(b, name)
            if before != after:
                changed[(pattern_of[b.url], name)].append((b.url, before, after))
    changes = []
    for (pattern, name), items in sorted(changed.items()):
        total = totals[pattern]
        share = len(items) / total if total else 0
        changes.append({
            "pattern": pattern, "field": name, "changed": len(items), "pages": total,
            "share": round(share, 3),
            "template": len(items) >= TEMPLATE_MIN and share >= TEMPLATE_SHARE,
            "examples": [{"url": u, "old": x, "new": y} for u, x, y in items[:5]],
        })
    changes.sort(key=lambda c: (not c["template"], -c["changed"], c["pattern"], c["field"]))

    added_urls = [new[k].url for k in sorted(new_keys - set(old))]
    added_by = Counter(_patterns(added_urls).values())
    return {
        "old_pages": len(old_pages), "new_pages": len(new_pages),
        "removed": removed, "closed": closed, "opened": opened,
        "nosnippet": nosnippet, "shrunk": shrunk, "template_changes": changes,
        "added": {"total": len(added_urls),
                  "by_pattern": [{"pattern": p, "pages": n}
                                 for p, n in sorted(added_by.items(),
                                                    key=lambda x: (-x[1], x[0]))],
                  "urls": added_urls},
    }


FIELD_LABEL = {"title": "title", "h1": "H1", "description": "description"}


def _reason_text(item: dict) -> str:
    reason, detail = item["reason"], item["detail"]
    if reason == "noindex":
        return tr("появился noindex: meta robots «{a0}»", a0=detail)
    if reason == "canonical":
        return tr("canonical теперь ведёт на {a0}", a0=detail)
    if reason == "draft":
        return tr("страница стала черновиком")
    if reason == "redirect":
        return tr("страница стала заглушкой-редиректом на {a0}", a0=detail)
    return tr("страница выпала из индексируемых")


def items(result: dict) -> list:
    """
    Разница плоским списком (уровень, адрес, код, текст) — в той же форме,
    что находки `check`: её так же сортируют, группируют и считают.
    """
    out = []
    for r in result["removed"]:
        if r["redirect_missing"]:
            out.append((r["level"], r["url"], "page-redirected", tr(
                "страницы нет, редирект ведёт на {a0} — а этой страницы в новой сборке "
                "тоже нет", a0=r["redirect_missing"])))
        elif r["redirect"]:
            out.append((r["level"], r["url"], "page-redirected",
                        tr("страницы нет, редирект на {a0}", a0=r["redirect"])))
        elif r["indexable_before"]:
            out.append((r["level"], r["url"], "page-removed", tr(
                "была открыта для индекса, в новой сборке её нет и редиректа нет — "
                "на живом сайте будет 404")))
        else:
            out.append((r["level"], r["url"], "page-removed",
                        tr("страницы нет; она и раньше была закрыта от индекса")))
    for c in result["closed"]:
        code = "page-redirected" if c["reason"] == "redirect" else "page-closed"
        out.append((c["level"], c["url"], code, _reason_text(c)))
    for url in result["nosnippet"]:
        out.append(("warning", url, "nosnippet-added", tr(
            "появился запрет сниппета: страница останется в индексе, но пропадёт "
            "из ответов ИИ-поиска")))
    for s in result["shrunk"]:
        out.append(("warning", s["url"], "text-shrunk", tr(
            "текста стало меньше на {a0:.0%}: {a1} → {a2} слов",
            a0=s["drop"], a1=s["old_words"], a2=s["new_words"])))
    for c in result["template_changes"]:
        example = c["examples"][0]
        out.append(("warning" if c["template"] else "info", c["pattern"], "template-change", tr(
            "{a0} изменился на {a1} страницах из {a2}; например {a3}: «{a4}» → «{a5}»",
            a0=FIELD_LABEL[c["field"]], a1=c["changed"], a2=c["pages"], a3=example["url"],
            a4=example["old"][:80], a5=example["new"][:80])))
    for url in result["opened"]:
        out.append(("info", url, "page-opened", tr("страница стала открытой для индекса")))
    for a in result["added"]["by_pattern"]:
        out.append(("info", a["pattern"], "pages-added",
                    tr("новых страниц: {a0}", a0=a["pages"])))
    return out
