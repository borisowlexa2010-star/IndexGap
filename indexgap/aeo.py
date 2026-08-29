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
import os
import re

from .checks import is_shell
from .i18n import tr

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
    "ни для кого не секрет", "в современном мире", "прежде чем",
    "in this article", "in this post", "we will explore", "let's dive",
    "let us explore", "as we all know", "in today's world",
)

QUESTION = re.compile(
    "^(как|что|где|когда|почему|зачем|сколько|какой|какая|какие|какое|кто|можно ли|нужно ли|how|what|where|when|why|who|which|can|do|does|is|are)\\b|[?？]\\s*$", re.I | re.U)

# Кто ходит за содержимым для ИИ-ответов и что теряется при блокировке.
AI_AGENTS = {
    "oai-searchbot": tr("ChatGPT не покажет страницу в ответах своего поиска"),
    "gptbot": tr("OpenAI не будет использовать страницу для обучения (на показ в поиске это не влияет)"),
    "chatgpt-user": tr("ChatGPT не сможет открыть страницу по прямой просьбе пользователя"),
    "perplexitybot": tr("Perplexity не проиндексирует страницу"),
    "claudebot": tr("Anthropic не будет использовать страницу"),
    "claude-searchbot": tr("Claude не покажет страницу в ответах с поиском"),
    "google-extended": tr("Gemini не будет использовать страницу для обучения (на AI Overviews не влияет)"),
    "applebot-extended": tr("Apple Intelligence не будет использовать страницу"),
    "bingbot": tr("Bing не проиндексирует страницу — а вместе с ним Copilot"),
}


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
            current.append(value.lower())
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
_BLOCK_ALL = {"/", "/*", "/$", "/*$"}


def _blocks_everything(entry: dict) -> bool:
    disallow = {d.strip() for d in (entry.get("disallow") or [])}
    allow = {a.strip() for a in (entry.get("allow") or [])}
    return bool(disallow & _BLOCK_ALL) and not (allow & _BLOCK_ALL)


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
        issues.append(("critical", "robots.txt", "robots-blocks-all",
                       tr("Disallow: / для всех агентов — сайт закрыт от всех поисковиков целиком")))
    for agent, why in sorted(AI_AGENTS.items()):
        entry = rules.get(agent)
        if entry and _blocks_everything(entry):
            level = "critical" if tr("не покажет") in why or tr("не проиндексирует") in why else "info"
            issues.append((level, "robots.txt", "ai-crawler-blocked",
                           tr("{a0} закрыт: {a1}", a0=agent, a1=why)))
    if not robots.get("sitemaps"):
        issues.append(("info", "robots.txt", "robots-no-sitemap",
                       tr("в robots.txt не указан Sitemap — строка `Sitemap: https://…/sitemap.xml` стоит копейки")))
    return issues


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?。！？])\s+", (text or "").strip(), maxsplit=1)
    return parts[0] if parts else ""


def check_answer(page, cfg: dict = None) -> list:
    """
    Прямой ответ в первом абзаце.

    Semrush на 304 805 цитируемых URL: ясность и суммаризация — сильнейший
    контентный фактор цитируемости (+32,8%). Практически это значит,
    что первый абзац должен отвечать на запрос, а не разгоняться.
    """
    cfg = {**CONFIG, **(cfg or {})}
    paragraphs = [p for p in (page.paragraphs or []) if len(p) > 20]
    if not paragraphs:
        return [("warning", page.url, "no-answer",
                 tr("не нашёл ни одного абзаца — цитировать нечего"))]
    first = paragraphs[0]
    issues = []
    lowered = first.lower().lstrip("«\"'— -")
    if lowered.startswith(PREAMBLE):
        issues.append(("warning", page.url, "answer-preamble",
                       tr("первый абзац начинается с разгона «{a0}…» — ИИ-поиск цитирует ответ, а не вступление", a0=first[:40])))
    elif len(first) < cfg["answer_min"]:
        issues.append(("info", page.url, "answer-short",
                       tr("первый абзац короче {a0} символов — на самостоятельный ответ не тянет", a0=cfg['answer_min'])))
    elif len(first) > cfg["answer_max"]:
        issues.append(("info", page.url, "answer-long",
                       tr("первый абзац {a0} символов — для цитирования лучше уложить ответ в {a1}", a0=len(first), a1=cfg['answer_max'])))
    return issues


def check_extractable(page, cfg: dict = None) -> list:
    """
    Извлекаемость: вопросные подзаголовки, списки и таблицы, длина абзаца.
    Q&A-формат +25,5%, структура секций +22,9%, элементы структуры +21,6%
    (тот же корпус Semrush).
    """
    cfg = {**CONFIG, **(cfg or {})}
    issues = []
    subheads = [t for lvl, t in page.headings if lvl >= 2]
    if len(subheads) >= 3:
        questions = sum(1 for t in subheads if QUESTION.search(t))
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
                 tr("в исходном HTML {a0} слов при {a1} скриптах — краулеры ИИ-поиска не исполняют JavaScript и увидят пустую страницу", a0=page.word_count, a1=(page.blocks or {}).get('script', 0)))]
    return []


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
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            issues.append(("warning", page.url, "jsonld-broken",
                           tr("блок JSON-LD не парсится ({a0}) — для поисковика его просто нет", a0=exc.msg)))
            continue
        for item in _ld_items(data):
            # Контейнер `@graph` сам по себе типа не имеет — это обёртка,
            # а не сущность. Раньше каждая страница с разметкой Yoast
            # получала за неё ложную находку.
            if "@type" not in item and not {"@graph", "@context"} & set(item):
                issues.append(("info", page.url, "jsonld-no-type",
                               tr("в блоке JSON-LD нет @type")))
            if "faqpage" in _ld_types(item):
                haystack = (page.text or "").lower()
                missing = []
                entities = item.get("mainEntity") or []
                if isinstance(entities, dict):
                    entities = [entities]
                for entity in entities:
                    if not isinstance(entity, dict):
                        continue
                    question = str(entity.get("name") or "").strip()
                    if question and question.lower()[:40] not in haystack:
                        missing.append(question)
                if missing:
                    issues.append(("warning", page.url, "jsonld-faq-invisible",
                                   tr("{a0} вопрос(ов) из FAQPage нет в видимом тексте — разметка, не совпадающая со страницей, это риск ручных санкций", a0=len(missing))))
    return issues


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


def check_provenance(page) -> list:
    """Даты и автор в машиночитаемом виде — сигналы, которые ИИ-поиск читает."""
    issues = []
    meta_keys = {k.lower() for k in (page.meta or {})}
    has_date = bool(meta_keys & set(DATE_KEYS))
    has_author = "author" in meta_keys
    for raw in page.jsonld or ():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in _ld_items(data):
            keys = {str(k).lower() for k in item}
            has_date = has_date or bool(keys & set(DATE_KEYS))
            has_author = has_author or "author" in keys
    if not has_date and re.search(r"<time[^>]+datetime=", page.raw or "", re.I):
        has_date = True
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
    issues = check_robots(robots)
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
