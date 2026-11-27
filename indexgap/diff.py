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
from collections import Counter, defaultdict, namedtuple
from urllib.parse import unquote, urljoin, urlsplit

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

# canonical сравнивается, только когда он есть в обеих сборках: добавленный
# canonical на себя — не поломка. `url` — форма адреса той же страницы:
# `/rent/c0/` стал `/rent/c0.html`, и на GitHub Pages, S3 и nginx по умолчанию
# старый адрес ответит 404.
FIELDS = ("title", "h1", "description", "canonical", "url")


# ── редиректы новой сборки ────────────────────────────────────────────────────

class Rule(namedtuple("Rule", "pattern target origin kind status force sure")):
    """
    Правило редиректа новой сборки.

    `kind`: `redirect` (3xx), `rewrite` (200 на другую страницу), `soft404`
    (200 на главную — сервер отдаёт её по чужому адресу), `error` (404, 410,
    451 — адрес отвечает ошибкой). `force` — правило срабатывает раньше файла
    сборки: `redirects` в vercel.json, `301!` и `force = true` у Netlify.
    `sure` — правило точно касается адреса сайта: хост в условии или в
    источнике совпал буква в букву, а не с точностью до `www.`.
    """
    __slots__ = ()


def _make(pattern, target, origin, kind="redirect", status="301", force=False, sure=True):
    return Rule(pattern, target, origin, kind, status, force, sure)


def _balanced(source: str, i: int) -> int:
    """Индекс после скобки, закрывающей `(` в позиции i; -1 — не закрыта."""
    depth = 0
    while i < len(source):
        ch = source[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if not depth:
                return i + 1
        i += 1
    return -1


_NEVER = re.compile(r"(?!)")


def _rule(source: str, regex: bool = False):
    """
    Шаблон адреса из правила редиректа → регулярное выражение.

    `*` и `:splat*` / `:path*` — хвост пути, `:name` — один сегмент, `(.*)` —
    группа без имени. В vercel.json (`regex`) — ещё `:name(c[0-9]+)` и любая
    группа `(…)`: у Netlify скобки в адресе — просто скобки.
    Хвостовой `/` не различается: Netlify и Vercel приводят его сами.
    """
    source = source.strip()
    if "://" in source:
        source = urlsplit(source).path or "/"
    source = source.rstrip("/") or "/"
    out, names = [], set()

    def group(name, body):
        # Имя группы — для подстановки в цель (`:splat`, `:slug`). Повтор
        # имени регулярное выражение не примет: тогда группа без имени.
        if name and name not in names:
            names.add(name)
            return f"(?P<{name}>{body})"
        return f"({body})"

    i = 0
    while i < len(source):
        ch = source[i]
        name = re.match(r":([A-Za-z_]\w*)", source[i:]) if ch == ":" else None
        if ch == "*":
            out.append(group("splat", ".*"))
            i += 1
        elif name:
            i += name.end()
            body = "[^/]+"
            if regex and i < len(source) and source[i] == "(":
                end = _balanced(source, i)
                if end < 0:
                    return _NEVER
                body, i = source[i + 1:end - 1], end
            if i < len(source) and source[i] in "*+?":
                mod = source[i]
                i += 1
                body = {"*": ".*", "+": ".+"}.get(mod, body) if body == "[^/]+" else body
                if mod == "?":
                    out.append(group(name.group(1), body) + "?")
                    continue
            out.append(group(name.group(1), body))
        elif source.startswith("(.*)", i) or regex and ch == "(":
            end = _balanced(source, i)
            if end < 0:
                return _NEVER
            out.append("(" + source[i + 1:end - 1] + ")")
            i = end
        else:
            out.append(re.escape(ch))
            i += 1
    try:
        return re.compile("^" + "".join(out) + "/?$")
    except re.error:
        return _NEVER


def _spa_fallback(pattern) -> bool:
    """
    Правило ловит любой адрес сайта (`/*`, `/(.*)`, `/:path*`). Перезапись 200
    на всё подряд — запасной вход SPA (`/* /index.html 200`),
    а не редирект: сервер отдаёт по удалённому адресу главную с кодом 200.
    Это мягкий 404, и удалённая страница остаётся критичной находкой.
    """
    return bool(pattern.match("/indexgap-probe/any/depth"))


def _home(target: str) -> bool:
    """Цель перезаписи — главная: `/`, `/index.html`, `/index`."""
    path = urlsplit(target).path if "://" in target else target.split("?")[0].split("#")[0]
    return path.rstrip("/") in ("", "/index.html", "/index", "/index.htm")


def _host_of(value: str) -> str:
    return (value or "").strip().lower().split(":")[0]


def _host_match(value: str, host: str):
    """True — тот же хост, None — тот же с точностью до `www.`, False — чужой."""
    a, b = _host_of(value), _host_of(host)
    if not b:
        return None
    if a == b:
        return True
    strip = lambda h: h[4:] if h.startswith("www.") else h    # noqa: E731
    return None if strip(a) == strip(b) else False


def _source_host(source: str, host: str):
    if "://" not in source:
        return True
    return _host_match(urlsplit(source).netloc, host)


def _by_status(pattern, target, origin, status, force, sure) -> list:
    """Правило по коду ответа; пусто — правило выкидывается."""
    code = status.rstrip("!")
    if code.startswith("200"):
        if _home(target):
            # `/* /index.html 200` на весь сайт — запасной вход SPA, его
            # не видно: по нему отдаётся всё, что не нашлось. Тот же вход
            # на один раздел — мягкий 404 на каждом удалённом адресе раздела.
            if _spa_fallback(pattern) and not force:
                return []
            return [_make(pattern, target, origin, "soft404", code, force, sure)]
        if _spa_fallback(pattern) and not force:
            return []
        return [_make(pattern, target, origin, "rewrite", code, force, sure)]
    if code[:1] in "45":
        return [_make(pattern, target, origin, "error", code, force, sure)]
    return [_make(pattern, target, origin, "redirect", code, force, sure)]


def _netlify_lines(text: str, origin: str, host: str = "") -> list:
    rules = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        parts = line.split()
        if len(parts) < 2 or not parts[0].startswith("/") and "://" not in parts[0]:
            continue
        at = next((n for n, p in enumerate(parts[1:], 1)
                   if p.startswith(("/", "http://", "https://"))), 0)
        if not at:
            continue
        target = parts[at]
        status = next((p for p in parts[at + 1:] if re.match(r"^\d{3}!?$", p)), "301")
        # `id=:id` между источником и целью — совпадение по параметру запроса,
        # `Country=de`, `Language=en`, `Role=admin` после кода — условие.
        # У обхода страницы без параметров и без этих признаков такое правило
        # не срабатывает.
        if any("=" in p for n, p in enumerate(parts[1:], 1) if n != at):
            continue
        sure = _source_host(parts[0], host)
        if sure is False:
            continue
        rules += _by_status(_rule(parts[0]), target, origin, status,
                            status.endswith("!"), sure is True)
    return rules


_TOML_BLOCK = re.compile(r"^\s*\[\[\s*redirects\s*\]\]\s*$", re.M)
_TOML_KEY = re.compile(r"^\s*(from|to|status|force)\s*=\s*[\"']?([^\"'\n#]+)", re.M)
_TOML_INLINE_KEY = re.compile(
    r"(?<![\w.-])(from|to|status|force)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^,}\s#]+))")
_TOML_CONDITION = re.compile(r"^\s*(?:(?:conditions|query)\s*=|\[\s*redirects\.(?:conditions|query)\s*\])",
                             re.M)


def _toml_rule(keys: dict, conditional: bool, origin: str, host: str) -> list:
    if conditional or not keys.get("from") or not keys.get("to"):
        return []
    sure = _source_host(keys["from"], host)
    if sure is False:
        return []
    status = keys.get("status", "301") or "301"
    force = keys.get("force", "").lower() == "true"
    return _by_status(_rule(keys["from"]), keys["to"], origin, status, force, sure is True)


def _inline_tables(text: str) -> list:
    """`redirects = [ { from = …, to = … }, … ]` — тела таблиц верхнего уровня."""
    found = re.search(r"^\s*redirects\s*=\s*\[", text, re.M)
    if not found:
        return []
    out, depth, start, i = [], 0, 0, found.end()
    quote = ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            if not depth:
                start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if not depth:
                out.append(text[start:i])
        elif ch == "]" and not depth:
            break
        i += 1
    return out


def _netlify_toml(text: str, origin: str, host: str = "") -> list:
    """
    `[[redirects]]` и `redirects = [{…}]` из netlify.toml: tomllib есть
    не во всех поддерживаемых Python.
    """
    rules = []
    for found in _TOML_BLOCK.finditer(text):
        block = text[found.end():]
        # Блок кончается на следующей таблице; подтаблицы `[redirects.headers]`,
        # `[redirects.conditions]` — его часть.
        nxt = re.search(r"^\s*\[(?!\s*redirects\.)", block, re.M)
        block = block[:nxt.start()] if nxt else block
        keys = {k: v.strip() for k, v in _TOML_KEY.findall(block)}
        rules += _toml_rule(keys, bool(_TOML_CONDITION.search(block)), origin, host)
    for body in _inline_tables(text):
        keys = {}
        for name, a, b, c in _TOML_INLINE_KEY.findall(body):
            keys.setdefault(name, (a or b or c).strip())
        conditional = bool(re.search(r"(?<![\w.-])(conditions|query)\s*=", body))
        rules += _toml_rule(keys, conditional, origin, host)
    return rules


def _vercel_condition(entry: dict, host: str):
    """
    Условие `has` / `missing`: True — правило срабатывает на обходе адреса
    сайта, False — нет (заголовок, cookie, параметр у обхода не выставлены),
    None — хост совпал лишь с точностью до `www.`.
    """
    sure = True
    for kind in ("has", "missing"):
        for cond in entry.get(kind) or ():
            if not isinstance(cond, dict):
                return False
            if cond.get("type") != "host":
                if kind == "has":
                    return False
                continue                  # «нет такого заголовка» у обхода выполнено
            hit = _host_match(str(cond.get("value", "")), host)
            if hit is None:
                sure = None
            elif hit != (kind == "has"):
                return False
    return sure


def _route_status(item: dict) -> str:
    status = item.get("status")
    return str(status) if isinstance(status, int) else ""


def _vercel_routes(items, origin: str, host: str) -> list:
    """
    Старый формат `routes`: `src` — регулярное выражение, редирект — код 3xx
    с заголовком Location. Срабатывают ли они раньше файлов, зависит от места
    `{"handle": "filesystem"}`, поэтому раньше файла они не считаются.
    """
    rules = []
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict) or not isinstance(item.get("src"), str):
            continue
        sure = _vercel_condition(item, host)
        status = _route_status(item)
        headers = item.get("headers") if isinstance(item.get("headers"), dict) else {}
        location = next((v for k, v in headers.items()
                         if str(k).lower() == "location" and isinstance(v, str)), "")
        dest = item.get("dest") if isinstance(item.get("dest"), str) else ""
        # `dest` без кода — перезапись, код 4xx — ошибка по адресу. Маршрут
        # с `continue` или `methods` лишь добавляет заголовки или ловит не GET.
        if sure is False or item.get("continue") or item.get("methods"):
            continue
        if not (status.startswith("3") and location) and not (dest and status in ("", "200")) \
                and status[:1] not in ("4", "5"):
            continue
        src = re.sub(r"\(\?<(?![=!])", "(?P<", item["src"].lstrip("^").rstrip("$"))
        try:
            pattern = re.compile("^" + src + "$")
        except re.error:
            continue
        if status.startswith("3") and location:
            rules.append(_make(pattern, location, origin, "redirect", status, False, sure is True))
        else:
            rules += _by_status(pattern, dest, origin, status or "200", False, sure is True)
    return rules


def _vercel(text: str, origin: str, host: str = "") -> list:
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
                sure = _vercel_condition(item, host)
                if sure is False:
                    continue
                rule = _rule(item["source"], regex=True)
                if section == "rewrites":
                    rules += _by_status(rule, item["destination"], origin, "200", False,
                                        sure is True)
                else:
                    # `redirects` Vercel проверяет раньше файлов сборки.
                    code = item.get("statusCode") or (308 if item.get("permanent", True) else 307)
                    rules.append(_make(rule, item["destination"], origin, "redirect",
                                       str(code), True, sure is True))
    rules += _vercel_routes(data.get("routes"), origin, host)
    return rules


# `_redirects` Netlify и Cloudflare Pages читают только из каталога
# публикации; netlify.toml и vercel.json лежат и в корне проекта.
REDIRECT_FILES = (("_redirects", _netlify_lines, False), ("netlify.toml", _netlify_toml, True),
                  ("vercel.json", _vercel, True))


def read_redirects(root: str, host: str = "") -> tuple:
    """
    Правила редиректов новой сборки: `_redirects` в корне публикации,
    netlify.toml и vercel.json — там же или уровнем выше, в корне проекта.
    `host` — хост сайта: по нему проверяются условия правил на хост.

    Возвращает (правила, имена прочитанных файлов).
    """
    rules, found = [], []
    here = os.path.abspath(root)
    for name, parse, parent in REDIRECT_FILES:
        for place in ([here, os.path.dirname(here)] if parent else [here]):
            path = os.path.join(place, name)
            if not os.path.isfile(path):
                continue
            try:
                text, _ = read_text(path)
            except Exception:                    # noqa: BLE001 — нечитаемый файл = нет правил
                continue
            got = parse(text, name, host)
            if got:
                rules += got
                try:
                    found.append(os.path.relpath(path))
                except ValueError:               # другой диск в Windows
                    found.append(path)
            break
    return rules, found


def _match(rules: list, url: str, present: bool = False):
    """
    Первое правило, которое сработает на этот адрес: (совпадение, правило).
    `present` — страница есть в сборке: тогда действуют только правила,
    которые срабатывают раньше файла, и только те, что точно касаются сайта.
    """
    path = urlsplit(url).path or "/"
    for rule in rules:
        if present and not (rule.force and rule.sure):
            continue
        # Правило могут записать кириллицей, а адрес страницы — в процент-кодировке.
        for form in ((path, unquote(path)) if "%" in path else (path,)):
            found = rule.pattern.match(form.rstrip("/") or "/") or rule.pattern.match(form)
            if found:
                return found, rule
    return None, None


def redirect_for(rules: list, url: str) -> str:
    """Куда правила переводят адрес; пусто — никуда, на живом сайте будет 404."""
    _, rule = _match(rules, url)
    return rule.target if rule and rule.kind in ("redirect", "rewrite") else ""


def _fill(found, target: str, url: str, same_site: bool = False) -> str:
    groups = found.groupdict()
    numbered = found.groups()
    unknown = []

    def named(m):
        value = groups.get(m.group(1))
        if value is None:
            unknown.append(m.group(0))
            return ""
        return value

    def indexed(m):
        n = int(m.group(1))
        if not 1 <= n <= len(numbered) or numbered[n - 1] is None:
            unknown.append(m.group(0))
            return ""
        return numbered[n - 1]

    target = target.split("?")[0].split("#")[0]
    site = urlsplit(url)
    netloc = site.netloc
    if "://" in target:
        parts = urlsplit(target)
        if parts.netloc.lower() != site.netloc.lower():
            if not (same_site and _host_match(parts.netloc, site.netloc) is not False):
                return ""
            netloc = parts.netloc
        target = parts.path or "/"
    if not target.startswith("/"):
        return ""
    target = re.sub(r":([A-Za-z_]\w*)\*?", named, target)
    target = re.sub(r"\$(\d+)", indexed, target)
    if unknown or "*" in target:
        return ""
    return f"{site.scheme}://{netloc}{target}"


def destination(rules: list, url: str) -> str:
    """
    Полный адрес, куда редирект ведёт этот адрес, с подставленными `:splat`,
    `:name`, `:name*` и `$1`. Пусто — если цель на другом хосте или
    подставить нечего: такую цель проверить по сборке нельзя.
    """
    found, rule = _match(rules, url)
    if not found or rule.kind not in ("redirect", "rewrite"):
        return ""
    return _fill(found, rule.target, url, same_site=True)


def _unfillable(rules: list, url: str) -> bool:
    """
    Цель правила — на этом же сайте, но подставить в неё нечего: `:slug`,
    которого нет в источнике, или `*` в цели. Все адреса уходят на одну
    несуществующую страницу.
    """
    found, rule = _match(rules, url)
    if not found or rule.kind not in ("redirect", "rewrite"):
        return False
    target = rule.target.split("?")[0].split("#")[0]
    if "://" in target:
        parts = urlsplit(target)
        if _host_match(parts.netloc, urlsplit(url).netloc) is False:
            return False
        target = parts.path or "/"
    return target.startswith("/") and not _fill(found, rule.target, url, same_site=True)


def _dead_end(rules: list, new: dict, full: str, start: str) -> tuple:
    """
    Куда в итоге приводит цель редиректа в новой сборке: идёт по заглушкам
    и правилам. ("", адрес) — к открытой странице или проверить нельзя;
    ("missing", адрес) — в адрес, которого нет; ("closed", адрес) — к странице
    с noindex или черновику; ("loop", адрес) — редиректы идут по кругу.
    """
    seen = {start}
    for _ in range(10):
        key = url_key(full)
        if key in seen:
            return "loop", full
        seen.add(key)
        page = new.get(key)
        if page is None:
            found, rule = _match(rules, full)
            if not rule or rule.kind not in ("redirect", "rewrite"):
                return "missing", full
            nxt = _fill(found, rule.target, full, same_site=True)
            if not nxt:
                return "", full
            full = nxt
            continue
        found, rule = _match(rules, page.url, present=True)
        if rule and rule.kind in ("redirect", "rewrite"):
            nxt = _fill(found, rule.target, page.url, same_site=True)
            if nxt and url_key(nxt) != key:
                full = nxt
                continue
        stub = redirect_target(page)
        if stub:
            nxt = urljoin(page.url, stub)
            if _host_match(urlsplit(nxt).netloc, urlsplit(page.url).netloc) is False:
                return "", full
            full = nxt
            continue
        if not indexable(page) and _why_closed(page)[0] in ("noindex", "draft"):
            return "closed", page.url
        return "", page.url
    return "", full


# ── сравнение ─────────────────────────────────────────────────────────────────

def _h1(page) -> str:
    for level, text in getattr(page, "headings", None) or ():
        if level == 1:
            return text
    return ""


def _field(page, name: str) -> str:
    if name == "url":
        return urlsplit(page.url).path or "/"
    if name == "canonical":
        return urljoin(page.url, page.canonical.strip()) if page.canonical else ""
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
    if page.canonical and (url_key(page.canonical) != page.key
                           or page.__dict__.get("_canonical_origin")):
        return "canonical", page.canonical
    return "other", ""


def _shadowed(rules: list, page, new_keys: dict):
    """
    Страница есть в новой сборке, но правило, которое срабатывает раньше
    файла (`redirects` в vercel.json, `301!` у Netlify), отвечает по её
    адресу иначе. Редирект на себя — `/x/` → `/x` — не в счёт.
    """
    found, rule = _match(rules, page.url, present=True)
    if not rule or rule.kind == "rewrite":
        return None
    item = {"url": page.url, "detail": rule.target, "origin": rule.origin,
            "status": rule.status, "redirect_missing": None}
    if rule.kind == "error":
        return dict(item, reason="rule-error", level="critical")
    if rule.kind == "soft404":
        return dict(item, reason="rule-soft404", level="critical")
    full = _fill(found, rule.target, page.url, same_site=True)
    if full and url_key(full) == page.key:
        return None
    if not full:
        level = "warning"                   # другой хост: проверить по сборке нельзя
    elif url_key(full) == url_key(urljoin(page.url, "/")):
        level = "critical"                  # раздел на главную — мягкий 404
    elif url_key(full) not in new_keys:
        level, item["redirect_missing"] = "warning", full
    else:
        level = "info"
        why, end = _dead_end(rules, new_keys, full, page.key)
        if why == "missing":
            level, item["redirect_missing"] = "warning", end
        elif why:
            level, item["redirect_dead"], item["redirect_end"] = "warning", why, end
    return dict(item, reason="redirect-rule", level=level, detail=full or rule.target)


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
        _, rule = _match(rules, page.url)
        target = redirect_for(rules, page.url)
        level = "critical" if was_open and not target else "info"
        missing_target = ""
        # Цель с `:splat` проверяется так же, как простая: `/rent/* /flat/:splat`
        # при разделе /flats/ ведёт каждую страницу в 404.
        full = destination(rules, page.url) if target else ""
        dead, end = "", ""
        if was_open and full and url_key(full) == url_key(urljoin(page.url, "/")):
            # Раздел на главную — мягкий 404, как и у правила раньше файла.
            level, dead = "critical", "home"
        elif was_open and full:
            why, end = _dead_end(rules, new, full, key)
            if why == "missing":
                level, missing_target = "warning", end
            elif why:
                level, dead = "warning", why
        elif was_open and target and _unfillable(rules, page.url):
            level, missing_target = "warning", target
        # Правило 404/410 или перезапись 200 на главную — тоже ответ, но не
        # редирект: на живом сайте по адресу ошибка или мягкий 404.
        if full and url_key(full) in new_keys:
            full = new[url_key(full)].url
        answer = rule if rule and rule.kind in ("error", "soft404") else None
        removed.append({"url": page.url, "level": level, "indexable_before": was_open,
                        "redirect": target or None, "redirect_to": full or None,
                        "redirect_missing": missing_target or None,
                        "redirect_dead": dead or None,
                        "redirect_end": end if dead in ("closed", "loop") else None,
                        "answer": answer.status if answer else None,
                        "answer_rule": answer.origin if answer else None})

    closed, opened, nosnippet, shrunk = [], [], [], []
    both = sorted(set(old) & new_keys)
    for key in both:
        a, b = old[key], new[key]
        was, now = indexable(a), indexable(b)
        if was and not now:
            reason, detail = _why_closed(b)
            level, missing = ("info" if reason == "redirect" else "critical"), ""
            dead, end = "", ""
            if reason == "redirect":
                # Заглушка, которая ведёт в пустоту, — то же, что редирект
                # удалённой страницы в пустоту.
                full = urljoin(b.url, detail)
                if _host_match(urlsplit(full).netloc, urlsplit(b.url).netloc) is not False:
                    why, end = _dead_end(rules, new, full, key)
                    if why == "missing":
                        level, missing = "warning", end
                    elif why:
                        level, dead = "warning", why
            closed.append({"url": b.url, "reason": reason, "detail": detail,
                           "level": level, "redirect_missing": missing or None,
                           "redirect_dead": dead or None,
                           "redirect_end": end if dead else None})
        elif was and now and rules:
            shadow = _shadowed(rules, b, new)
            if shadow:
                closed.append(shadow)
        if now and not was:
            opened.append(b.url)
        if now and b.nosnippet and not a.nosnippet:
            nosnippet.append(b.url)
        before, after = a.word_count, b.word_count
        if now and before >= SHRINK_MIN_WORDS and after < before * (1 - SHRINK_SHARE):
            shrunk.append({"url": b.url, "old_words": before, "new_words": after,
                           "drop": round(1 - after / before, 3)})

    # Раздел, уехавший редиректом на новые адреса, сравнивается парами
    # «старый адрес → новый»: срезанный текст и запрет сниппета видны и там.
    # Пара — только когда на новую страницу ведёт одна старая.
    targets = Counter(url_key(r["redirect_to"]) for r in removed if r["redirect_to"])
    for r in removed:
        to = url_key(r["redirect_to"] or "")
        if r["level"] != "info" or not r["indexable_before"] or targets[to] != 1 \
                or to in old or to not in new:
            continue
        a, b = old.get(url_key(r["url"])), new[to]
        if a is None or not indexable(b):
            continue
        if b.nosnippet and not a.nosnippet:
            nosnippet.append(b.url)
        before, after = a.word_count, b.word_count
        if before >= SHRINK_MIN_WORDS and after < before * (1 - SHRINK_SHARE):
            shrunk.append({"url": b.url, "old_words": before, "new_words": after,
                           "drop": round(1 - after / before, 3)})

    pattern_of = _patterns(new[k].url for k in both)
    totals = Counter(pattern_of.values())
    changed = defaultdict(list)
    for key in both:
        a, b = old[key], new[key]
        for name in FIELDS:
            before, after = _field(a, name), _field(b, name)
            if name == "canonical" and not (before and after):
                continue
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


FIELD_LABEL = {"title": "title", "h1": "H1", "description": "description",
               "canonical": "canonical", "url": "URL"}


def _dead_text(item: dict) -> str:
    """Хвост сообщения о редиректе, который ведёт не к открытой странице."""
    why = item.get("redirect_dead")
    if why == "home":
        return " — " + tr("редирект на главную поиск считает мягким 404: страница выпадет "
                          "из индекса")
    if why == "closed":
        return " — " + tr("а цепочка редиректов приводит к странице, закрытой от индекса: {a0}",
                          a0=item.get("redirect_end"))
    if why == "loop":
        return " — " + tr("а дальше редиректы идут по кругу")
    return ""


def _reason_text(item: dict) -> str:
    reason, detail = item["reason"], item["detail"]
    if reason == "noindex":
        return tr("появился noindex: meta robots «{a0}»", a0=detail)
    if reason == "canonical":
        return tr("canonical теперь ведёт на {a0}", a0=detail)
    if reason == "draft":
        return tr("страница стала черновиком")
    if reason == "redirect":
        if item.get("redirect_missing"):
            return tr("страница стала заглушкой-редиректом на {a0} — а этой страницы в новой "
                      "сборке нет", a0=item["redirect_missing"])
        return tr("страница стала заглушкой-редиректом на {a0}", a0=detail) + _dead_text(item)
    if reason == "redirect-rule":
        if item.get("redirect_missing"):
            return tr("страница есть в новой сборке, но правило из {a0} срабатывает раньше "
                      "файла и уводит её на {a1} — а этой страницы в новой сборке нет",
                      a0=item["origin"], a1=item["redirect_missing"])
        return tr("страница есть в новой сборке, но правило из {a0} срабатывает раньше файла "
                  "и уводит её на {a1}", a0=item["origin"], a1=detail) + _dead_text(item)
    if reason == "rule-error":
        return tr("страница есть в новой сборке, но правило из {a0} срабатывает раньше файла "
                  "и отвечает кодом {a1}", a0=item["origin"], a1=item["status"])
    if reason == "rule-soft404":
        return tr("страница есть в новой сборке, но правило из {a0} срабатывает раньше файла "
                  "и отдаёт по её адресу главную с кодом 200 — это мягкий 404",
                  a0=item["origin"])
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
                        tr("страницы нет, редирект на {a0}",
                           a0=r.get("redirect_to") or r["redirect"]) + _dead_text(r)))
        elif r.get("answer") and r["indexable_before"]:
            if r["answer"].startswith("200"):
                out.append((r["level"], r["url"], "page-removed", tr(
                    "была открыта для индекса, в новой сборке её нет, а правило из {a0} "
                    "отдаёт по этому адресу главную с кодом 200 — это мягкий 404",
                    a0=r["answer_rule"])))
            else:
                out.append((r["level"], r["url"], "page-removed", tr(
                    "была открыта для индекса, в новой сборке её нет, а правило из {a0} "
                    "отвечает по этому адресу кодом {a1}", a0=r["answer_rule"], a1=r["answer"])))
        elif r["indexable_before"]:
            out.append((r["level"], r["url"], "page-removed", tr(
                "была открыта для индекса, в новой сборке её нет и редиректа нет — "
                "на живом сайте будет 404")))
        else:
            out.append((r["level"], r["url"], "page-removed",
                        tr("страницы нет; она и раньше была закрыта от индекса")))
    for c in result["closed"]:
        code = "page-redirected" if c["reason"] in ("redirect", "redirect-rule") else "page-closed"
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


def moved_findings(old_issues: list, result: dict, new_pages: list) -> list:
    """
    Находки старой сборки, перенесённые на адреса, куда редирект увёл их
    страницы. Раздел переехал под `/en/` — старые дубли и слабые места те же,
    и в новой сборке они не новые. Адрес в предмете находки (страница-близнец,
    цель ссылки) переносится так же, в той же форме — ключом, полным адресом или путём.
    """
    new_by_key = {p.key: p.url for p in new_pages}
    # Переезд — только на страницу, которой в старой сборке не было. Страница,
    # слитая редиректом в уже существующую, своих находок цели не передаёт:
    # иначе новая поломка цели совпадала со старой находкой удалённой.
    fresh = {url_key(u) for u in (result.get("added") or {}).get("urls") or ()}
    moved = {}
    for r in result.get("removed") or ():
        to = r.get("redirect_to")
        if to and url_key(to) in new_by_key and url_key(to) in fresh:
            moved[url_key(r["url"])] = new_by_key[url_key(to)]
    if not moved:
        return old_issues
    site = next(iter(new_by_key.values()))

    def move(value):
        if not isinstance(value, str) or not value.startswith(("/", "http://", "https://")):
            return value
        got = moved.get(url_key(urljoin(site, value)))
        if not got:
            return value
        if value.startswith("//"):          # предмет записан ключом адреса
            return url_key(got)
        return got if "://" in value else (urlsplit(got).path or "/")

    out = []
    for item in old_issues:
        item = dict(item)
        item["url"] = move(item.get("url"))
        if isinstance(item.get("subject"), list):
            item["subject"] = [move(v) for v in item["subject"]]
        out.append(item)
    return out
