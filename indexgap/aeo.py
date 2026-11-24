# -*- coding: utf-8 -*-
"""
Машинная читаемость: то, что решает, сможет ли ИИ-поиск взять со страницы ответ.

Границу стоит провести сразу, потому что вокруг неё много продаваемого воздуха.

**Что проверяется здесь.** Не мешает ли страница сама себе: не закрыта ли
от сниппетов, не заблокированы ли краулеры ИИ-поисковиков в robots.txt,
есть ли на странице текст в исходном HTML, есть ли прямой ответ в первом
абзаце, размечены ли даты и автор, валиден ли JSON-LD. Это необходимые
условия, и они проверяются локально и детерминированно.

**Чего здесь нет и быть не может.** Обещания цитирований. По данным Ahrefs
на 75 000 брендов с видимостью в ИИ-поиске сильнее всего коррелируют
упоминания вне сайта (0,66–0,74), а количество страниц на сайте — 0,19.
76% цитат в AI Overviews — страницы из топ-10 обычной выдачи. То есть
попадание в ответ определяется работой за пределами файлов проекта.
Пакет делает первую половину и честно говорит, что вторая — не про код.

Отдельно про `llms.txt`: генератора нет намеренно. Google публично заявил,
что не поддерживает и не планирует, ни один движок не подтвердил
использование для ранжирования. Генерировать файл, который никто не читает,
значит продавать ученику ритуал.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter

from .checks import is_shell
from .i18n import N_, tr

CONFIG = {
    "answer_min": 40,           # символов в прямом ответе
    "answer_max": 320,
    "shell_words": 100,         # меньше слов при N скриптах — пустой JS-каркас
    "shell_scripts": 3,
    "long_paragraph": 900,      # символов без подзаголовка — плохо извлекается
    "question_share": 0.3,      # доля вопросных подзаголовков, ниже которой стоит сказать
}

# Разгон вместо ответа. Первое предложение, начинающееся так, для ИИ-поиска
# пустое: цитировать нечего.
PREAMBLE = (
    "в этой статье", "в данной статье", "в этом материале", "мы рассмотрим",
    "давайте разберёмся", "давайте разберемся", "сегодня мы", "как известно",
    "ни для кого не секрет", "в современном мире",
    "in this article", "in this post", "in this blog post", "in this guide",
    "we will explore", "let's dive", "let's explore", "let us explore",
    "as we all know", "in today's", "welcome to",
)


def _is_preamble(lowered: str) -> bool:
    """
    Начинается ли абзац с разгона. Фраза должна кончиться на границе слова:
    «in this post-pandemic market…» — не «in this post».
    """
    for phrase in PREAMBLE:
        if lowered.startswith(phrase):
            rest = lowered[len(phrase):len(phrase) + 1]
            if not rest or not (rest.isalnum() or rest == "-"):
                return True
    # «Updated: in this article we will…» — подпись-ярлык перед тем же разгоном.
    label = re.match(r"[^\s:]{1,20}:\s+", lowered)
    return bool(label) and _is_preamble(lowered[label.end():])


# В ar/fa/ur используется U+061F: без него восемь вопросных заголовков
# выглядели как ноль. Это тот же вопросный знак, а не исключение из порога.
# Вопрос — это знак вопроса в конце или вопросительное слово. Где оно стоит,
# зависит от языка: в русском, английском, арабском, индонезийском — в начале
# («أين ستقيم», «Apa sebenarnya yang dilihat konsulat»), а в хинди, бенгали, фарси,
# китайском и японском — внутри фразы («दूतावास वास्तव में क्या देख रहा है»,
# «您将住在哪里»). Раньше слова знались только русские и английские, и на
# многоязычном сайте вопросы без «?» в половине языков не считались вопросами.
_Q_START = (
    "как|что|где|когда|почему|зачем|сколько|какой|какая|какие|какое|кто|можно ли|нужно ли|"
    "how|what|where|when|why|who|which|can|do|does|is|are|should|will|"
    "wie|was|wo|wann|warum|wer|welche|welcher|kann|muss|"
    "comment|quoi|où|quand|pourquoi|qui|quel|quelle|quels|est-ce|"
    "cómo|qué|dónde|cuándo|por qué|quién|cuál|cuánto|"
    "como|o que|onde|quando|por que|quem|qual|quanto|"
    "cosa|dove|perché|chi|quale|quanto|"
    "apa|apakah|bagaimana|mengapa|kenapa|kapan|bila|bilakah|di mana|siapa|berapa|adakah|"
    "nasıl|nerede|neden|hangi|"
    "ما|ماذا|كيف|متى|أين|لماذا|كم|هل|"
    "کیا|چه|چگونه|چطور|کجا|چرا|آیا"
)
_INDIC = "\u0900-\u0dff\u0600-\u06ff"
_Q_INSIDE = (
    "क्या|कैसे|कब|कहाँ|कहां|क्यों|कौन|कितना|कितने|कितनी|"
    "কি|কী|কীভাবে|কিভাবে|কখন|কোথায়|কেন|কে|কত|"
    "کیسے|کب|کہاں|کیوں|کون|کتنا|کتنے|"
    "چه|چگونه|کجا|چرا|چند"
)
_Q_CJK = "什么|甚麼|哪里|哪裡|哪儿|哪个|怎么|怎样|如何|为什么|為什麼|多少|几|是否|吗|嗎|呢|何|どう|なぜ|いつ|どこ|だれ|誰|ですか|무엇|어떻게|언제|어디|왜|누구|얼마|나요"
# Тайский вопрос пишется без знака: вопросительное слово или частица внутри
# фразы, слова не разделены пробелами («ค่าวีซ่าเท่าไหร่»).
_Q_THAI = ("อะไร|เท่าไหร่|เท่าไร|ไหม|มั้ย|อย่างไร|ยังไง|แค่ไหน|ที่ไหน|เมื่อไหร่|เมื่อไร|"
           "ทำไม|ใคร|หรือไม่|หรือเปล่า")
QUESTION = re.compile(
    "^(?:" + _Q_START + ")(?![\\w" + _INDIC + "])"
    "|(?<![\\w" + _INDIC + "])(?:" + _Q_INSIDE + ")(?![\\w" + _INDIC + "])"
    "|(?:" + _Q_CJK + "|" + _Q_THAI + ")"
    # Греческий вопросительный знак — `;` (U+037E при нормализации становится
    # им же); армянский `՞` стоит над словом, эфиопский — `፧`.
    "|[\u0370-\u03ff\u1f00-\u1fff]\\s?[;\u037e]\\s*$|\u055e|\u1367"
    "|[?？؟]\\s*$", re.I | re.U)

# Кто ходит за содержимым для ИИ-ответов и что теряется при блокировке.
AI_AGENTS = {
    "oai-searchbot": N_("ChatGPT не покажет страницу в ответах своего поиска"),
    "gptbot": N_("OpenAI не будет использовать страницу для обучения (на показ в поиске это не влияет)"),
    "chatgpt-user": N_("ChatGPT не сможет открыть страницу по прямой просьбе пользователя"),
    "perplexitybot": N_("Perplexity не проиндексирует страницу"),
    "claudebot": N_("Anthropic не будет использовать страницу"),
    "claude-searchbot": N_("Claude не покажет страницу в ответах с поиском"),
    "google-extended": N_("Gemini не будет использовать страницу для обучения (на AI Overviews не влияет)"),
    "applebot-extended": N_("Apple Intelligence не будет использовать страницу"),
    "bingbot": N_("Bing не проиндексирует страницу — а вместе с ним Copilot"),
    "claude-user": N_("Claude не сможет открыть страницу по прямой просьбе пользователя"),
    "perplexity-user": N_("Perplexity не сможет открыть страницу по прямой просьбе пользователя"),
    "ccbot": N_("Common Crawl не возьмёт страницу в свой набор (им пользуются многие модели)"),
    "bytespider": N_("ByteDance не будет использовать страницу"),
    "amazonbot": N_("Amazon не будет использовать страницу"),
    "meta-externalagent": N_("Meta не будет использовать страницу для обучения"),
}

# Закрытие этих ботов убирает страницу из поиска или из ответов с поиском —
# это потеря трафика, а не решение про обучение. Важность записана здесь, а не
# выводится из текста сообщения: раньше она искалась по русскому слову внутри
# уже переведённой строки, и в английском выводе все четыре были «инфо».
AI_SEARCH_AGENTS = {"oai-searchbot", "perplexitybot", "claude-searchbot", "bingbot"}


def read_robots(path: str) -> dict:
    """
    Разбирает robots.txt проекта: какие агенты что запрещают.
    Пакет не читал его вовсе, хотя `Disallow` — классическая причина
    «страниц нет в индексе», которую ищут неделями.
    """
    from .core import read_text, SourceError

    if not path:
        return {"found": False, "rules": {}, "sitemaps": []}
    if os.path.isdir(path):
        return {"found": False, "error": tr("{a0} — это каталог, а нужен файл", a0=path),
                "rules": {}, "sitemaps": []}
    if not os.path.exists(path):
        return {"found": False, "error": tr("файла {a0} нет", a0=path),
                "rules": {}, "sitemaps": []}
    try:
        text, _ = read_text(path)
    except SourceError as exc:
        return {"found": False, "error": str(exc), "rules": {}, "sitemaps": []}

    rules, sitemaps = {}, []
    current = []
    previous_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            previous_was_agent = False
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if not previous_was_agent:
                current = []
            # `Googlebot/2.1` — тот же Googlebot: важно имя, а не версия.
            current.append((value.lower().split("/")[0].split() or [""])[0])
            previous_was_agent = True
            for agent in current:
                rules.setdefault(agent, {"disallow": [], "allow": []})
        elif field in ("disallow", "allow"):
            previous_was_agent = False
            for agent in current or ["*"]:
                rules.setdefault(agent, {"disallow": [], "allow": []})
                rules[agent][field].append(value)
        elif field == "sitemap":
            previous_was_agent = False
            sitemaps.append(value)
        else:
            # Crawl-delay, Host, Clean-param и любая другая директива тоже
            # закрывают перечисление агентов. Без этого `Crawl-delay` между
            # двумя `User-agent` склеивал группы, и запрет для одного бота
            # читался как «сайт закрыт целиком» — на типовом robots рунета.
            previous_was_agent = False
    return {"found": True, "rules": rules, "sitemaps": sitemaps}


# `/`, `/*` и `/$` запрещают весь сайт. Строгое сравнение с «/» пропускало
# полный запрет, записанный вторым способом.
# `/$` сюда не входит: это ровно главная страница, а не весь сайт. Раньше
# `Allow: /$` считалось разрешением всего и гасило находку о полном запрете.
_BLOCK_ALL = {"/", "/*", "/*$"}


def _blocks_everything(entry: dict) -> bool:
    disallow = {d.strip() for d in (entry.get("disallow") or [])}
    allow = {a.strip() for a in (entry.get("allow") or [])}
    return bool(disallow & _BLOCK_ALL) and not (allow & _BLOCK_ALL)


def _search_bot_closed(entry: dict) -> bool:
    """
    Бот ИИ-поиска закрыт целиком: `Disallow: /` и ни одного Allow, которое
    открыло бы хоть что-то. `Disallow: /` с `Allow: /rent/` — частичный
    запрет: по правилу самого длинного совпадения такие страницы открыты,
    и считать их надо по сборке, а не объявлять бота закрытым.
    """
    return _blocks_everything(entry) and not any(
        a.strip() for a in (entry.get("allow") or []))


# Поисковики, у которых бывает своя группа правил в robots.txt.
_SEARCH_ENGINES = ("googlebot", "bingbot", "yandex", "yandexbot", "duckduckbot",
                   "baiduspider", "slurp", "applebot")


_PCT = re.compile(r"%[0-9a-fA-F]{2}")


def _robots_norm(text: str) -> str:
    """
    Правило и адрес в одной записи: не-ASCII — в UTF-8 %XX, `%d0` — `%D0`.

    `Disallow: /каталог/` и `Disallow: /%d0%ba…` Google читает так же, как
    `/%D0%BA…`; без этого robots.txt нелатинского сайта не совпадал ни с одним
    адресом, и закрытый раздел выглядел открытым.
    """
    from urllib.parse import quote
    text = _PCT.sub(lambda m: m.group(0).upper(), text)
    if text.isascii():
        return text
    return "".join(ch if ch.isascii() else quote(ch, safe="") for ch in text)


def _robots_pattern(rule: str):
    """Правило robots.txt по правилам Google: `*` — что угодно, `$` — конец адреса."""
    rule = _robots_norm(rule)
    anchored = rule.endswith("$")
    body = rule[:-1] if anchored else rule
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile(regex + ("$" if anchored else ""))


def _robots_group(robots: dict, agent: str = "googlebot") -> dict:
    """Своя группа агента сильнее общей `*`: Google читает только одну."""
    rules = robots.get("rules") or {}
    return rules.get(agent) or rules.get("*") or {}


def robots_allows(robots: dict, path: str, agent: str = "googlebot") -> bool:
    """Пускает ли robots.txt агента по адресу."""
    return not blocking_rule(robots, path, agent)


def blocking_rule(robots: dict, path: str, agent: str = "googlebot") -> str:
    """
    Правило Disallow, которое закрывает адрес, или пустая строка. Самое
    длинное совпавшее правило побеждает; при равной длине — Allow. Пустой
    `Disallow:` не запрещает ничего.
    """
    group = _robots_group(robots, agent)
    path = _robots_norm(path)
    best, verdict = -1, True
    for field, allowed in (("disallow", False), ("allow", True)):
        for rule in group.get(field) or ():
            rule = rule.strip()
            if not rule:
                continue
            if _robots_pattern(rule).match(path):
                length = len(rule)
                if length > best or (length == best and allowed):
                    best, verdict = length, ("" if allowed else rule)
    return "" if verdict is True else verdict


def blocked_urls(pages: list, robots: dict) -> set:
    """
    Страницы, которые robots.txt не пускает обходить: их ссылок поисковик не
    читает. Полный запрет сайта — отдельная находка, а не тысяча закрытых.
    """
    from urllib.parse import urlsplit
    if not robots.get("found") or _blocks_everything(_robots_group(robots)):
        return set()
    found = set()
    for page in pages:
        parts = urlsplit(page.url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if blocking_rule(robots, path):
            found.add(page.url)
    return found


def check_blocked_pages(pages: list, robots: dict) -> list:
    """
    Страницы сборки, которые robots.txt не пускает обходить.

    `Disallow: /compare/` при шестидесяти таких страницах в sitemap пакет
    пропускал: правила он разбирал, но смотрел только на `Disallow: /`.
    Страница, закрытая обходом, в индекс не попадёт с текстом — поисковик его
    не прочитает, а noindex на ней не увидит. Закрытую noindex страницу и
    полный запрет сайта (о нём отдельная находка) здесь не повторяем.
    """
    from urllib.parse import urlsplit
    from .publish import indexable
    if not robots.get("found"):
        return []
    issues = _search_agents_partly_blocked(pages, robots)
    if _blocks_everything(_robots_group(robots)):
        return issues
    for page in sorted(pages, key=lambda p: p.url):
        if not indexable(page):
            continue
        parts = urlsplit(page.url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        verdict = blocking_rule(robots, path)
        if verdict:
            issues.append(("critical", page.url, "robots-blocks-page",
                           tr("robots.txt не пускает поисковик на страницу (правило "
                              "«Disallow: {a0}») — текст он не прочитает, ссылки и sitemap "
                              "ведут сюда зря", a0=verdict)))
    return issues


def _search_agents_partly_blocked(pages: list, robots: dict) -> list:
    """
    Своя группа ИИ-поиска или Bingbot с частичным запретом (`Disallow: /rent/`).

    Полный запрет такого бота — находка `check_robots`; частичный не замечался
    вовсе, хотя раздел каталога так же пропадает из ответов ChatGPT или Bing.
    Считаются открытые страницы сборки, которые Googlebot обходит, а этот бот
    — нет. Одна находка на бота: правило одно, а страниц может быть тысячи.
    Закрыта половина открытых страниц и больше — критично, меньше —
    предупреждение: служебный раздел часто закрывают намеренно.
    """
    from urllib.parse import urlsplit
    from .publish import indexable
    rules = robots.get("rules") or {}
    open_pages = [p for p in pages if indexable(p)]
    issues = []
    for agent in sorted(AI_SEARCH_AGENTS):
        entry = rules.get(agent)
        if not entry or _search_bot_closed(entry):
            continue
        blocked = Counter()
        for page in open_pages:
            parts = urlsplit(page.url)
            path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            rule = blocking_rule(robots, path, agent)
            if rule and not blocking_rule(robots, path):
                blocked[rule] += 1
        n = sum(blocked.values())
        if not n:
            continue
        rule = blocked.most_common(1)[0][0]
        level = "critical" if 2 * n >= len(open_pages) else "warning"
        issues.append((level, "robots.txt", "ai-crawler-blocked",
                       tr("{a0} не пускают на {a1} из {a2} открытых страниц (правило "
                          "«Disallow: {a3}»): {a4}", a0=agent, a1=n, a2=len(open_pages),
                          a3=rule, a4=tr(AI_AGENTS[agent]))))
    return issues


def check_robots(robots: dict) -> list:
    """Находки по robots.txt: кого закрыли и что из-за этого теряется."""
    issues = []
    if not robots.get("found"):
        if robots.get("error"):
            issues.append(("warning", "robots.txt", "robots-unreadable",
                           tr("robots.txt не прочитан: {a0}", a0=robots['error'])))
        else:
            issues.append(("info", "robots.txt", "no-robots",
                           tr("robots.txt не найден — это не ошибка, но и не контроль: передай путь через --robots, чтобы проверить")))
        return issues

    rules = robots.get("rules") or {}
    star = rules.get("*") or {}
    if _blocks_everything(star):
        # Своя группа сильнее общей: `Googlebot` с `Allow: /` сайт видит, что
        # бы ни стояло под звёздочкой.
        allowed = sorted(a for a in _SEARCH_ENGINES
                         if a in rules and not _blocks_everything(rules[a]))
        if allowed:
            issues.append(("warning", "robots.txt", "robots-blocks-all",
                           tr("Disallow: / для всех агентов, кроме {a0} — остальные поисковики "
                              "и ИИ-поиск сайт не видят", a0=", ".join(allowed))))
        else:
            issues.append(("critical", "robots.txt", "robots-blocks-all",
                           tr("Disallow: / для всех агентов — сайт закрыт от всех поисковиков целиком")))
    elif "googlebot" in rules and _blocks_everything(rules["googlebot"]):
        # Своя группа Googlebot с `Disallow: /` закрывает сайт от Google, даже
        # если под звёздочкой всё открыто. Раньше об этом молчали все три
        # проверки: постраничные оставляли полный запрет этой, а эта смотрела
        # только на `*`.
        issues.append(("critical", "robots.txt", "robots-blocks-all",
                       tr("Disallow: / для Googlebot — Google не обходит сайт целиком")))
    for agent, why in sorted(AI_AGENTS.items()):
        entry = rules.get(agent)
        search = agent in AI_SEARCH_AGENTS
        if entry and (_search_bot_closed(entry) if search else _blocks_everything(entry)):
            level = "critical" if search else "info"
            issues.append((level, "robots.txt", "ai-crawler-blocked",
                           tr("{a0} закрыт: {a1}", a0=agent, a1=tr(why))))
    if not robots.get("sitemaps"):
        issues.append(("info", "robots.txt", "robots-no-sitemap",
                       tr("в robots.txt не указан Sitemap — строка `Sitemap: https://…/sitemap.xml` стоит копейки")))
    return issues


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?。！？])\s+", (text or "").strip(), maxsplit=1)
    return parts[0] if parts else ""


# После слова должна идти дата, имя или «by/on»: «By law, a deposit…»,
# «Written permission is required…» и «Updated: in this article we will…» —
# обычные первые фразы, а не подпись. Раньше их выбрасывали как дату, и
# оценивался второй абзац.
_UPPER = "A-ZÀ-ÖØ-ÞА-ЯЁ"
_DATELINE = re.compile(
    r"^\s*(?:(?i:(?:last\s+)?(?:updated|published|posted|modified|reviewed|written|"
    r"обновлено|опубликовано|дата|автор|aktualisiert|veröffentlicht|mis à jour|publié|"
    r"actualizado|publicado))(?:\s*:)?\s+(?:(?i:by|on|am|le|el|em|от)\b|\d|[" + _UPPER + r"])"
    r"|(?i:by)\s+[" + _UPPER + r"])")
_DATE_ONLY = re.compile(
    r"^[\s\d.,/:\-–—·|]*(?:[A-Za-zА-Яа-яЁё]+[\s\d.,/:\-–—·|]*){0,4}$")


def _is_dateline(text: str) -> bool:
    """Строка даты или подписи над статьёй: короткая и про время, а не про суть."""
    text = text.strip()
    if len(text) > 100:
        return False
    if _DATELINE.match(text):
        return True
    return bool(re.search(r"\d{4}", text)) and bool(_DATE_ONLY.match(text)) and len(text) < 40


def check_answer(page, cfg: dict = None) -> list:
    """
    Прямой ответ в первом абзаце.

    Semrush на 304 805 цитируемых URL: ясность и суммаризация — сильнейший
    контентный фактор цитируемости (+32,8%). Практически это значит,
    что первый абзац должен отвечать на запрос, а не разгоняться.
    """
    cfg = {**CONFIG, **(cfg or {})}
    # Строка «Updated September 2026» или «Published 12 March · 5 min read»
    # перед первым абзацем — не ответ: на 98% страниц каталога первым
    # абзацем бралась она, и `answer-short` закрывал собой `answer-preamble`.
    paragraphs = [p for p in (page.paragraphs or []) if len(p) > 20 and not _is_dateline(p)]
    if not paragraphs:
        return [("warning", page.url, "no-answer",
                 tr("не нашёл ни одного абзаца — цитировать нечего"))]
    first = paragraphs[0]
    issues = []
    # Типографский апостроф — тот же апостроф: «Let’s dive» не узнавалось.
    lowered = first.lower().lstrip("«\"'— -").replace("’", "'").replace("‘", "'")
    if _is_preamble(lowered):
        issues.append(("warning", page.url, "answer-preamble",
                       tr("первый абзац начинается с разгона «{a0}…» — ИИ-поиск цитирует ответ, а не вступление", a0=first[:40])))
    elif len(first) < cfg["answer_min"]:
        issues.append(("info", page.url, "answer-short",
                       tr("первый абзац короче {a0} символов — на самостоятельный ответ не тянет", a0=cfg['answer_min'])))
    elif len(first) > cfg["answer_max"]:
        issues.append(("info", page.url, "answer-long",
                       tr("первый абзац {a0} символов — для цитирования лучше уложить ответ в {a1}", a0=len(first), a1=cfg['answer_max'])))
    return issues


# «Who we are», «What we offer», «Как мы работаем» без «?» — подпись раздела,
# а не вопрос: за вопросительным словом сразу стоит подлежащее-местоимение.
_DECLARATIVE = re.compile(
    r"^(?:how|what|where|who|why|when|which|как|что|где|кто|почему|зачем|"
    r"wie|was|wo|wer|warum)\s+(?:we|you|i|they|it|our|your|us|мы|вы|нас|вас|wir|sie|ihr)\b",
    re.I | re.U)


def _is_question(heading: str) -> bool:
    text = heading.strip()
    if not QUESTION.search(text):
        return False
    return bool(re.search(r"[?？؟]\s*$", text)) or not _DECLARATIVE.match(text)


def check_extractable(page, cfg: dict = None) -> list:
    """
    Извлекаемость: вопросные подзаголовки, списки и таблицы, длина абзаца.
    Q&A-формат +25,5%, структура секций +22,9%, элементы структуры +21,6%
    (тот же корпус Semrush).
    """
    cfg = {**CONFIG, **(cfg or {})}
    issues = []
    # Заголовки врезок, подвала и меню — шаблон, а не разделы статьи.
    outline = page.outline if getattr(page, "outline", None) is not None else page.headings
    subheads = [t for lvl, t in outline if lvl >= 2]
    if len(subheads) >= 3:
        questions = sum(1 for t in subheads if _is_question(t))
        # Считаем долю, а не «хотя бы один»: одно ложное срабатывание
        # регулярки гасило проверку целиком.
        if questions / len(subheads) < cfg["question_share"]:
            issues.append(("info", page.url, "no-question-headings",
                           tr("вопросов среди подзаголовков {a0} из {a1} — формат «вопрос → ответ» цитируется заметно чаще", a0=questions, a1=len(subheads))))
    long_paragraphs = [p for p in (page.paragraphs or []) if len(p) > cfg["long_paragraph"]]
    if long_paragraphs:
        issues.append(("info", page.url, "long-paragraph",
                       tr("{a0} абзац(ев) длиннее {a1} символов — такой блок трудно процитировать целиком", a0=len(long_paragraphs), a1=cfg['long_paragraph'])))
    blocks = page.blocks or {}
    if page.word_count > 400 and not blocks.get("li") and not blocks.get("table"):
        issues.append(("info", page.url, "no-structure",
                       tr("в тексте нет ни списков, ни таблиц — структурные элементы повышают шанс попасть в ответ")))
    if blocks.get("img") and blocks.get("img_no_alt"):
        issues.append(("info", page.url, "img-no-alt",
                       tr("{a0} изображени(й) без alt", a0=blocks['img_no_alt'])))
    elif (blocks.get("img_empty_alt", 0) >= 3 and blocks["img_empty_alt"] == blocks.get("img")):
        # alt="" верен для украшений. Когда так помечены все картинки страницы,
        # это почти всегда шаблон, а не решение: товарное фото не декор.
        issues.append(("info", page.url, "img-no-alt", tr(
            "все {a0} изображени(й) с пустым alt=\"\" — так помечают украшения; "
            "если среди них есть фото по теме страницы, им нужен alt",
            a0=blocks["img_empty_alt"])))
    issues += check_alt_text(page)
    return issues


# Alt, который ничего не говорит: заглушка шаблона на любом языке. Сверяется
# всё значение целиком, а не вхождение: «фото квартиры в Москве» — хороший alt.
ALT_FILLERS = {
    "image", "img", "picture", "photo", "pic", "photograph", "icon", "logo", "banner",
    "thumbnail", "placeholder", "untitled", "alt", "alt text", "image description",
    "изображение", "картинка", "фото", "фотография", "иконка", "логотип", "баннер",
    "рисунок", "зображення", "картинка", "світлина",
    "bild", "foto", "abbildung", "imagen", "imagem", "immagine", "obrázek", "zdjęcie",
    "obraz", "kép", "resim", "görsel", "afbeelding", "billede", "bilde", "kuva",
    "صورة", "الصورة", "صوره", "تصویر", "عکس", "תמונה", "छवि", "तस्वीर", "फोटो",
    "รูปภาพ", "รูป", "ภาพ", "hình ảnh", "ảnh", "gambar", "foto produk",
    "图片", "图像", "照片", "圖片", "画像", "写真", "イメージ", "이미지", "사진",
    "εικόνα", "φωτογραφία",
}
# Имя файла вместо описания: `IMG_2034`, `DSC00123`, `PXL_20240101_1234`,
# `photo-1.webp`, хеш загрузчика. Не «iPhone 15 Pro 256GB»: число в alt —
# не признак файла.
_ALT_FILE = re.compile(
    r"^(?:img|image|dsc|dscn|dscf|dcim|pxl|photo|screenshot|wp|gopr|mvimg)[\s_\-]*\d{2,}[\w\-]*$|"
    r"^[^\s]+\.(?:jpe?g|png|gif|webp|avif|svg|bmp|tiff?|heic)$|"
    r"^[a-f0-9][a-f0-9\-_]{15,}$", re.I)


def _alt_is_filler(alt: str) -> bool:
    text = re.sub(r"[\s\u3000]+", " ", alt.strip().strip(".:-—_").lower())
    if not text:
        return False
    if text in ALT_FILLERS:
        return True
    # «image 3», «фото 12», «画像1» — заглушка с номером.
    bare = re.sub(r"[\s#№\-_]*\d+$", "", text)
    if bare != text and bare in ALT_FILLERS:
        return True
    return bool(_ALT_FILE.match(text))


def check_alt_text(page) -> list:
    """
    Alt, который есть, но не работает: заглушка или имя файла — и alt не тем
    письмом, каким написана страница (английский alt на русской или арабской
    версии — шаблон, который забыли перевести).
    """
    from .signals import declared_scripts, text_script, SCRIPTS

    alts = [a for a, _ in (getattr(page, "alts", None) or [])]
    if not alts:
        return []
    issues = []
    fillers = [a for a in alts if _alt_is_filler(a)]
    if fillers:
        shown = ", ".join(f"«{a[:30]}»" for a in sorted(set(fillers))[:4])
        issues.append(("info", page.url, "img-alt-filler", tr(
            "у {a0} из {a1} изображений alt ничего не говорит: {a2} — это заглушка "
            "или имя файла, а не описание", a0=len(fillers), a1=len(alts), a2=shown)))
    expected = declared_scripts(page.lang)
    meaningful = [a for a in alts if a not in fillers]
    if expected and meaningful:
        script, share, letters = text_script(" ".join(meaningful), expected)
        from . import langid
        same_script_other = (script in expected and letters >= 20
                             and langid.identify(" ".join(meaningful), min_tokens=12)[0]
                             not in ("", langid.primary(page.lang))
                             and langid.primary(page.lang) in langid.WORDS)
        if same_script_other or (letters >= 20 and share >= 0.8 and script not in expected):
            issues.append(("info", page.url, "img-alt-language", tr(
                "страница на lang=«{a0}», а alt изображений написан другим письмом "
                "({a1}): похоже, шаблон alt не переведён", a0=page.lang.strip(),
                a1=tr(SCRIPTS[script][0]))))
    return issues


def check_shell(page, cfg: dict = None) -> list:
    """
    Пустой JS-каркас. GPTBot, OAI-SearchBot, ClaudeBot и PerplexityBot
    не исполняют JavaScript: страница, которую рисует скрипт, для них пустая.
    Googlebot исполняет — поэтому проблема видна не сразу.

    Саму находку теперь выдаёт `checks.run_all`: она нужна и без `--no-aeo`,
    и от неё зависит, какие проверки на странице вообще имеют смысл.
    Здесь остался только вердикт, чтобы `aeo` не оценивал пустую страницу
    по прямому ответу и извлекаемости — это было бы шумом поверх шума.
    """
    cfg = {**CONFIG, **(cfg or {})}
    if is_shell(page, cfg):
        return [("critical", page.url, "js-shell",
                 # тот же текст, что у checks.run_all: находка одна, и сайт
                 # документации не должен зависеть от порядка файлов
                 tr("в исходном HTML нет текста — его рисует JavaScript, а краулеры ИИ-поиска его не исполняют"))]
    return []


def _no_constant(name):
    raise ValueError(tr("{a0} — не число JSON", a0=name))


def _load_ld(raw: str):
    """
    JSON-LD строго по RFC 8259. Python принимает `NaN` и `Infinity`, а
    строгий парсер поисковика выбрасывает такой блок целиком.
    """
    return json.loads(raw, parse_constant=_no_constant)


def _faq_pages(data, depth=0):
    """
    FAQPage в любом месте разметки: и вложенная в `WebPage.mainEntity` или
    `hasPart`. Раньше смотрелся только верхний уровень и `@graph`.
    """
    if depth > 8:
        return
    if isinstance(data, list):
        for value in data:
            yield from _faq_pages(value, depth + 1)
    elif isinstance(data, dict):
        if "faqpage" in _ld_types(data):
            yield data
        for value in data.values():
            if isinstance(value, (dict, list)):
                yield from _faq_pages(value, depth + 1)


_TAG = re.compile(r"<[^<>]+>")


def _question_key(question: str) -> str:
    """Вопрос для поиска в тексте: без тегов и финального знака вопроса."""
    text = _plain(_TAG.sub(" ", question))
    return " ".join(text.split()).rstrip(" ?？؟.!:")


def check_jsonld(page) -> list:
    """
    Разметка проверяется на валидность и на соответствие тексту, а не на наличие.

    Ahrefs отследил 1 885 страниц, добавивших JSON-LD: цитирования
    не выросли. Поэтому «нет разметки» — не находка. А вот битый JSON
    или FAQ, которого нет на странице, — находка: это риск санкций
    без единого плюса.
    """
    issues = []
    for raw in page.jsonld or ():
        try:
            data = _load_ld(raw)
        except (ValueError, RecursionError) as exc:
            issues.append(("warning", page.url, "jsonld-broken",
                           tr("блок JSON-LD не парсится ({a0}) — для поисковика его просто нет",
                              a0=getattr(exc, "msg", None)
                              or (str(exc) if isinstance(exc, ValueError) else "")
                              or tr("слишком глубокая вложенность"))))
            continue
        mismatch = _ld_numbers_missing(data, page)
        if mismatch:
            issues.append(("warning", page.url, "jsonld-mismatch", tr(
                "в JSON-LD {a0}, а на странице таких чисел нет — разметка должна повторять "
                "видимое, иначе это риск ручных санкций", a0=", ".join(mismatch[:3]))))
        for item in _ld_items(data):
            # Контейнер `@graph` сам по себе типа не имеет — это обёртка,
            # а не сущность. Раньше каждая страница с разметкой Yoast
            # получала за неё ложную находку. Но `@context` без `@type`
            # рядом с данными — как раз забытый тип, а не обёртка.
            if "@type" not in item and "@graph" not in item \
                    and not set(item) <= {"@context", "@id"}:
                issues.append(("info", page.url, "jsonld-no-type",
                               tr("в блоке JSON-LD нет @type")))
        for item in _faq_pages(data):
            # Вопрос ищется во всём видимом тексте и после приведения обеих
            # сторон к одному виду: вёрстка ставит «’» вместо «'», тире
            # вместо дефиса, а в разметке лежит `&amp;`. Каждое такое
            # расхождение давало находку с угрозой ручных санкций.
            # Сверяется весь вопрос, а не первые 40 символов: в программном
            # FAQ отличается как раз хвост — город или товар.
            haystack = _plain((page.text or "") + " " + (getattr(page, "chrome", "") or ""))
            missing = []
            entities = item.get("mainEntity") or []
            if isinstance(entities, dict):
                entities = [entities]
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                question = str(entity.get("name") or "").strip()
                key = _question_key(question)
                if key and key not in haystack:
                    missing.append(question)
            if missing:
                issues.append(("warning", page.url, "jsonld-faq-invisible",
                               tr("{a0} вопрос(ов) из FAQPage нет в видимом тексте — разметка, не совпадающая со страницей, это риск ручных санкций", a0=len(missing))))
    return issues


# Числа разметки, которые читатель обязан видеть: цена предложения, рейтинг и
# число отзывов. Google требует, чтобы разметка повторяла страницу; сгенерированная
# разметка расходится с текстом, когда шаблон берёт поле из одной колонки
# датасета, а текст — из другой.
_LD_NUMBERS = {"price": "price", "lowprice": "lowPrice", "highprice": "highPrice",
               "ratingvalue": "ratingValue", "reviewcount": "reviewCount",
               "ratingcount": "ratingCount"}


def _ld_numbers(node, depth=0, inside_rating=False):
    """(поле, число) из разметки, вглубь, но только предложения и общий рейтинг."""
    if depth > 8:
        return
    if isinstance(node, list):
        for value in node:
            yield from _ld_numbers(value, depth + 1, inside_rating)
        return
    if not isinstance(node, dict):
        return
    types = {str(t).lower() for t in (node.get("@type") if isinstance(node.get("@type"), list)
                                      else [node.get("@type")]) if t}
    for key, value in node.items():
        low = str(key).lower()
        if low in ("review", "reviews"):
            continue                       # оценки отдельных отзывов на странице не обязаны быть
        if low in _LD_NUMBERS and not isinstance(value, (dict, list)):
            rating_field = low in ("ratingvalue", "reviewcount", "ratingcount")
            if rating_field and not (inside_rating or "aggregaterating" in types):
                continue
            yield _LD_NUMBERS[low], value
        elif isinstance(value, (dict, list)):
            yield from _ld_numbers(value, depth + 1,
                                   inside_rating or low == "aggregaterating")


_LOOSE_GROUPS = re.compile(r"\d(?:[\d,'’\u00a0\u202f ]*\d)?")
_THOUSANDS = re.compile(r"(\d+(?:[.,]\d+)?)\s?(?:k|K|тыс\.?|к)(?![\w])")


def _visible_numbers(text: str) -> tuple:
    """
    Числа видимого текста в трёх видах: значения, цифры без разделителей и
    «тысячи». Цифры без разделителей ловят то, что значения не ловят:
    `$16<sup>99</sup>` (склеено в 1699), индийское `1,60,000`, швейцарское
    `1'600.00`. «1.2K reviews» и «$1.6k» — округлённые тысячи.
    """
    from .content import NUMBER, _norm_number
    values, digits, thousands = set(), set(), []
    for raw in re.findall(r"(?<![\d.,])(" + NUMBER + r")", text):
        try:
            values.add(round(float(_norm_number(raw)), 4))
        except (ValueError, OverflowError):
            pass
    for raw in _LOOSE_GROUPS.findall(text):
        digits.add(re.sub(r"\D", "", raw).lstrip("0") or "0")
    for m in _THOUSANDS.finditer(text):
        try:
            thousands.append(float(m.group(1).replace(",", ".")) * 1000)
        except ValueError:
            pass
    return values, digits, thousands


def _shown(number: float, values: set, digits: set, thousands: list, text: str = "") -> bool:
    if number in values:
        return True
    whole = int(number)
    cents = int(round((number - whole) * 100))
    if cents:
        # $16<sup>99</sup> — «16 99»; <span>16</span><span>.99</span> — «16 .99».
        # Целая часть и центы должны стоять рядом: раньше «19» из даты и «99»
        # из другой цены в любом месте страницы засчитывались за 19.99.
        if re.search(r"(?<![\d.,])%d\s?[.,]?\s?%02d(?!\d)" % (whole, cents), text):
            return True
    elif str(whole) in digits:
        return True
    elif re.search(r"(?<![\d.,])%d\s?[.,]?\s?00(?!\d)" % whole, text):
        # $16<sup>00</sup> — «$1600» в тексте. Не «$1,600»: цена 16 при видимых
        # 1,600 — ошибка в сто раз, а не другое написание.
        return True
    return any(abs(t - number) <= number * 0.1 for t in thousands if number >= 1000)


def _ld_value(value):
    """Число из поля разметки: `1600`, `"1,600.00"`, а и `"$1,600"`, `"1600 USD"`."""
    from .content import NUMBER, _norm_number
    if isinstance(value, float) and not math.isfinite(value):
        return None
    text = str(value).strip()
    try:
        number = float(_norm_number(text.replace(" ", "")))
    except OverflowError:
        # `"inf"`, `"Infinity"`, `"1e400"`: числа нет — сравнивать нечего.
        # Раньше одно такое поле роняло проверку всего сайта.
        return None
    except ValueError:
        found = re.search(NUMBER, text)
        if not found:
            return None
        try:
            number = float(_norm_number(found.group(0)))
        except (ValueError, OverflowError):
            return None
    return round(number, 4) if math.isfinite(number) else None


def _ld_numbers_missing(data, page) -> list:
    text = (page.text or "") + " " + (getattr(page, "chrome", "") or "")
    values, digits, thousands = _visible_numbers(text)
    out = []
    for field, value in _ld_numbers(data):
        number = _ld_value(value)
        if number is None or number <= 0 or _shown(number, values, digits, thousands, text):
            continue
        shown = f"{field} {value}"
        if shown not in out:
            out.append(shown)
    return out


_TYPOGRAPHY = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "«": '"', "»": '"',
                             "–": "-", "—": "-", "‑": "-", "…": "...", "\u00a0": " "})


def _plain(text: str) -> str:
    """Текст для сравнения: без сущностей, типографики и лишних пробелов."""
    import html
    import unicodedata
    text = unicodedata.normalize("NFKC", html.unescape(html.unescape(text or "")))
    return " ".join(text.translate(_TYPOGRAPHY).split()).lower()


def _ld_items(data) -> list:
    """
    Разворачивает разметку в плоский список объектов.

    Форму `@graph` отдают Yoast и RankMath, то есть половина сайтов. Раньше
    она не разворачивалась, и один и тот же блок давал сразу три ложные
    находки: «нет @type», «нет даты», «нет автора» — плюс не находился
    FAQ, которого нет на странице.
    """
    out = []
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            out.append(node)
            graph = node.get("@graph")
            if isinstance(graph, (list, dict)):
                stack.append(graph)
    return out


def _ld_types(item: dict) -> set:
    value = item.get("@type")
    values = value if isinstance(value, list) else [value]
    return {str(v).lower() for v in values if v}


DATE_KEYS = ("datepublished", "datemodified", "date", "updated", "published")


# В значении даты есть год: `<time datetime="09:00">` в часах работы — не дата.
_HAS_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
# Микроданные и RDFa на обычных элементах: `<span itemprop="author">`,
# `<span property="datePublished" content="…">`. Читаются Google так же, как
# JSON-LD, а извлекатель берёт itemprop только с <meta>.
_INLINE_AUTHOR = re.compile(
    r"<[a-z][^<>]*\b(?:itemprop|property)\s*=\s*[\"']?(?:[^\"'<>]*\s)?(?:schema:)?"
    r"(?:author|creator|publisher)(?![\w:-])", re.I)
_INLINE_DATE = re.compile(
    r"<[a-z][^<>]*\b(?:itemprop|property)\s*=\s*[\"']?(?:[^\"'<>]*\s)?(?:schema:)?"
    r"(?:datePublished|dateModified|dateCreated)(?![\w:-])", re.I)


def _filled(value) -> bool:
    """Поле заполнено: `"author": ""` и `"datePublished": null` — не автор и не дата."""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return any(_filled(v) for v in value)
    if isinstance(value, dict):
        return any(_filled(v) for k, v in value.items() if not str(k).startswith("@"))
    return value is not None and value is not False


def check_provenance(page) -> list:
    """Даты и автор в машиночитаемом виде — сигналы, которые ИИ-поиск читает."""
    issues = []
    meta = {str(k).lower(): v for k, v in (page.meta or {}).items()}
    has_date = any(_HAS_YEAR.search(str(meta.get(k) or "")) for k in DATE_KEYS)
    has_author = _filled(meta.get("author"))
    for raw in page.jsonld or ():
        try:
            data = _load_ld(raw)
        except (ValueError, RecursionError):
            continue
        for item in _ld_items(data):
            values = {str(k).lower(): v for k, v in item.items()}
            has_date = has_date or any(_filled(values.get(k)) for k in DATE_KEYS)
            # Издатель — тоже «кто за этим стоит»; находка так и называется:
            # «автор или организация».
            has_author = has_author or any(_filled(values.get(k))
                                           for k in ("author", "publisher", "creator"))
    if not has_date or not has_author:
        # Закомментированная разметка не разметка.
        raw = _COMMENT.sub(" ", page.raw or "")
        if not has_date:
            has_date = any(_HAS_YEAR.search(m) for m in re.findall(
                r"<time\b[^<>]{0,500}?datetime\s*=\s*[\"']?([^\"'<>]*)", raw, re.I))
            has_date = has_date or bool(_INLINE_DATE.search(raw))
        if not has_author:
            has_author = bool(_INLINE_AUTHOR.search(raw))
    if not has_date:
        issues.append(("info", page.url, "no-date",
                       tr("нет машиночитаемой даты публикации или обновления")))
    if not has_author:
        issues.append(("info", page.url, "no-author",
                       tr("не указан автор или организация — сигнал E-E-A-T")))
    return issues


def run(pages: list, robots_path: str = "", cfg: dict = None) -> dict:
    """Все проверки машинной читаемости разом."""
    cfg = {**CONFIG, **(cfg or {})}
    robots = read_robots(robots_path)
    issues = check_robots(robots) + check_blocked_pages(pages, robots)
    for page in sorted(pages, key=lambda p: p.url):
        # Пустую оболочку `checks` уже назвал по имени. Оценивать её прямой
        # ответ и извлекаемость бессмысленно: оценивать нечего.
        if is_shell(page, cfg):
            continue
        issues += check_answer(page, cfg)
        issues += check_extractable(page, cfg)
        issues += check_jsonld(page)
        issues += check_provenance(page)
    return {
        "issues": issues,
        "robots": robots,
        "note": tr("Проверено то, что не мешает машине взять ответ со страницы. Попадание в ответы ИИ-поиска определяется в основном вне сайта: упоминания и позиция в обычной выдаче. Пакет на это не влияет."),
    }
