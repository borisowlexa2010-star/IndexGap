# -*- coding: utf-8 -*-
"""
Проверки, которые ломают programmatic-конвейер чаще всего.

Три группы:
  1. Похожесть и наполнение — почти-дубли и тонкие страницы. Это то, из-за чего
     поисковик склеивает сотни сгенерированных страниц в одну и трафика нет.
  2. Перелинковка — сироты, тупики и глубина клика. Страница, на которую не ведёт
     ни одна ссылка, в sitemap есть, а в индекс не попадает.
  3. Техническая гигиена — title, description, canonical, noindex, сниппеты.

Всё считается локально, до публикации. Внешних сервисов и ключей не требуется.

Два принципа, добытых аудитом:

  * **Проверка не имеет права тихо выключаться.** Если корзина LSH переполнена
    или страниц слишком мало для статистики — об этом говорится вслух,
    а не подменяется словом «не найдено».
  * **Ссылка и страница сравниваются по ключу**, а не по строке URL.
    Иначе сайт из плоских html-файлов целиком объявляется сиротами.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict, deque

from .core import url_key
from .settings import SCRIPTLESS, text_volume

# ── настройки, которые имеет смысл крутить под свой проект ────────────────────
CONFIG = {
    "shingle_size": 5,          # длина словесной n-граммы
    "minhash_perms": 32,        # чем больше, тем точнее оценка и медленнее счёт
    "lsh_bands": 8,             # bands * rows == minhash_perms
    "exact_below": 400,         # столько страниц сравниваем попарно и точно
    "near_duplicate": 0.80,     # Jaccard, выше которого пара — почти-дубль
    "similar": 0.55,            # ниже дубля, но уже повод посмотреть
    "thin_words": 250,          # меньше слов — тонкая страница
    "boilerplate_share": 0.90,  # биграмма в этой доле страниц считается шаблонной
    "boilerplate_min_pages": 8, # меньше — статистики нет, вердикта не будет
    "unique_share_min": 0.25,   # доля неповторяющегося текста ниже — тревога
    "max_click_depth": 3,       # глубже — почти не индексируется
    "shell_words": 100,         # меньше слов при N скриптах — пустой JS-каркас
    "shell_scripts": 3,
    "title_min": 20,
    "title_max": 65,
    "description_min": 70,
    "description_max": 165,
    # Иероглифика: тот же смысл занимает примерно вдвое меньше знаков,
    # поэтому пороги длины для неё свои.
    "cjk_length_factor": 0.5,
}

_MASK = (1 << 61) - 1
_PRIME = (1 << 61) - 1


def _shingles(words: list, k: int) -> set:
    if len(words) < k:
        return {int(hashlib.blake2b(" ".join(words).encode("utf-8"),
                                    digest_size=8).hexdigest(), 16)} if words else set()
    return {
        int(hashlib.blake2b(" ".join(words[i:i + k]).encode("utf-8"), digest_size=8).hexdigest(), 16)
        for i in range(len(words) - k + 1)
    }


def _minhash(shingles: set, perms: int) -> tuple:
    """Классический minhash на семействе (a*x + b) mod prime."""
    if not shingles:
        return tuple([0] * perms)
    values = list(shingles)
    sig = []
    for i in range(perms):
        a = 0x9E3779B97F4A7C15 * (i + 1) & _MASK or 1
        b = 0xBF58476D1CE4E5B9 * (i + 3) & _MASK
        sig.append(min([(a * s + b) % _PRIME for s in values]))
    return tuple(sig)


def find_near_duplicates(pages: list, cfg: dict = None, words: dict = None) -> dict:
    """
    Ищет пары похожих страниц.

    Возвращает словарь: `pairs` — список (page_a, page_b, jaccard) по убыванию,
    и `notes` — то, что метод хочет сказать о себе вслух.

    До нескольких сотен страниц сравнение честно попарное: это точно и быстро.
    Дальше включается LSH. Переполненная корзина больше не выбрасывается —
    раньше 201 одинаковая страница давала ровно ноль находок, то есть чем хуже
    был конвейер, тем тише отчёт.
    """
    cfg = {**CONFIG, **(cfg or {})}
    notes = []
    k = cfg["shingle_size"]

    words = words or {p.url: p.words for p in pages}
    shingles = {}
    for p in pages:
        sh = _shingles(words.get(p.url, []), k)
        if sh:
            shingles[p.url] = sh
    urls = sorted(shingles)
    if len(urls) < 2:
        return {"pairs": [], "notes": notes, "method": "нет данных"}

    if len(urls) <= cfg["exact_below"]:
        method = "попарное сравнение"
        candidates = [(urls[i], urls[j])
                      for i in range(len(urls)) for j in range(i + 1, len(urls))]
    else:
        method = "LSH"
        perms, bands = cfg["minhash_perms"], cfg["lsh_bands"]
        rows = max(1, perms // bands)
        signatures = {u: _minhash(shingles[u], perms) for u in urls}
        buckets = defaultdict(list)
        for url in urls:
            sig = signatures[url]
            for b in range(bands):
                band = sig[b * rows:(b + 1) * rows]
                key = (b, hashlib.blake2b(repr(band).encode(), digest_size=8).digest())
                buckets[key].append(url)

        cap = 200
        candidate_set = set()
        clustered = 0
        for bucket in buckets.values():
            if len(bucket) < 2:
                continue
            if len(bucket) <= cap:
                for i in range(len(bucket)):
                    for j in range(i + 1, len(bucket)):
                        candidate_set.add((bucket[i], bucket[j]))
            else:
                # Корзина такого размера — это не «шаблон, значит не дубли»,
                # а наоборот: кластер почти одинаковых страниц. Полный перебор
                # внутри неё квадратичен, поэтому сравниваем всех с образцом.
                clustered += 1
                rep = bucket[0]
                for other in bucket[1:]:
                    candidate_set.add((rep, other))
        if clustered:
            notes.append(
                f"{clustered} групп(ы) страниц оказались настолько похожи, что "
                f"сравнивались с образцом группы, а не попарно — иначе счёт "
                f"занял бы часы. Пары внутри такой группы показаны не все.")
        candidates = sorted(candidate_set)

    by_url = {p.url: p for p in pages}
    out = []
    for a, b in candidates:
        sa, sb = shingles[a], shingles[b]
        union = len(sa | sb)
        if not union:
            continue
        j = len(sa & sb) / union
        if j >= cfg["similar"]:
            out.append((by_url[a], by_url[b], round(j, 3)))
    out.sort(key=lambda t: (-t[2], t[0].url, t[1].url))
    return {"pairs": out, "notes": notes, "method": method}


def trimmed_words(pages: list) -> dict:
    """
    Слова страницы без общей обвязки сайта.

    Если часть страниц размечена `<main>`, а часть нет, то у первых меню
    и подвал уже вычтены, а у вторых нет — и вердикт переворачивался:
    аккуратно свёрстанная страница получала «уникально 19%», а неаккуратная
    проходила чисто. Здесь у страниц без разметки отрезается общий для всех
    префикс и суффикс — то есть та же шапка и тот же подвал.
    """
    plain = [p for p in pages if not p.chrome]
    words = {p.url: p.words for p in pages}
    if len(plain) < 3 or len(plain) == len(pages):
        return words

    lists = [words[p.url] for p in plain if words[p.url]]
    if not lists:
        return words
    shortest = min(len(w) for w in lists)

    prefix = 0
    while prefix < shortest // 2 and len({w[prefix] for w in lists}) == 1:
        prefix += 1
    suffix = 0
    while suffix < shortest // 2 - prefix and len({w[-1 - suffix] for w in lists}) == 1:
        suffix += 1
    if not prefix and not suffix:
        return words
    for p in plain:
        w = words[p.url]
        words[p.url] = w[prefix:len(w) - suffix] if suffix else w[prefix:]
    return words


def boilerplate_profile(pages: list, cfg: dict = None, words: dict = None) -> dict:
    """
    Для каждой страницы — доля текста, которая НЕ является шаблоном.

    Считается по биграммам, а не по отдельным словам. В узкой нише словарь
    естественно ограничен: «виза», «документы», «срок» законно стоят на каждой
    странице, и по словам любой нормальный конвейер выглядел бы как шаблон.
    А вот повторяющиеся ФРАЗЫ — это уже меню, футер и неизменная часть шаблона.

    На горстке страниц вердикта не будет: порог «в 90% страниц» на выборке
    из трёх означает «на двух», и результат скачет от 20% до 99% при добавлении
    одной страницы. Молчать про это нельзя, поэтому возвращается и причина.
    """
    cfg = {**CONFIG, **(cfg or {})}
    if len(pages) < cfg["boilerplate_min_pages"]:
        return {"shares": {}, "skipped": (
            f"страниц {len(pages)}, для оценки шаблонности нужно хотя бы "
            f"{cfg['boilerplate_min_pages']} — на меньшей выборке результат "
            f"меняется от одной добавленной страницы")}

    words = words or {p.url: p.words for p in pages}

    def bigrams(seq):
        return [f"{seq[i]} {seq[i+1]}" for i in range(len(seq) - 1)]

    df = Counter()
    for p in pages:
        df.update(set(bigrams(words.get(p.url, []))))
    # Порог не может требовать «на всех страницах»: при девяти страницах
    # ceil(9*0.9) давал ровно 9, шаблон переставал находиться, и добавление
    # десятой страницы переворачивало вердикт с «всё чисто» на «10 критичных».
    threshold = max(2, min(len(pages) - 1,
                           math.ceil(len(pages) * cfg["boilerplate_share"])))
    common = {g for g, c in df.items() if c >= threshold}

    shares = {}
    for p in pages:
        grams = bigrams(words.get(p.url, []))
        if not grams:
            shares[p.url] = 0.0
            continue
        unique = sum(1 for g in grams if g not in common)
        shares[p.url] = round(unique / len(grams), 3)
    return {"shares": shares, "skipped": ""}


def link_graph(pages: list, home_url: str = None) -> dict:
    """
    Строит граф внутренних ссылок и считает то, что влияет на индексацию:
    входящие, исходящие, глубина клика от главной, сироты и тупики.

    Главная задаётся явно (из --site). Раньше за неё брался самый короткий URL,
    и на каталоге без главной 11 страниц из 12 объявлялись недостижимыми —
    катастрофа, которой нет. Если главной среди страниц нет, глубина
    не считается вовсе, и об этом сообщается.
    """
    by_key = {p.key: p.url for p in pages}
    inbound = defaultdict(set)
    outbound = {}
    unresolved = set()
    for p in pages:
        targets = set()
        for link in p.links:
            key = url_key(link)
            target = by_key.get(key)
            if target and target != p.url:
                targets.add(target)
            elif not target:
                unresolved.add(key)
        outbound[p.url] = targets
        for t in targets:
            inbound[t].add(p.url)

    home = by_key.get(url_key(home_url)) if home_url else None
    # Раньше флаг зависел от того, передали ли адрес: CLI передавал None,
    # когда главной среди страниц нет, и предупреждение не печаталось никогда.
    urls = sorted(by_key.values())

    depth = {}
    if home:
        depth[home] = 0
        queue = deque([home])
        while queue:
            cur = queue.popleft()
            for nxt in sorted(outbound.get(cur, ())):
                if nxt not in depth:
                    depth[nxt] = depth[cur] + 1
                    queue.append(nxt)

    return {
        "home": home,
        "home_missing": not home,
        "inbound": {u: sorted(inbound.get(u, ())) for u in urls},
        "outbound": {u: sorted(t) for u, t in outbound.items()},
        "depth": depth,
        "unresolved": sorted(unresolved),
        "orphans": sorted(u for u in urls if not inbound.get(u) and u != home),
        "dead_ends": sorted(u for u in urls if not outbound.get(u)),
        "unreachable": sorted(u for u in urls if u not in depth) if home else [],
    }


def root_mismatch(pages: list, graph: dict) -> str:
    """
    Самый частый неверный вердикт: каталог не соответствует корню сайта.

    Запуск из корня проекта вместо `./content` сдвигает все адреса на сегмент,
    ссылки перестают совпадать, и человек получает «все страницы сироты» —
    без единого сигнала о том, что виноват путь, а не перелинковка.
    Проверяем прямо: сойдутся ли неразрешённые ссылки, если у адресов страниц
    убрать первый сегмент пути.
    """
    unresolved = set(graph.get("unresolved") or [])
    orphans = graph.get("orphans") or []
    if not unresolved or not pages or len(orphans) < max(3, len(pages) * 0.5):
        return ""
    shifted = set()
    for p in pages:
        # Ключ имеет вид //host/путь — снимаем первый сегмент пути.
        host, _, path = p.key.lstrip("/").partition("/")
        _, _, tail = path.partition("/")
        if tail:
            shifted.add(f"//{host}/{tail}")
    hits = len(unresolved & shifted)
    if hits >= max(2, len(unresolved) * 0.5):
        first = pages[0].path
        return ("похоже, каталог не соответствует корню сайта: ссылки на страницах "
                "короче их собственных адресов на один сегмент. Из-за этого все "
                "страницы выглядят сиротами, и такой же сдвиг уедет в sitemap.\n"
                f"    Проверь, какой каталог отображается в корень {pages[0].url.split('/')[2]}"
                f" — сейчас это {first.rsplit('/', 2)[0] or '.'}")
    return ""


def _length_bounds(cfg: dict, language: str) -> dict:
    """Пороги длины зависят от письменности: 60 иероглифов — это не 60 букв."""
    code = (language or "").split("-")[0].lower()
    factor = cfg["cjk_length_factor"] if code in SCRIPTLESS else 1.0
    return {
        "title_min": int(cfg["title_min"] * factor),
        "title_max": int(cfg["title_max"] * factor),
        "description_min": int(cfg["description_min"] * factor),
        "description_max": int(cfg["description_max"] * factor),
    }


_AMP_RE = re.compile(r"<html[^>]*\s(amp|⚡)[\s=>]", re.I)


def is_shell(page, cfg: dict = None) -> bool:
    """
    Страница, которую рисует JavaScript: в исходном HTML текста нет.

    Проверено на живом каталоге недвижимости из 1 099 страниц: все они
    отдавались пустой оболочкой. Пакет нашёл там 1 099 `js-shell` — и вместе
    с ними 1 099 `low-uniqueness` и 1 098 `orphan`, хотя это не три беды,
    а одна: в пустом HTML не из чего считать ни уникальность, ни ссылки.
    Поэтому оболочку теперь определяет `checks`, а зависимые проверки
    на таких страницах не запускаются.
    """
    cfg = {**CONFIG, **(cfg or {})}
    blocks = page.blocks or {}
    # AMP по определению рендерится без своего JavaScript, а её обязательный
    # рантайм — это те самые три скрипта.
    if _AMP_RE.search(page.raw or ""):
        return False
    if page.word_count >= 25 and (page.chrome or blocks.get("p")):
        return False
    return (page.word_count < cfg["shell_words"]
            and blocks.get("script", 0) >= cfg["shell_scripts"])


# Находки, которые на пустой оболочке ничего не значат: их источник — текст
# и ссылки, которых в исходном HTML просто нет.
SHELL_DEPENDENT = {
    "thin", "low-uniqueness", "template-skeleton", "same-opening",
    "near-duplicate", "similar", "no-headings", "no-h1", "many-h1",
    "orphan", "unreachable", "deep", "description-length",
}


def technical_issues(pages: list, cfg: dict = None, language: str = "",
                     shells: set = None) -> list:
    """Плоский список находок: (уровень, url, код, пояснение)."""
    cfg = {**CONFIG, **(cfg or {})}
    bounds = _length_bounds(cfg, language)
    shells = shells or set()
    issues = []

    titles = defaultdict(list)
    descriptions = defaultdict(list)
    for p in pages:
        if p.title:
            titles[p.title.strip().lower()].append(p.url)
        if p.description:
            descriptions[p.description.strip().lower()].append(p.url)

    for p in pages:
        for note in p.notes:
            issues.append(("warning", p.url, "source-note", note))
        if p.noindex:
            issues.append(("critical", p.url, "noindex",
                           "страница закрыта от индексации — если это не задумано, трафика не будет"))
        if p.nosnippet:
            issues.append(("critical", p.url, "nosnippet",
                           "запрещён сниппет: страница может быть в индексе, но в ответы "
                           "ИИ-поиска и в расширенную выдачу не попадёт"))
        if not p.title:
            issues.append(("critical", p.url, "no-title", "нет title"))
        else:
            n = len(p.title)
            if n < bounds["title_min"]:
                issues.append(("warning", p.url, "title-short", f"title {n} символов"))
            elif n > bounds["title_max"]:
                issues.append(("info", p.url, "title-long",
                               f"title {n} символов, обрежется в выдаче"))
        if not p.description:
            issues.append(("warning", p.url, "no-description", "нет meta description"))
        else:
            n = len(p.description)
            if n < bounds["description_min"] or n > bounds["description_max"]:
                issues.append(("info", p.url, "description-length",
                               f"description {n} символов"))

        h1 = [t for lvl, t in p.headings if lvl == 1]
        if not p.headings:
            issues.append(("warning", p.url, "no-headings", "на странице нет заголовков"))
        elif not h1:
            issues.append(("warning", p.url, "no-h1",
                           "нет H1 — поисковику нечем определить, о чём страница"))
        elif len(h1) > 1:
            issues.append(("info", p.url, "many-h1", f"H1 на странице {len(h1)}, нужен один"))

        if p.canonical and url_key(p.canonical) != p.key:
            issues.append(("critical", p.url, "canonical-elsewhere",
                           f"canonical указывает на {p.canonical} — страница отдаёт вес другой"))
        volume = text_volume(p, language)
        if volume < cfg["thin_words"]:
            issues.append(("warning", p.url, "thin",
                           f"объём текста ≈ {volume} — тонкая страница"))

    issues = [i for i in issues if not (i[1] in shells and i[2] in SHELL_DEPENDENT)]

    for title, urls in sorted(titles.items()):
        if len(urls) > 1:
            for u in sorted(urls):
                issues.append(("warning", u, "duplicate-title",
                               f"такой же title ещё у {len(urls) - 1} страниц"))
    for desc, urls in sorted(descriptions.items()):
        if len(urls) > 1:
            for u in sorted(urls):
                issues.append(("info", u, "duplicate-description",
                               f"такой же description ещё у {len(urls) - 1} страниц"))
    return issues


LEVEL_ORDER = {"critical": 0, "warning": 1, "info": 2}

# Порядок важности внутри уровня: сначала то, что чинится и даёт трафик,
# потом косметика. Раньше сортировка шла по алфавиту кода, и главная находка
# пакета оказывалась в самом низу списка.
CODE_WEIGHT = {
    "stale-event": 0, "unsupported-number": 1, "still-draft": 2, "brief-left": 3,
    "noindex": 3, "nosnippet": 4, "canonical-elsewhere": 5,
    "orphan": 6, "unreachable": 7, "near-duplicate": 8, "low-uniqueness": 9,
    "template-skeleton": 10, "same-opening": 11, "thin": 12,
    "no-title": 13, "no-h1": 14, "duplicate-title": 15, "deep": 16,
    "similar": 17, "source-note": 18, "check-by-eye": 19, "stale-closed": 30,
}


# Находки, которые и должны встречаться массово: это их природа, а не шаблон.
NOT_TEMPLATE_WIDE = {"near-duplicate", "similar", "js-shell", "unsupported-number",
                     "stale-event", "still-draft", "brief-left"}


def template_wide(issues: list, page_count: int, share: float = 0.9) -> list:
    """
    Что встречается почти на всех страницах — свойство шаблона, а не список дел.

    На живом каталоге виз `vague-anchor` сработал на 2 970 страницах из 2 970,
    а `no-question-headings` — на 2 919. Формально верно, практически бесполезно:
    человек видит три тысячи «находок» и закрывает отчёт. Чинится это один раз
    в шаблоне, и сказать об этом надо один раз.
    """
    if page_count < 20:
        return []
    by_code = defaultdict(set)
    for level, url, code, _ in issues:
        if code in NOT_TEMPLATE_WIDE or not url or url == "robots.txt":
            continue
        by_code[code].add(url)
    notes = []
    for code, urls in sorted(by_code.items()):
        got = len(urls) / page_count
        if got >= share:
            notes.append(
                f"`{code}` — на {len(urls)} страницах из {page_count} ({got:.0%}). "
                "Это свойство шаблона, а не список страниц: чинится один раз "
                "в шаблоне и исчезает везде.")
    return notes


def sort_issues(issues: list) -> list:
    return sorted(issues, key=lambda i: (LEVEL_ORDER.get(i[0], 3),
                                         CODE_WEIGHT.get(i[2], 50), i[2], i[1]))


def _clusters(edges: list) -> list:
    """Связные компоненты: группы страниц, которые дублируют друг друга."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups = defaultdict(list)
    for node in parent:
        groups[find(node)].append(node)
    return sorted((sorted(g) for g in groups.values()), key=len, reverse=True)


def run_all(pages: list, home_url: str = None, cfg: dict = None,
            language: str = "") -> dict:
    """Единая точка входа: всё, что считается локально, без сети."""
    cfg = {**CONFIG, **(cfg or {})}
    graph = link_graph(pages, home_url)
    words = trimmed_words(pages)
    boiler = boilerplate_profile(pages, cfg, words)
    dupes = find_near_duplicates(pages, cfg, words)
    shells = {p.url for p in pages if is_shell(p, cfg)}
    issues = technical_issues(pages, cfg, language, shells=shells)
    notes = list(dupes["notes"])
    for url in sorted(shells):
        issues.append(("critical", url, "js-shell",
                       "в исходном HTML нет текста — его рисует JavaScript, "
                       "а краулеры ИИ-поиска его не исполняют"))
    if shells:
        share = len(shells) / len(pages) if pages else 0
        notes.append(
            f"пустых JS-каркасов: {len(shells)} из {len(pages)} ({share:.0%}). "
            "На этих страницах не считались объём текста, уникальность, дубли "
            "и ссылки — в исходном HTML их неоткуда взять. Это одна беда, "
            "а не четыре: появится серверный HTML — проверки заработают.")
    if boiler["skipped"]:
        notes.append("шаблонность не оценивалась: " + boiler["skipped"])
    mismatch = root_mismatch(pages, graph)
    if mismatch:
        notes.append(mismatch)
    if graph["home_missing"]:
        notes.append(
            "главной страницы нет среди разобранных файлов, поэтому глубина клика "
            "и недостижимость не считались. Проверь --site и корень каталога.")

    for url, share in sorted(boiler["shares"].items()):
        if share < cfg["unique_share_min"] and url not in shells:
            issues.append(("critical", url, "low-uniqueness",
                           f"только {share:.0%} текста уникально — остальное шаблон"))
    for url in graph["orphans"]:
        if url not in shells:
            issues.append(("critical", url, "orphan",
                           "ни одна внутренняя ссылка не ведёт на страницу"))
    for url in graph["unreachable"]:
        if url not in graph["orphans"] and url not in shells:
            issues.append(("critical", url, "unreachable",
                           "до страницы нельзя дойти от главной по ссылкам"))
    for url, d in sorted(graph["depth"].items()):
        if url in shells:
            continue
        if d > cfg["max_click_depth"]:
            issues.append(("warning", url, "deep",
                           f"{d} кликов от главной — краулер доходит редко"))

    # Одна находка на страницу, а не на пару: двести одинаковых страниц дают
    # 19 900 пар, и блок «чинить в этом порядке» сообщал «19 900 near-duplicate».
    partners = defaultdict(list)
    for a, b, j in dupes["pairs"]:
        partners[a.url].append((j, b.url))
        partners[b.url].append((j, a.url))
    for url in sorted(partners):
        if url in shells:
            continue
        found = sorted(partners[url], reverse=True)
        best, other = found[0]
        more = f" и ещё {len(found) - 1}" if len(found) > 1 else ""
        if best >= cfg["near_duplicate"]:
            issues.append(("critical", url, "near-duplicate",
                           f"совпадает на {best:.0%} со страницей {other}{more} — "
                           f"поисковик оставит в индексе одну"))
        else:
            issues.append(("info", url, "similar",
                           f"похожа на {best:.0%} на {other}{more}"))

    # Дубли живут группами, а не парами. На живом каталоге виз 588 страниц
    # с кодом `near-duplicate` оказались 62 группами одинаковых по смыслу
    # страновых гайдов: «переписать 588 страниц» — приговор, «развести 62 темы»
    # — задача. Поэтому счёт групп говорится вслух.
    groups = _clusters([(a.url, b.url) for a, b, j in dupes["pairs"]
                        if j >= cfg["near_duplicate"] and a.url not in shells
                        and b.url not in shells])
    if groups:
        biggest = max(len(g) for g in groups)
        notes.append(
            f"почти-дубли образуют {len(groups)} групп(ы), в самой большой "
            f"{biggest} страниц. Чинится по группам: одна остаётся, остальные "
            "переписываются под другой интент или отдают ей canonical.")

    # Две пустые оболочки совпадают на 100% — и это ничего не значит.
    # Пока они оставались в `duplicates`, счётчик «похожих пар» показывал
    # сотни находок там, где находка ровно одна: пустой HTML.
    pairs = [(a, b, j) for a, b, j in dupes["pairs"]
             if a.url not in shells and b.url not in shells]

    return {
        "pages": pages,
        "graph": graph,
        "unique_share": boiler["shares"],
        "duplicates": pairs,
        "duplicate_method": dupes["method"],
        "issues": sort_issues(issues),
        "notes": notes,
        "config": cfg,
    }
