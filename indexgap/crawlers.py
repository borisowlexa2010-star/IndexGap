# -*- coding: utf-8 -*-
"""
ИИ-краулеры по логам сервера: кто из них на самом деле приходил и за чем.

Выгрузка Search Console говорит, что знает Google. Про ChatGPT, Claude и
Perplexity такой панели нет, но их боты оставляют след в access-логе —
это единственные точные данные о том, видит ли ИИ-поиск страницы, и для них
не нужны ни ключи, ни деньги.

Главное различие — зачем бот пришёл. У одного оператора их несколько:

  * обучение (GPTBot, ClaudeBot, CCBot) — данные для будущих моделей; на то,
    процитируют ли страницу в ответе сегодня, не влияет;
  * поиск (OAI-SearchBot, Claude-SearchBot, PerplexityBot) — индекс, из
    которого ассистент берёт источники ответа;
  * по запросу человека (ChatGPT-User, Claude-User, Perplexity-User) —
    кто-то задал вопрос, и ассистент открыл страницу, чтобы ответить.
    Ближе к «нас цитируют» по логам не подобраться.

Закрывать robots.txt «ИИ-ботов» целиком, не различая этих трёх, — частая
ошибка: вместе с обучением уходит и поиск.

User-Agent пишет сам клиент, и подделать его можно. Проверка по обратному DNS
или опубликованным диапазонам адресов требует сети, поэтому здесь её нет —
и отчёт это говорит, а не молчит.
"""

from __future__ import annotations

import gzip
import http.client
import json
import os
import re
import urllib.request
from collections import Counter
from urllib.parse import unquote, urlsplit

from .core import SourceError, url_key
from .i18n import N_, tr

TRAINING = "training"
AI_SEARCH = "ai-search"
AI_USER = "ai-user"
SEARCH = "search"

PURPOSE_TITLE = {
    TRAINING: N_("обучение моделей"),
    AI_SEARCH: N_("ИИ-поиск"),
    AI_USER: N_("ИИ по запросу человека"),
    SEARCH: N_("поисковик"),
}

# (подстрока User-Agent, имя бота, оператор, назначение). Порядок важен:
# более длинное имя проверяется раньше того, что в нём содержится.
BOTS = (
    ("oai-searchbot", "OAI-SearchBot", "OpenAI", AI_SEARCH),
    ("chatgpt-user", "ChatGPT-User", "OpenAI", AI_USER),
    ("gptbot", "GPTBot", "OpenAI", TRAINING),
    ("claude-searchbot", "Claude-SearchBot", "Anthropic", AI_SEARCH),
    ("claude-user", "Claude-User", "Anthropic", AI_USER),
    ("claude-web", "Claude-Web", "Anthropic", AI_USER),
    ("claudebot", "ClaudeBot", "Anthropic", TRAINING),
    ("anthropic-ai", "anthropic-ai", "Anthropic", TRAINING),
    ("perplexity-user", "Perplexity-User", "Perplexity", AI_USER),
    ("perplexitybot", "PerplexityBot", "Perplexity", AI_SEARCH),
    ("mistralai-user", "MistralAI-User", "Mistral", AI_USER),
    ("duckassistbot", "DuckAssistBot", "DuckDuckGo", AI_USER),
    ("meta-externalfetcher", "meta-externalfetcher", "Meta", AI_USER),
    ("meta-externalagent", "meta-externalagent", "Meta", TRAINING),
    ("youbot", "YouBot", "You.com", AI_SEARCH),
    ("amazonbot", "Amazonbot", "Amazon", AI_SEARCH),
    ("applebot", "Applebot", "Apple", SEARCH),
    ("bytespider", "Bytespider", "ByteDance", TRAINING),
    ("ccbot", "CCBot", "Common Crawl", TRAINING),
    ("cohere-ai", "cohere-ai", "Cohere", TRAINING),
    ("googlebot", "Googlebot", "Google", SEARCH),
    ("bingbot", "bingbot", "Microsoft", SEARCH),
)

AI_PURPOSES = (AI_SEARCH, AI_USER)

# Обычный «combined» формат nginx и Apache; хвост с referer и UA бывает не всегда.
_COMBINED = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>[A-Z]+) (?P<target>\S+)(?: [^"]*)?" (?P<status>\d{3}) \S+'
    r'(?: "(?P<referer>[^"]*)" "(?P<ua>[^"]*)")?')

# Поля, которыми JSON-логи разных CDN и хостингов называют одно и то же.
_JSON_TARGET = ("url", "uri", "path", "request_uri", "requestUri", "requestPath",
                "ClientRequestURI", "ClientRequestPath", "request_path", "cs-uri-stem")
_JSON_HOST = ("host", "ClientRequestHost", "hostname", "requestHost")
_JSON_UA = ("user_agent", "userAgent", "http_user_agent", "ua",
            "ClientRequestUserAgent", "cs(User-Agent)", "agent")
_JSON_STATUS = ("status", "status_code", "statusCode", "EdgeResponseStatus",
                "OriginResponseStatus", "sc-status", "response_status")
_JSON_METHOD = ("method", "request_method", "ClientRequestMethod", "cs-method")
_JSON_IP = ("clientIp", "ClientIP", "client_ip", "remote_addr", "remoteAddr", "ip",
            "c-ip", "realIp", "x_forwarded_for")

# Страница — то, у чего нет расширения или расширение страничное.
_PAGE_EXT = {"", "html", "htm", "php", "asp", "aspx", "jsp", "shtml", "xhtml"}


def identify(user_agent: str) -> tuple:
    """(имя, оператор, назначение) или пустой кортеж, если это не известный бот."""
    lowered = (user_agent or "").lower()
    for token, name, operator, purpose in BOTS:
        if token in lowered:
            return name, operator, purpose
    return ()


def _first(record: dict, names: tuple):
    for name in names:
        if name in record and record[name] not in (None, ""):
            return record[name]
    return None


def parse_line(line: str) -> dict:
    """
    Одна строка лога → {target, host, status, method, ua} или {}.
    Понимает combined-формат и JSON-строки (Cloudflare, Vercel, Fastly и т. п.).
    """
    line = line.strip()
    if not line:
        return {}
    if line.startswith("{"):
        try:
            record = json.loads(line)
        except ValueError:
            return {}
        if not isinstance(record, dict):
            return {}
        # Вложенные «request»/«http» у некоторых хостингов; у Vercel (log
        # drain) запрос лежит в «proxy», а User-Agent там — список строк.
        for nest in ("proxy", "request", "http", "httpRequest"):
            inner = record.get(nest)
            if isinstance(inner, dict):
                record = {**record, **inner}
        target = _first(record, _JSON_TARGET)
        ua = _first(record, _JSON_UA)
        if isinstance(ua, list):
            ua = " ".join(str(u) for u in ua)
        if not target or not ua:
            return {}
        try:
            status = int(_first(record, _JSON_STATUS) or 0)
        except (TypeError, ValueError):
            status = 0
        ip = str(_first(record, _JSON_IP) or "").split(",")[0].strip()
        return {"target": str(target), "host": str(_first(record, _JSON_HOST) or ""),
                "status": status, "method": str(_first(record, _JSON_METHOD) or "GET").upper(),
                "ua": str(ua), "ip": ip}
    match = _COMBINED.match(line)
    if not match or not match.group("ua"):
        return {}
    return {"target": match.group("target"), "host": "", "status": int(match.group("status")),
            "method": match.group("method"), "ua": match.group("ua"), "ip": match.group("ip")}


def _open(path: str):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def _is_page(path: str) -> bool:
    last = path.rstrip("/").rsplit("/", 1)[-1]
    ext = last.rsplit(".", 1)[-1].lower() if "." in last else ""
    return ext in _PAGE_EXT


def read_logs(paths: list, site: str = "") -> dict:
    """
    Читает логи и собирает, какой бот какие страницы запрашивал и с каким ответом.

    Ключ страницы — тот же `url_key`, что у воронки: `/виза/` из лога и
    `/%D0%B2…/` со страницы сборки — одна страница.
    """
    if not paths:
        return {}
    base = site.rstrip("/") if site else ""
    events = []
    lines = matched = 0
    for path in paths:
        if not os.path.exists(path):
            raise SourceError(tr("Лог {a0} не найден.", a0=path))
        if os.path.isdir(path):
            raise SourceError(tr("{a0} — каталог; нужен файл лога (можно .gz).", a0=path))
        with _open(path) as fh:
            for raw in fh:
                lines += 1
                hit = parse_line(raw)
                if not hit or hit["method"] not in ("GET", "HEAD"):
                    continue
                who = identify(hit["ua"])
                if not who:
                    continue
                matched += 1
                name, operator, purpose = who
                target = hit["target"]
                parts = urlsplit(target)
                if parts.scheme:
                    url = target.split("#")[0]
                    path_only = parts.path or "/"
                else:
                    path_only = unquote(target.split("?")[0].split("#")[0]) or "/"
                    host = hit["host"]
                    root = f"https://{host}" if host and not base else base
                    url = (root or "") + (target.split("#")[0] if target.startswith("/") else "/" + target)
                events.append((name, operator, purpose, hit["status"], hit.get("ip", ""),
                               path_only, url))
    if not matched:
        raise SourceError(tr(
            "В логах ({a0} строк) нет ни одного известного бота. Либо это не "
            "access-лог (нужен формат combined nginx/Apache или JSON-строки), "
            "либо User-Agent в нём не пишется.", a0=lines))
    return {"lines": lines, "bot_hits": matched, "bots": _aggregate(events),
            "events": events}


def _aggregate(events: list) -> dict:
    """Сводка по ботам из отдельных запросов: страницы, ответы, robots.txt, адреса."""
    bots = {}
    for name, operator, purpose, status, ip, path_only, url in events:
        bot = bots.setdefault(name, {
            "name": name, "operator": operator, "purpose": purpose,
            "hits": 0, "statuses": Counter(), "pages": {}, "robots_txt": 0, "ips": Counter()})
        bot["hits"] += 1
        bot["statuses"][status] += 1
        if ip:
            bot["ips"][ip] += 1
        if path_only.rstrip("/").endswith("robots.txt"):
            bot["robots_txt"] += 1
            continue
        if not _is_page(path_only):
            continue
        key = url_key(url.split("?")[0]) if url else path_only
        page = bot["pages"].setdefault(key, {"url": url.split("?")[0], "hits": 0,
                                             "ok": 0, "errors": Counter()})
        page["hits"] += 1
        if 200 <= status < 400:
            page["ok"] += 1
        elif status:
            page["errors"][status] += 1
    return bots


def coverage(pages: list, logs: dict, verified: dict = None) -> dict:
    """
    Сводит логи со страницами сборки: какие страницы ИИ-поиск открыл, какие
    нет, и где бот получил ошибку на странице, которая существует.
    """
    from .publish import indexable

    if not logs:
        return {}
    display = {url_key(p.url): p.url for p in pages}
    publishable = {url_key(p.url) for p in pages if indexable(p)}
    by_purpose = {purpose: set() for purpose in PURPOSE_TITLE}
    rows, errors = [], []
    for name, bot in sorted(logs["bots"].items(), key=lambda kv: -kv[1]["hits"]):
        fetched = {k for k, v in bot["pages"].items() if v["ok"]} & publishable
        by_purpose[bot["purpose"]] |= fetched
        failed = {k: v for k, v in bot["pages"].items() if v["errors"] and k in display}
        statuses = bot["statuses"]
        rows.append({
            "name": name, "operator": bot["operator"], "purpose": bot["purpose"],
            "hits": bot["hits"], "pages": len(fetched), "of": len(publishable),
            "errors": sum(1 for _ in failed), "robots_txt": bot["robots_txt"],
            "forbidden": sum(n for s, n in statuses.items() if s in (401, 403)),
            "statuses": {str(s): n for s, n in sorted(statuses.items())},
        })
        for key, page in sorted(failed.items()):
            if page["ok"]:
                continue          # однажды получил — значит, ошибка была временной
            errors.append({"bot": name, "purpose": bot["purpose"], "url": display[key],
                           "statuses": {str(s): n for s, n in sorted(page["errors"].items())}})

    ai_seen = by_purpose[AI_SEARCH] | by_purpose[AI_USER]
    notes = []
    for row in rows:
        # Массовый 403 ИИ-боту — почти всегда защита CDN, а не robots.txt:
        # Cloudflare с 2025 года блокирует ИИ-краулеров по умолчанию.
        if row["purpose"] in AI_PURPOSES and row["forbidden"] >= max(5, 0.5 * row["hits"]):
            notes.append(tr(
                "{a0}: {a1} из {a2} запросов получили 401/403. Похоже, его отсекает "
                "защита CDN или WAF, а не robots.txt (Cloudflare блокирует ИИ-ботов "
                "по умолчанию) — страницы для этого ИИ-поиска закрыты, хотя robots.txt "
                "их разрешает", a0=row["name"], a1=row["forbidden"], a2=row["hits"]))
    if not any(r["purpose"] in AI_PURPOSES for r in rows):
        notes.append(tr(
            "в логах нет ни одного бота ИИ-поиска (OAI-SearchBot, Claude-SearchBot, "
            "PerplexityBot) и ни одного визита по запросу человека. Для ИИ-ответов "
            "сайт пока невидим — проверь robots.txt и защиту CDN"))
    if verified is None:
        notes.append(tr(
            "Бот определён по User-Agent, а его может подделать кто угодно. Адреса "
            "не проверялись — это делает --verify-bots (ходит в сеть)"))
    return {
        "bots": rows,
        "errors": errors,
        "fetched": {purpose: sorted(display[k] for k in keys)
                    for purpose, keys in by_purpose.items()},
        "ai_not_fetched": sorted(display[k] for k in publishable - ai_seen),
        "ai_fetched_count": len(ai_seen),
        "publishable": len(publishable),
        "lines": logs["lines"],
        "notes": notes,
        "verified": verified,
    }


# ── подлинность ботов ──────────────────────────────────────────────────────────

# Опубликованные операторами диапазоны адресов (формат {"prefixes": [{"ipv4Prefix"…}]}).
RANGES = {
    "GPTBot": "https://openai.com/gptbot.json",
    "OAI-SearchBot": "https://openai.com/searchbot.json",
    "ChatGPT-User": "https://openai.com/chatgpt-user.json",
    "PerplexityBot": "https://www.perplexity.com/perplexitybot.json",
    "Perplexity-User": "https://www.perplexity.com/perplexity-user.json",
    "Googlebot": "https://developers.google.com/static/search/apis/ipranges/googlebot.json",
    "bingbot": "https://www.bing.com/toolbox/bingbot.json",
}
# Обратный DNS с прямым подтверждением — там, где оператор описывает такую проверку.
RDNS = {
    "Googlebot": ("googlebot.com", "google.com"),
    "bingbot": ("search.msn.com",),
    "Applebot": ("applebot.apple.com",),
}


def _prefixes(data) -> list:
    import ipaddress
    out = []
    for item in (data or {}).get("prefixes") or ():
        for key in ("ipv4Prefix", "ipv6Prefix"):
            if isinstance(item, dict) and item.get(key):
                try:
                    out.append(ipaddress.ip_network(item[key], strict=False))
                except ValueError:
                    pass
    return out


def _fetch_ranges(url: str, timeout: int = 15):
    from .core import request
    with urllib.request.urlopen(request(url), timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _rdns_ok(ip: str, domains: tuple) -> bool:
    """Имя по адресу из домена оператора, и это имя ведёт обратно на тот же адрес."""
    import socket
    try:
        host = socket.gethostbyaddr(ip)[0].rstrip(".").lower()
    except (OSError, UnicodeError):
        return False
    if not any(host == d or host.endswith("." + d) for d in domains):
        return False
    try:
        return ip in socket.gethostbyname_ex(host)[2]
    except (OSError, UnicodeError):
        return False


def verify(logs: dict, fetch=None, rdns=None) -> dict:
    """
    Подлинен ли каждый адрес, с которого пришёл бот: в опубликованных
    диапазонах оператора или подтверждён DNS. Ходит в сеть — только по флагу.

    Возвращает {бот: {"method", "genuine", "spoofed", "unknown", "spoofed_hits"}}
    и множество поддельных пар (бот, адрес) под ключом "_spoofed".
    """
    import ipaddress
    fetch = fetch or _fetch_ranges
    rdns = rdns or _rdns_ok
    out, spoofed = {}, set()
    for name, bot in sorted((logs or {}).get("bots", {}).items()):
        ips = bot.get("ips") or {}
        if not ips:
            continue
        nets, method = None, ""
        if name in RANGES:
            try:
                nets = _prefixes(fetch(RANGES[name]))
                method = "ranges" if nets else ""
            except (OSError, ValueError, TimeoutError, http.client.HTTPException):
                nets = None
        row = {"method": method, "genuine": 0, "spoofed": 0, "unknown": 0, "spoofed_hits": 0}
        for ip, hits in ips.items():
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                row["unknown"] += 1
                continue
            if nets:
                verdict = any(addr in net for net in nets)
            elif name in RDNS:
                row["method"] = "dns"
                verdict = rdns(ip, RDNS[name])
            else:
                row["unknown"] += 1
                continue
            if verdict:
                row["genuine"] += 1
            else:
                row["spoofed"] += 1
                row["spoofed_hits"] += hits
                spoofed.add((name, ip))
        out[name] = row
    out["_spoofed"] = spoofed
    return out


def without_spoofed(logs: dict, spoofed: set) -> dict:
    """Те же логи без запросов с поддельных адресов — цифры по ботам честнее."""
    if not spoofed:
        return logs
    events = [e for e in logs["events"] if (e[0], e[4]) not in spoofed]
    return {**logs, "events": events, "bots": _aggregate(events),
            "bot_hits": len(events)}
