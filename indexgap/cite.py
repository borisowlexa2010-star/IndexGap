# -*- coding: utf-8 -*-
"""
Замер цитируемости в ИИ-поиске: ChatGPT, Gemini, Perplexity, Grok.

Это единственная часть пакета, которой нужны ключи и деньги, и единственная,
которая ходит в чужие API. Поэтому она стоит отдельным модулем, выключена
по умолчанию и ничего не отправляет без явного `--send`.

**Что здесь меряется на самом деле — читать до того, как показывать цифру.**

Меряется API этих сервисов, а не их приложения. Это не придирка: документация
OpenAI прямо говорит, что в Responses API поиск включается инструментом и модель
сама решает, искать ли, тогда как в ChatGPT поиск ведёт себя иначе. У Gemini
grounding через API — не то же самое, что AI Overviews в выдаче Google.
Совпадение между API и продуктом есть, равенства нет. Поэтому в отчёте нигде
не написано «вас цитирует ChatGPT»; написано «столько-то прогонов из N через
API такого-то вернули ваш домен в источниках».

**Ответ недетерминирован.** Один и тот же вопрос дважды даёт разные источники.
Один прогон не значит ничего, поэтому каждый вопрос задаётся несколько раз,
а в отчёте стоит доля прогонов, а не «да/нет». Доля 1 из 5 и 5 из 5 — разные
вещи, и разница видна только так.

**И главное, что не изменится от этого модуля.** По данным Ahrefs на 75 000
брендов видимость в ИИ-поиске сильнее всего коррелирует с упоминаниями вне
сайта (0,66–0,74), а с количеством страниц — 0,19. 76% цитат в AI Overviews —
страницы из топ-10 обычной выдачи. Этот модуль показывает термометр; лечится
болезнь не им.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from .core import SourceError
from .i18n import N_, tr

TIMEOUT = 90

# Провайдеры. Модели вынесены в настройки: имена у всех четырёх меняются
# несколько раз в год, и зашитое имя — гарантированная поломка через квартал.
PROVIDERS = {
    "perplexity": {
        "title": "Perplexity",
        "env": ("PERPLEXITY_API_KEY",),
        "url": "https://api.perplexity.ai/chat/completions",
        "model": "sonar",
        "note": N_("Единственный из четырёх, кто по замыслу отвечает с источниками. "
                   "Ближе всех к тому, что видит человек в самом сервисе."),
    },
    "openai": {
        "title": "ChatGPT (API)",
        "env": ("OPENAI_API_KEY",),
        "url": "https://api.openai.com/v1/responses",
        "model": "gpt-5.6",
        "note": N_("Поиск включается инструментом, и модель сама решает, искать ли. "
                   "В самом ChatGPT это работает иначе — цифры близки, но не равны."),
    },
    "gemini": {
        "title": "Gemini (API)",
        "env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "url": "https://generativelanguage.googleapis.com/v1beta/interactions",
        "model": "gemini-3.7-flash",
        "note": N_("Grounding через API — не то же самое, что AI Overviews "
                   "в обычной выдаче Google. Считать одним нельзя."),
    },
    "xai": {
        "title": "Grok",
        "env": ("XAI_API_KEY",),
        "url": "https://api.x.ai/v1/responses",
        "model": "grok-4",
        "note": N_("Ищет и по вебу, и по X. Доля источников из X в ответах "
                   "заметна — это особенность сервиса, а не вашего сайта."),
    },
}


def available(env: dict = None) -> list:
    """Кого можно спросить: у кого нашёлся ключ."""
    env = os.environ if env is None else env
    out = []
    for name, meta in PROVIDERS.items():
        if any((env.get(key) or "").strip() for key in meta["env"]):
            out.append(name)
    return sorted(out)


def missing_keys(names=None) -> list:
    """Чего не хватает — списком переменных окружения, а не намёком."""
    out = []
    for name in sorted(names or PROVIDERS):
        meta = PROVIDERS.get(name)
        if meta:
            out.append(f"{meta['title']}: {' или '.join(meta['env'])}")
    return out


def _key(name: str, env: dict = None) -> str:
    env = os.environ if env is None else env
    for variable in PROVIDERS[name]["env"]:
        value = (env.get(variable) or "").strip()
        if value:
            return value
    return ""


def _post(url: str, payload: dict, headers: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        request.add_header(key, value)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _urls_anywhere(data) -> list:
    """
    Все ссылки из ответа, где бы они ни лежали.

    Формат ответов у всех четырёх разный и меняется: у кого-то
    `annotations[].url`, у кого-то `citations`, у кого-то `search_results`.
    Проще и надёжнее собрать все строки, похожие на адрес, чем каждый квартал
    чинить четыре разных пути к одному и тому же.
    """
    found = []

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and node.startswith(("http://", "https://")):
            found.append(node)

    walk(data)
    return found


def _text_anywhere(data) -> str:
    parts = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("text", "content", "output_text") and isinstance(value, str):
                    parts.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return "\n".join(parts)


def ask(name: str, prompt: str, cfg: dict = None, env: dict = None) -> dict:
    """Один вопрос одному провайдеру. Возвращает ссылки и текст ответа."""
    meta = PROVIDERS[name]
    model = (cfg or {}).get("model") or meta["model"]
    key = _key(name, env)
    if not key:
        raise SourceError(tr("нет ключа для {a0}: задай {a1}",
                             a0=meta["title"], a1=" или ".join(meta["env"])))

    if name == "perplexity":
        url, headers = meta["url"], {"Authorization": f"Bearer {key}"}
        payload = {"model": model,
                   "messages": [{"role": "user", "content": prompt}]}
    elif name == "openai":
        url, headers = meta["url"], {"Authorization": f"Bearer {key}"}
        payload = {"model": model, "input": prompt,
                   "tools": [{"type": "web_search"}]}
    elif name == "xai":
        url, headers = meta["url"], {"Authorization": f"Bearer {key}"}
        payload = {"model": model, "input": prompt,
                   "tools": [{"type": "web_search"}]}
    elif name == "gemini":
        url = meta["url"] + f"?key={key}"
        headers = {}
        payload = {"model": model, "input": prompt,
                   "tools": [{"type": "google_search"}]}
    else:
        raise SourceError(tr("неизвестный провайдер: {a0}", a0=name))

    try:
        data = _post(url, payload, headers)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:                       # noqa: BLE001
            pass
        raise SourceError(tr("{a0} ответил {a1}. {a2}\n    Чаще всего это чужое "
                             "имя модели или ключ без доступа к поиску. Имя "
                             "модели задаётся в indexgap.json, раздел `cite`.",
                             a0=meta["title"], a1=exc.code, a2=detail))
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SourceError(tr("{a0} недоступен: {a1}", a0=meta["title"], a1=exc))
    except json.JSONDecodeError:
        raise SourceError(tr("{a0} вернул не JSON", a0=meta["title"]))

    return {"urls": _urls_anywhere(data), "text": _text_anywhere(data)}


def _host(url: str) -> str:
    match = re.match(r"https?://([^/?#]+)", url or "")
    return (match.group(1).lower().lstrip("www.") if match else "").split(":")[0]


def measure(prompts: list, domain: str, brand: str = "", providers: list = None,
            runs: int = 3, cfg: dict = None, env: dict = None,
            pause: float = 0.5, on_step=None) -> dict:
    """
    Задаёт каждый вопрос `runs` раз каждому провайдеру и считает доли.

    Доля, а не «да/нет»: ответ недетерминирован, и один прогон не отличает
    «нас цитируют» от «повезло».
    """
    domain = (domain or "").lower().lstrip("www.").split("/")[0]
    if not domain:
        raise SourceError(tr("не указан домен: --domain example.com"))
    providers = providers or available(env)
    if not providers:
        raise SourceError(
            tr("ни одного ключа не найдено. Замер цитируемости — единственная "
               "часть пакета, которой нужны ключи и деньги; всё остальное "
               "работает без них.\n    Нужен хотя бы один:\n      {a0}",
               a0="\n      ".join(missing_keys())))

    brand_re = re.compile(re.escape(brand), re.I) if brand else None
    results, errors = [], []
    for prompt in prompts:
        for name in providers:
            hits, mentions, cited, competitors, failed = 0, 0, [], {}, 0
            for _ in range(max(1, runs)):
                try:
                    answer = ask(name, prompt, cfg, env)
                except SourceError as exc:
                    failed += 1
                    errors.append(f"{name}: {exc}")
                    continue
                hosts = [_host(u) for u in answer["urls"]]
                own = [u for u, h in zip(answer["urls"], hosts)
                       if h == domain or h.endswith("." + domain)]
                if own:
                    hits += 1
                    cited += own
                for other in hosts:
                    if other and other != domain and not other.endswith("." + domain):
                        competitors[other] = competitors.get(other, 0) + 1
                if brand_re and brand_re.search(answer["text"] or ""):
                    mentions += 1
                if on_step:
                    on_step(prompt, name)
                time.sleep(pause)
            done = max(1, runs) - failed
            results.append({
                "prompt": prompt,
                "provider": name,
                "runs": done,
                "failed": failed,
                "cited": hits,
                "cited_share": (hits / done) if done else 0.0,
                "brand_mentions": mentions,
                "urls": sorted(set(cited)),
                "top_competitors": sorted(competitors.items(),
                                          key=lambda kv: -kv[1])[:8],
            })
    return {"results": results, "errors": errors, "domain": domain,
            "brand": brand, "providers": providers, "runs": runs,
            "notes": notes_for(providers)}


def notes_for(providers: list) -> list:
    """Оговорки, без которых цифру нельзя показывать."""
    out = [
        tr("Замерен API, а не приложение. Совпадение с тем, что видит человек "
           "в ChatGPT или Gemini, есть, равенства нет — и в первую очередь "
           "потому, что в приложении поиск включается иначе."),
        tr("Ответ недетерминирован: тот же вопрос дважды даёт разные источники. "
           "Поэтому в таблице доля прогонов, а не «да/нет». Одного прогона "
           "не хватает ни на какой вывод."),
        tr("Цитируемость почти не зависит от того, что можно поправить в файлах "
           "проекта. По данным Ahrefs на 75 000 брендов она сильнее всего "
           "связана с упоминаниями вне сайта (0,66–0,74), а с числом страниц — "
           "0,19. Этот замер — термометр, а не лечение."),
    ]
    for name in providers or ():
        meta = PROVIDERS.get(name)
        if meta and meta.get("note"):
            out.append(f"{meta['title']} — {tr(meta['note'])}")
    return out


def read_prompts(path: str) -> list:
    """Вопросы: по одному в строке. Пустые строки и `#` пропускаются."""
    from .core import read_text

    if not os.path.exists(path):
        raise SourceError(tr("Файл с вопросами {a0} не найден.", a0=path))
    text, _ = read_text(path)
    out = [line.strip() for line in text.splitlines()
           if line.strip() and not line.strip().startswith("#")]
    if not out:
        raise SourceError(tr("{a0}: ни одного вопроса.", a0=path))
    return out


def prompts_from_keywords(rows: list, field: str, limit: int = 10) -> list:
    """
    Вопросы из семантики: берутся самые частотные ключи как есть.

    Спрашивать надо тем языком, которым спрашивает человек, а не «расскажи
    про наш бренд»: цитируют в ответе на вопрос пользователя, а не на запрос
    о компании.
    """
    seen, out = set(), []
    for row in rows or ():
        value = (row.get(field) or "").strip()
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
        if len(out) >= limit:
            break
    return out
