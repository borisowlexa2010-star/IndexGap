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
import json
import math
import re
from collections import Counter, defaultdict, deque

from . import hreflang
from .core import EMPTY_MOUNT, NOT_LIVE, SourceError, drop_spans, is_dense
from .core import url_key
from .publish import indexable
from .settings import display_width, text_volume
from .i18n import tr

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
    # Подставленные значения шаблона: пара страниц считается одним текстом,
    # если различающихся слов у каждой не больше этого числа или этой доли.
    "slot_words": 6,
    "slot_share": 0.04,
    "slot_floor": 0.30,         # ниже этого сходства пару не перепроверяем
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
    # Столько запаркованных переводов нужно, чтобы считать это правилом
    # шаблона. Меньше — каждая страница сообщается сама, как раньше.
    "parked_rule_min": 5,
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
    """
    Minhash одной перестановкой: шингл попадает в одну из `perms` корзин, в
    корзине держится минимум. Пустые корзины берут значение у соседней.

    Классический вариант считал `perms` хэшей на каждый шингл — тридцать два
    прохода по странице в чистом Python, десять секунд из семидесяти на большом
    каталоге. Здесь проход один, а оценка сходства не хуже.
    """
    if not shingles:
        return tuple([0] * perms)
    empty = _PRIME
    sig = [empty] * perms
    for s in shingles:
        h = (0x9E3779B97F4A7C15 * s + 0xBF58476D1CE4E5B9) & _MASK
        slot = h % perms
        value = h // perms
        if value < sig[slot]:
            sig[slot] = value
    if empty in sig:
        # Уплотнение: пустая корзина занимает значение ближайшей непустой
        # справа, по кругу, со сдвигом на расстояние — иначе две короткие
        # страницы совпадали бы по всем пустым корзинам сразу.
        filled = [i for i, v in enumerate(sig) if v != empty]
        if not filled:
            return tuple([0] * perms)
        for i in range(perms):
            if sig[i] != empty:
                continue
            step = 1
            while sig[(i + step) % perms] == empty or (i + step) % perms not in filled:
                step += 1
            sig[i] = sig[(i + step) % perms] + step * 0x9E3779B1
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

    # Как и sitemap, сравниваем страницы, которые претендуют на индекс.
    # У noindex, черновика и canonical-алиаса нет отдельной поисковой выдачи;
    # технические предупреждения об этих состояниях остаются в run_all.
    eligible = [p for p in pages if indexable(p)]
    excluded = len(pages) - len(eligible)
    if excluded:
        notes.append(tr("Из сравнения дублей исключено {a0} страниц: noindex, "
                        "canonical на другую страницу или черновик.", a0=excluded))
    pages = eligible

    words = words or {p.url: p.words for p in pages}
    shingles = {}
    for p in pages:
        own = words.get(p.url, [])
        # У иероглифики слово — один знак: пять знаков подряд совпадают у любых
        # двух текстов на одну тему. Шингл берётся вдвое длиннее.
        sh = _shingles(own, k * 2 if is_dense(own) else k)
        if sh:
            shingles[p.url] = sh
    urls = sorted(shingles)
    if len(urls) < 2:
        return {"pairs": [], "notes": notes, "method": tr("нет данных")}

    if len(urls) <= cfg["exact_below"]:
        method = tr("попарное сравнение")
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
                tr("{a0} групп(ы) страниц оказались настолько похожи, что сравнивались с образцом группы, а не попарно — иначе счёт занял бы часы. Пары внутри такой группы показаны не все.", a0=clustered))
        candidates = sorted(candidate_set)

    by_url = {p.url: p for p in pages}
    out = []
    for a, b in candidates:
        sa, sb = shingles[a], shingles[b]
        union = len(sa | sb)
        if not union:
            continue
        j = len(sa & sb) / union
        if cfg["slot_floor"] <= j < cfg["near_duplicate"]:
            j = max(j, _without_slots(words.get(a, []), words.get(b, []), k, cfg))
        if j >= cfg["similar"]:
            out.append((by_url[a], by_url[b], round(j, 3)))
    out.sort(key=lambda t: (-t[2], t[0].url, t[1].url))
    return {"pairs": out, "notes": notes, "method": method}


def _without_slots(a: list, b: list, k: int, cfg: dict) -> float:
    """
    Сходство двух страниц, если не считать подставленных значений.

    Шаблон «Аренда в городе {city}» даёт страницы, одинаковые на 95% слов, но
    каждое вхождение города портит пять соседних шинглов — и сходство выходило
    0,6: ниже порога, без единой находки. Пять тысяч страниц одного шаблона
    получали «критичных: 0».

    Подставленное значение узнаётся в паре: это слова, которые есть на одной
    странице и которых нет на другой, при том что таких слов мало. Они
    заменяются одной меткой, и сходство считается заново. Если страницы
    различаются многими словами, это разный текст, и замены не происходит.
    """
    va, vb = set(a), set(b)
    only_a, only_b = va - vb, vb - va
    limit = max(cfg["slot_words"], int(min(len(va), len(vb)) * cfg["slot_share"]))
    if not (only_a or only_b) or len(only_a) > limit or len(only_b) > limit:
        return 0.0
    k = k * 2 if is_dense(a) else k
    sa = _shingles(["\x00" if w in only_a else w for w in a], k)
    sb = _shingles(["\x00" if w in only_b else w for w in b], k)
    union = len(sa | sb)
    return len(sa & sb) / union if union else 0.0


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
    words = {p.url: list(p.words) for p in pages}
    # Раньше обрезка не делалась вовсе, если <main> нет ни у одной страницы, —
    # то есть ровно на тех сайтах, где шапка и подвал сидят в тексте каждой
    # страницы и сравниваются как её содержание.
    if len(plain) < 3:
        return words

    lists = [words[p.url] for p in plain if words[p.url]]
    if not lists:
        return words
    lengths = sorted(len(w) for w in lists)
    typical = lengths[len(lengths) // 10]          # не самая короткая: одна
    need = max(2, math.ceil(len(lists) * 0.9))     # страница не решает за всех

    def common(position):
        # Слово общее, если стоит на этом месте у девяти страниц из десяти.
        # Требование «у всех» обнуляла одна иначе свёрстанная страница.
        counts = Counter(w[position] for w in lists if len(w) > abs(position) - (position < 0))
        word, n = counts.most_common(1)[0] if counts else ("", 0)
        return word if n >= need else None

    head = []
    while len(head) < typical // 2:
        word = common(len(head))
        if word is None:
            break
        head.append(word)
    tail = []
    while len(tail) < typical // 2 - len(head):
        word = common(-1 - len(tail))
        if word is None:
            break
        tail.append(word)
    if not head and not tail:
        return words
    tail.reverse()
    for p in plain:
        w = words[p.url]
        if head and w[:len(head)] == head:
            w = w[len(head):]
        if tail and w[-len(tail):] == tail:
            w = w[:-len(tail)]
        words[p.url] = w
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
            tr("страниц {a0}, для оценки шаблонности нужно хотя бы {a1} — на меньшей выборке результат меняется от одной добавленной страницы", a0=len(pages), a1=cfg['boilerplate_min_pages']))}

    words = words or {p.url: p.words for p in pages}

    def bigrams(seq):
        return [f"{seq[i]} {seq[i+1]}" for i in range(len(seq) - 1)]

    # Шаблон свой у каждого языка. Если считать фразы по всем страницам сразу,
    # на сайте из двух языков ни одна не встретится «в 90% страниц» — и
    # проверка молчала именно там, где шаблонов больше одного: шестьсот
    # страниц одного шаблона давали шестьсот находок, дважды по триста — ноль.
    cohorts = defaultdict(list)
    for p in pages:
        cohorts[_cohort(p)].append(p)

    shares, small = {}, 0
    for members in cohorts.values():
        if len(members) < cfg["boilerplate_min_pages"]:
            small += len(members)
            continue
        df = Counter()
        for p in members:
            df.update(set(bigrams(words.get(p.url, []))))
        # Порог не может требовать «на всех страницах»: при девяти страницах
        # ceil(9*0.9) давал ровно 9, шаблон переставал находиться, и добавление
        # десятой страницы переворачивало вердикт с «всё чисто» на «10 критичных».
        threshold = max(2, min(len(members) - 1,
                               math.ceil(len(members) * cfg["boilerplate_share"])))
        common = {g for g, c in df.items() if c >= threshold}
        for p in members:
            grams = bigrams(words.get(p.url, []))
            if not grams:
                shares[p.url] = 0.0
                continue
            unique = sum(1 for g in grams if g not in common)
            shares[p.url] = round(unique / len(grams), 3)
    skipped = ""
    if small:
        skipped = tr("у {a0} страниц(ы) на языках, где страниц меньше {a1}, — "
                     "на такой выборке вердикт был бы случайным",
                     a0=small, a1=cfg["boilerplate_min_pages"])
    return {"shares": shares, "skipped": skipped}


def _cohort(page) -> str:
    """Группа, внутри которой шаблон общий: язык страницы, а нет его — префикс пути."""
    lang = (getattr(page, "lang", "") or "").split("-")[0].lower()
    if lang:
        return lang
    return _locale_split(page.url)[1]


# Корень сайта на Next.js — часто не страница, а заглушка: RSC-поток с командой
# NEXT_REDIRECT на /en. Классический вариант того же — meta refresh.
_NEXT_REDIRECT = re.compile(r"NEXT_REDIRECT;(?:replace|push);([^;\"\\\s]+);30[1278]")
_META_TAG = re.compile(r"<meta\b[^>]{0,2000}>", re.I)
_REFRESH = re.compile(r"http-equiv\s*=\s*[\"']?refresh", re.I)
_REFRESH_CONTENT = re.compile(
    r"content\s*=\s*[\"']\s*(\d+(?:\.\d+)?)\s*[;,]\s*url\s*=\s*['\"]?([^\"'\s>]+)", re.I)
# Где «редирект» — не редирект: его показывают, выключили или держат про запас.
_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.I | re.S)


def redirect_target(page) -> str:
    """
    Куда страница перебрасывает, если это заглушка-редирект; иначе пусто.

    Заглушка не проверяется как страница, поэтому ошибиться здесь дорого:
    у настоящей страницы молча пропадут все находки. Раньше хватало строки
    в исходнике — и заглушкой становилась статья про Next.js с примером
    в <code>, страница с <noscript>-переадресацией для браузеров без скриптов
    и страница, которая сама себя обновляет раз в пять минут.

    Редиректом считается meta refresh с нулевой задержкой, стоящий в живой
    разметке, и `NEXT_REDIRECT` внутри <script> на странице без текста.
    """
    # Спрашивают об этом много раз за прогон, а исходник бывает в сотни
    # килобайт: ответ запоминается на странице.
    try:
        return page._redirect_target
    except AttributeError:
        target = _redirect_target(page)
        try:
            page._redirect_target = target
        except AttributeError:
            pass
        return target


def _redirect_target(page) -> str:
    from urllib.parse import urljoin
    raw = getattr(page, "raw", "") or ""
    if str(getattr(page, "path", "")).lower().endswith((".md", ".markdown")):
        return ""
    # Дешёвые признаки первыми: вычищать исходник в сотни килобайт стоит,
    # только если в нём вообще есть что искать.
    by_script = ("NEXT_REDIRECT" in raw
                 and len((getattr(page, "text", "") or "").split()) < 30)
    # Подстрока ищется на порядок быстрее выражения без учёта регистра, а на
    # большинстве страниц `http-equiv` нет вовсе.
    by_meta = (("http-equiv" in raw or "HTTP-EQUIV" in raw or "Http-Equiv" in raw)
               and bool(_REFRESH.search(raw)))
    if not by_script and not by_meta:
        return ""
    live = drop_spans(raw, NOT_LIVE)
    if by_meta:
        for tag in _META_TAG.findall(live):
            if not _REFRESH.search(tag):
                continue
            found = _REFRESH_CONTENT.search(tag)
            if found and float(found.group(1)) <= 1:
                return urljoin(page.url, found.group(2).strip())
    if by_script:
        for script in _SCRIPT.findall(live):
            found = _NEXT_REDIRECT.search(script)
            if found:
                return urljoin(page.url, found.group(1).strip())
    return ""


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
    by_hreflang = defaultdict(set)
    unresolved = set()
    for p in pages:
        targets = set()
        for link in p.links:
            key = url_key(link)
            # `/a/?utm_source=nav` — ссылка на `/a/`: если страницы с такими
            # параметрами нет, это та же страница с меткой в адресе.
            target = by_key.get(key) or by_key.get(key.split("?", 1)[0])
            if target and target != p.url:
                targets.add(target)
            elif not target:
                unresolved.add(key)
        # Заглушка-редирект ведёт туда, куда перебрасывает, — хотя ссылки <a>
        # в ней нет. Алиасы Hugo так и устроены, и всё за ними считалось
        # недостижимым.
        landing = redirect_target(p)
        landing = by_key.get(url_key(landing)) if landing else None
        if landing and landing != p.url:
            targets.add(landing)
        outbound[p.url] = targets
        for t in targets:
            inbound[t].add(p.url)
        # hreflang — объявленная связь между версиями страницы. В Astro
        # Starlight переключатель языков — <select>, ссылок <a> между версиями
        # нет вовсе, и одиннадцать переводов сайта Gin — 1 122 страницы —
        # считались недостижимыми. Поисковик по hreflang их находит.
        for _code, href in hreflang.read_alternates(p):
            twin = by_key.get(url_key(href)) if href else None
            if twin and twin != p.url:
                by_hreflang[p.url].add(twin)

    home = by_key.get(url_key(home_url)) if home_url else None
    # Главная-заглушка: ссылок из неё нет, и без этого шага недостижимым
    # объявлялся весь сайт. На каталоге виз — около трёх тысяч страниц.
    redirected_from = None
    if home:
        by_url = {p.url: p for p in pages}
        walked = {home}
        while True:                           # цепочка, но не петля
            target = redirect_target(by_url[home])
            nxt = by_key.get(url_key(target)) if target else None
            if not nxt or nxt in walked:
                break
            walked.add(nxt)
            redirected_from = redirected_from or home
            home = nxt
    # Раньше флаг зависел от того, передали ли адрес: CLI передавал None,
    # когда главной среди страниц нет, и предупреждение не печаталось никогда.
    urls = sorted(by_key.values())

    def walk(edges):
        found = {}
        if home:
            found[home] = 0
            queue = deque([home])
            while queue:
                cur = queue.popleft()
                for nxt in sorted(edges(cur)):
                    if nxt not in found:
                        found[nxt] = found[cur] + 1
                        queue.append(nxt)
        return found

    by_links = walk(lambda u: outbound.get(u, ()))
    depth = walk(lambda u: set(outbound.get(u, ())) | by_hreflang.get(u, set()))
    # Страницы, до которых ссылками <a> не дойти, а через hreflang — можно.
    only_hreflang = sorted(set(depth) - set(by_links))
    hreflang_inbound = defaultdict(set)
    for source, twins in by_hreflang.items():
        for twin in twins:
            hreflang_inbound[twin].add(source)

    return {
        "home": home,
        "home_missing": not home,
        "inbound": {u: sorted(inbound.get(u, ())) for u in urls},
        "outbound": {u: sorted(t) for u, t in outbound.items()},
        "depth": depth,
        "unresolved": sorted(unresolved),
        "home_redirected_from": redirected_from,
        # Сама заглушка — не страница: на неё не должны вести ссылки, и из неё
        # никуда не нужно доходить.
        "only_hreflang": only_hreflang,
        "orphans": sorted(u for u in urls if not inbound.get(u) and u != home
                          and u != redirected_from and not hreflang_inbound.get(u)),
        "dead_ends": sorted(u for u in urls if not outbound.get(u)),
        "unreachable": sorted(u for u in urls if u not in depth
                              and u != redirected_from) if home else [],
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
        return (tr("похоже, каталог не соответствует корню сайта: ссылки на страницах короче их собственных адресов на один сегмент. Из-за этого все страницы выглядят сиротами, и такой же сдвиг уедет в sitemap.\n    Проверь, какой каталог отображается в корень {a0} — сейчас это {a1}", a0=pages[0].url.split('/')[2], a1=first.rsplit('/', 2)[0] or '.'))
    return ""


def _length_bounds(cfg: dict, language: str = "") -> dict:
    """
    Пороги длины. Один и тот же для всех языков — потому что меряется ширина.

    Раньше здесь был множитель «для CJK», выбираемый по языку страницы.
    На смешанной строке — а мультиязычные сайты состоят из них: иероглифы
    плюс бренд и «Form 14A» латиницей — он ошибался в обе стороны, и выбирать
    его приходилось по объявленному языку, который может быть неверным.
    Ширина (`settings.display_width`) снимает и то и другое.
    """
    return {
        "title_min": cfg["title_min"],
        "title_max": cfg["title_max"],
        "description_min": cfg["description_min"],
        "description_max": cfg["description_max"],
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
    # Объём меряется по письменности и по всему тексту, в каком бы теге он ни
    # стоял. Раньше требовался <p>: страница контактов из адреса и списка —
    # тридцать слов и три скрипта аналитики — объявлялась оболочкой, как и
    # статья на китайском, где «слов» по пробелам выходило десять.
    volume = text_volume(page)
    if volume >= 25:
        return False
    scripts = blocks.get("script", 0)
    # Пустой узел под приложение — прямое свидетельство: сборка Vite — это он
    # и один модульный скрипт. Порог «три скрипта» её не видел.
    if EMPTY_MOUNT.search(page.raw or ""):
        return scripts >= 1
    # Страница с заголовком или с отрисованным меню статична: она короткая, а
    # не пустая. Раздел mdBook из одного заголовка, галерея Sphinx из картинок
    # и заготовка «TO WRITE» объявлялись тем, что «рисует JavaScript», — это
    # неправда, и чинить там нужно текст, а не рендеринг.
    if getattr(page, "headings", None) or len((getattr(page, "chrome", "") or "").split()) >= 10:
        return False
    if volume < 5 and scripts >= 1:
        return True
    return scripts >= cfg["shell_scripts"]


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
    bounds = _length_bounds(cfg)
    shells = shells or set()
    issues = []

    titles = defaultdict(list)
    descriptions = defaultdict(list)
    for p in pages:
        # Отдельные noindex/canonical-находки не отменяют намеренную
        # консолидацию URL и не делают её дублем индексируемой страницы.
        if not indexable(p):
            continue
        if p.title:
            titles[p.title.strip().lower()].append(p.url)
        if p.description:
            descriptions[p.description.strip().lower()].append(p.url)

    for p in pages:
        for note in p.notes:
            issues.append(("warning", p.url, "source-note", note))
        if p.noindex:
            issues.append(("critical", p.url, "noindex",
                           tr("страница закрыта от индексации — если это не задумано, трафика не будет")))
        if p.nosnippet:
            issues.append(("critical", p.url, "nosnippet",
                           tr("запрещён сниппет: страница может быть в индексе, но в ответы ИИ-поиска и в расширенную выдачу не попадёт")))
        if not p.title:
            issues.append(("critical", p.url, "no-title", tr("нет title")))
        else:
            n = display_width(p.title)
            if n < bounds["title_min"]:
                issues.append(("warning", p.url, "title-short", tr("title {a0} символов", a0=n)))
            elif n > bounds["title_max"]:
                issues.append(("info", p.url, "title-long",
                               tr("title {a0} символов, обрежется в выдаче", a0=n)))
        if not p.description:
            issues.append(("warning", p.url, "no-description", tr("нет meta description")))
        else:
            n = display_width(p.description)
            if n < bounds["description_min"] or n > bounds["description_max"]:
                issues.append(("info", p.url, "description-length",
                               tr("description {a0} символов", a0=n)))

        h1 = [t for lvl, t in p.headings if lvl == 1]
        if not p.headings:
            issues.append(("warning", p.url, "no-headings", tr("на странице нет заголовков")))
        elif not h1:
            issues.append(("warning", p.url, "no-h1",
                           tr("нет H1 — поисковику нечем определить, о чём страница")))
        elif len(h1) > 1:
            issues.append(("info", p.url, "many-h1", tr("H1 на странице {a0}, нужен один", a0=len(h1))))

        if p.canonical and url_key(p.canonical) != p.key:
            issues.append(("critical", p.url, "canonical-elsewhere",
                           tr("canonical указывает на {a0} — страница отдаёт вес другой", a0=p.canonical)))
        volume = text_volume(p, language)
        if volume < cfg["thin_words"]:
            issues.append(("warning", p.url, "thin",
                           tr("объём текста ≈ {a0} — тонкая страница", a0=volume)))

    issues = [i for i in issues if not (i[1] in shells and i[2] in SHELL_DEPENDENT)]

    for title, urls in sorted(titles.items()):
        if len(urls) > 1:
            for u in sorted(urls):
                issues.append(("warning", u, "duplicate-title",
                               tr("такой же title ещё у {a0} страниц", a0=len(urls) - 1)))
    for desc, urls in sorted(descriptions.items()):
        if len(urls) > 1:
            for u in sorted(urls):
                issues.append(("info", u, "duplicate-description",
                               tr("такой же description ещё у {a0} страниц", a0=len(urls) - 1)))
    return issues


LEVEL_ORDER = {"critical": 0, "warning": 1, "info": 2}

# Порядок важности внутри уровня: сначала то, что чинится и даёт трафик,
# потом косметика. Раньше сортировка шла по алфавиту кода, и главная находка
# пакета оказывалась в самом низу списка.
CODE_WEIGHT = {
    "stale-event": 0, "translations-parked": 1, "unsupported-number": 1, "still-draft": 2, "brief-left": 3,
    "noindex": 3, "nosnippet": 4, "canonical-elsewhere": 5,
    "hreflang-static-cluster": 4, "hreflang-canonical-conflict": 5,
    "hreflang-no-self": 5, "hreflang-no-return": 6,
    "hreflang-target-blocked": 7, "hreflang-missing": 12, "hreflang-bad-code": 13,
    "hreflang-lang-mismatch": 15, "hreflang-unknown-target": 19,
    "orphan": 6, "unreachable": 7, "near-duplicate": 8, "low-uniqueness": 9,
    "template-skeleton": 10, "same-opening": 11, "thin": 12,
    "no-title": 13, "no-h1": 14, "duplicate-title": 15, "deep": 16,
    "similar": 17, "source-note": 18, "check-by-eye": 19, "stale-closed": 30,
}


# Находки, которые и должны встречаться массово: это их природа, а не шаблон.
NOT_TEMPLATE_WIDE = {"near-duplicate", "similar", "js-shell", "unsupported-number",
                     "translations-parked",
                     "stale-event", "still-draft", "brief-left",
                     "hreflang-no-return", "hreflang-unknown-target"}


def template_wide(issues: list, page_count: int, share: float = 0.9,
                  pages: list = None) -> list:
    """
    Что встречается почти на всех страницах — свойство шаблона, а не список дел.

    На живом каталоге виз `vague-anchor` сработал на 2 970 страницах из 2 970,
    а `no-question-headings` — на 2 919. Формально верно, практически бесполезно:
    человек видит три тысячи «находок» и закрывает отчёт. Чинится это один раз
    в шаблоне, и сказать об этом надо один раз.

    Отдельно — по языкам. У мультиязычного сайта шаблон свой у каждой версии,
    и находка может покрывать сто процентов одного языка, оставаясь каплей
    в общем счёте. На том же сайте `description-length` сработал на всех 289
    китайских страницах — это 10% сайта и 100% языка. Первое ничего не значит,
    второе значит ровно то, что описания китайской версии написаны по длине
    латиницы: чинится один раз, в шаблоне этой версии.
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
                tr("`{a0}` — на {a1} страницах из {a2} ({a3:.0%}). Это свойство "
                   "шаблона, а не список страниц: чинится один раз в шаблоне "
                   "и исчезает везде.", a0=code, a1=len(urls), a2=page_count,
                   a3=got))

    total_by_lang = defaultdict(set)
    where = {}
    for page in pages or ():
        code = (page.lang or "").split("-")[0].lower()
        where[page.url] = code
        if code:
            total_by_lang[code].add(page.url)
    if len(total_by_lang) < 2:
        return notes

    for code, urls in sorted(by_code.items()):
        if len(urls) / page_count >= share:
            continue                      # уже сказано про весь сайт
        hit = defaultdict(int)
        for url in urls:
            language = where.get(url)
            if language:
                hit[language] += 1
        for language, count in sorted(hit.items()):
            total = len(total_by_lang.get(language) or ())
            if total >= 20 and count / total >= share:
                notes.append(
                    tr("`{a0}` — на {a1} страницах языка «{a2}» из {a3}, то есть "
                       "почти на всех. По сайту это лишь {a4:.0%}, но чинится "
                       "один раз: в шаблоне этой языковой версии.",
                       a0=code, a1=count, a2=language, a3=total,
                       a4=len(urls) / page_count))
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


# Первый сегмент пути — код языка: `ar`, `zh`, `pt-br`, `zh-hans`.
_URL_IN_TEXT = re.compile(r"https?://[^\s,»\"'<>)]+")

# Что следует из того, что страница закрыта и отдаёт canonical оригиналу.
# Каждое по отдельности — правда, но все вместе — один факт, сказанный семь раз.
PARKED_ECHOES = {
    "noindex", "canonical-elsewhere", "orphan", "unreachable", "deep",
    "hreflang-no-self", "hreflang-canonical-conflict", "hreflang-no-return",
    "hreflang-target-blocked",
}


# Страны, которыми сайты называют региональные разделы. Языком такой сегмент
# не является, но раздел — региональная версия, и вести себя должен как она.
_REGION_PREFIXES = {"us", "gb", "au", "nz", "sg", "ae", "za", "mx", "jp", "cn",
                    "kr", "hk", "tw", "ph", "ie", "at"}


def _is_locale(segment: str) -> bool:
    """
    Языковой ли это префикс пути.

    Формы кода мало: `/app/`, `/go/`, `/faq/`, `/api/`, `/img/`, `/new/` —
    тоже две-три буквы, и каждая считалась языком: главной приписывали
    «переводы» в `/api/` и `/faq/`, а перенос `/old/` → `/new/` объявлялся
    запаркованными переводами. Языком считается то, что есть в ISO 639-1.
    """
    match = hreflang._TAG_RE.match(segment or "")
    if not match:
        return False
    primary = match.group(1).lower()
    if primary in hreflang.LANGUAGES:
        return True
    return primary in _REGION_PREFIXES and not (match.group(2) or match.group(3))


def _locale_split(url: str) -> tuple:
    """(хост, язык, остаток пути) — язык пуст, если первого сегмента-кода нет."""
    host, _, path = url_key(url).lstrip("/").partition("/")
    first, _, rest = path.partition("/")
    if _is_locale(first):
        return host, first.lower(), rest.strip("/")
    return host, "", path.strip("/")


def parked_translations(pages: list, cfg: dict = None) -> dict:
    """
    Переводы, закрытые от индекса в пользу оригинала: `noindex` и canonical на
    ту же страницу в другом языке. {url: (язык страницы, язык оригинала)}.

    На каталоге виз так было закрыто 1 408 страниц в девяти языках, и каждая
    давала семь находок — девять десятых отчёта. Правило — одно.
    Пусто, если таких страниц меньше порога: одиночки сообщаются как раньше.
    """
    cfg = {**CONFIG, **(cfg or {})}
    parked = {}
    for p in pages:
        # `robots: none` закрывает так же, как noindex.
        if not p.noindex or not p.canonical:
            continue
        if url_key(p.canonical) == url_key(p.url):
            continue
        host, lang, rest = _locale_split(p.url)
        to_host, to_lang, to_rest = _locale_split(p.canonical)
        # Оригинал может жить и без префикса: в Next.js, Astro, Hugo и
        # Docusaurus основной язык по умолчанию стоит в корне. Раньше такой
        # сайт получал по две критичные находки на каждый закрытый перевод.
        if lang and lang != to_lang and host == to_host and rest == to_rest:
            parked[p.url] = (lang, to_lang or tr("основной"))
    return parked if len(parked) >= cfg["parked_rule_min"] else {}


def _collapse_parked(issues: list, notes: list, pages: list, cfg: dict) -> list:
    """Заменяет каскад от запаркованных переводов одной находкой."""
    parked = parked_translations(pages, cfg)
    if not parked:
        return issues
    keys = {url_key(u) for u in parked}

    def echo(issue):
        level, url, code, message = issue
        if code not in PARKED_ECHOES:
            return False
        if url in parked:
            return True
        # Открытая страница, которая в hreflang называет запаркованный перевод:
        # это то же правило, увиденное с другой стороны.
        if code in ("hreflang-target-blocked", "hreflang-no-return"):
            return any(url_key(m) in keys for m in _URL_IN_TEXT.findall(message or ""))
        return False

    kept = [i for i in issues if not echo(i)]
    removed = len(issues) - len(kept)
    # Открытые страницы, которые всё ещё называют запаркованные переводы в своём
    # hreflang. Их находки тоже сворачиваются — но сказать о них нужно: правка
    # там, на открытых страницах, а не на закрытых.
    naming = {i[1] for i in issues if echo(i) and i[1] not in parked
              and i[2] in ("hreflang-target-blocked", "hreflang-no-return")}
    known_keys = {p.key for p in pages}
    orphaned = sum(1 for p in pages if p.url in parked
                   and url_key(p.canonical) not in known_keys)

    by_lang = Counter(lang for lang, _ in parked.values())
    source = Counter(to for _, to in parked.values()).most_common(1)[0][0]
    languages = ", ".join(f"{lang} {n}" for lang, n in sorted(by_lang.items()))
    # Считается объявленная разметка, а не слово в исходнике: переключатель
    # языков `<a hreflang="en">` — не альтернатива, а ссылка.
    with_hreflang = sum(1 for p in pages if p.url in parked
                        and hreflang.read_alternates(p))

    message = tr(
        "{a0} страниц(ы) на {a1} язык(ах) закрыты noindex и отдают canonical той же "
        "странице на «{a2}». Это одно правило шаблона, а не {a0} проблем. "
        "По языкам: {a3}.",
        a0=len(parked), a1=len(by_lang), a2=source, a3=languages)
    if with_hreflang:
        message += " " + tr(
            "{a0} из них всё ещё объявляют hreflang: он называет их равноправными "
            "версиями, а canonical — дублями, и поисковик выберет сам.",
            a0=with_hreflang)
    if naming:
        message += " " + tr(
            "{a0} открыт(ых) страниц всё ещё называют их в своём hreflang — "
            "убрать нужно и оттуда.", a0=len(naming))
    if orphaned:
        message += " " + tr(
            "У {a0} из них canonical ведёт на страницу, которой среди файлов нет.",
            a0=orphaned)
    kept.append(("critical", "hreflang", "translations-parked", message))
    notes.append(tr(
        "запаркованные переводы: {a0} страниц(ы) сведены в одну находку, "
        "снято {a1} повторов — у каждой страницы было до семи находок "
        "с одной причиной.", a0=len(parked), a1=removed))
    return kept


# Что имеет смысл говорить о странице, закрытой от индекса: само закрытие и
# то, что касается связей с другими страницами.
KEEP_ON_CLOSED = {"noindex", "canonical-elsewhere", "nosnippet", "stale-closed",
                  "translations-parked"}


def drop_closed_noise(issues: list, pages: list) -> list:
    """
    Убирает находки о содержимом страниц, закрытых от индекса.

    mdBook кладёт в каждый сайт `print.html` и `toc.html` с noindex, и обе
    получали «нет title», «тонкая», «нет description». Закрытая страница в
    выдаче не появится: её заголовок, объём и первый абзац никому не видны.
    Остаются само закрытие и находки hreflang — они про связи, а не про текст.
    """
    closed = {p.url for p in pages if p.noindex}
    if not closed:
        return issues
    return [i for i in issues if i[1] not in closed or i[2] in KEEP_ON_CLOSED
            or i[2].startswith("hreflang-")]


def validate_config(cfg: dict) -> list:
    """
    Пороги, вписанные руками: либо действуют, либо названы.

    Ключ с опечаткой раньше молча не действовал, число строкой роняло прогон
    трейсбеком, а `near_duplicate: 80` вместо `0.8` тихо выключало находку.
    Возвращает заметки о незнакомых ключах; на невозможные значения отвечает
    ошибкой со словами.
    """
    import difflib
    notes = []
    for key, value in (cfg or {}).items():
        if key.startswith("_"):
            continue
        if key not in CONFIG:
            close = difflib.get_close_matches(key, list(CONFIG), n=1, cutoff=0.7)
            notes.append(tr("настройка «{a0}» мне не знакома и не действует", a0=key)
                         + (tr(" — возможно, имелось в виду «{a0}»", a0=close[0]) if close else ""))
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SourceError(tr("настройка «{a0}» должна быть числом, а в конфиге стоит {a1}",
                                 a0=key, a1=json.dumps(value, ensure_ascii=False)))
    merged = {**CONFIG, **{k: v for k, v in (cfg or {}).items() if k in CONFIG}}

    def need(ok, key, rule):
        if not ok:
            raise SourceError(tr("настройка «{a0}» = {a1}: {a2}", a0=key, a1=merged[key], a2=rule))

    for key in ("near_duplicate", "similar", "boilerplate_share", "unique_share_min",
                "slot_share", "slot_floor"):
        need(0 < merged[key] <= 1, key, tr("нужна доля от 0 до 1 — например 0.8, а не 80"))
    need(merged["similar"] <= merged["near_duplicate"], "similar",
         tr("порог «похожих» не может быть выше порога почти-дублей"))
    for key in ("shingle_size", "minhash_perms", "lsh_bands", "thin_words",
                "boilerplate_min_pages", "max_click_depth", "title_min", "description_min"):
        need(merged[key] >= 1, key, tr("нужно целое число не меньше 1"))
    need(merged["lsh_bands"] <= merged["minhash_perms"], "lsh_bands",
         tr("полос не может быть больше, чем перестановок (minhash_perms)"))
    need(merged["title_min"] < merged["title_max"], "title_max",
         tr("верхняя граница должна быть больше нижней"))
    need(merged["description_min"] < merged["description_max"], "description_max",
         tr("верхняя граница должна быть больше нижней"))
    return notes


def run_all(pages: list, home_url: str = None, cfg: dict = None,
            language: str = "") -> dict:
    """Единая точка входа: всё, что считается локально, без сети."""
    unknown = validate_config(cfg)
    cfg = {**CONFIG, **(cfg or {})}
    graph = link_graph(pages, home_url)
    words = trimmed_words(pages)
    boiler = boilerplate_profile(pages, cfg, words)
    dupes = find_near_duplicates(pages, cfg, words)
    shells = {p.url for p in pages if is_shell(p, cfg)}
    # Страница из одного заголовка — тонкая, и об этом сказано. Сравнивать её с
    # другой такой же и сообщать «100% дубль» и «0% уникального» — та же
    # находка ещё дважды: сравнивать там нечего.
    bare = shells | {p.url for p in pages if text_volume(p) < 25}
    multi = hreflang.check(pages, cfg)
    issues_hreflang = multi["issues"]
    # Пары «один язык, разные страны» законно похожи почти дословно.
    # Совет «поставь canonical» убил бы региональную версию, поэтому такие
    # пары не идут в дубли вовсе.
    regional = {tuple(sorted(pair)) for pair in multi["regional_pairs"]}
    issues = technical_issues(pages, cfg, language, shells=shells)
    issues += issues_hreflang
    notes = list(dupes["notes"]) + list(multi["notes"]) + unknown
    for url in sorted(shells):
        issues.append(("critical", url, "js-shell",
                       tr("в исходном HTML нет текста — его рисует JavaScript, а краулеры ИИ-поиска его не исполняют")))
    if shells:
        share = len(shells) / len(pages) if pages else 0
        notes.append(
            tr("пустых JS-каркасов: {a0} из {a1} ({a2:.0%}). На этих страницах не считались объём текста, уникальность, дубли и ссылки — в исходном HTML их неоткуда взять. Это одна беда, а не четыре: появится серверный HTML — проверки заработают.", a0=len(shells), a1=len(pages), a2=share))
    if boiler["skipped"]:
        notes.append(tr("шаблонность не оценивалась: ") + boiler["skipped"])
    mismatch = root_mismatch(pages, graph)
    if mismatch:
        notes.append(mismatch)
    if graph.get("home_redirected_from"):
        notes.append(tr(
            "главная {a0} — заглушка-редирект на {a1}. Глубина клика и "
            "недостижимость считаются от {a1}: из самой заглушки ссылок нет, "
            "и без этого весь сайт выглядел бы недостижимым.",
            a0=graph["home_redirected_from"], a1=graph["home"]))
    if graph.get("only_hreflang"):
        notes.append(tr(
            "{a0} страниц(ы) связаны с остальным сайтом только через hreflang: ссылок "
            "<a> на них с других языковых версий нет (так устроен переключатель "
            "языков в виде списка). Поисковик их находит, поэтому недостижимыми они "
            "не считаются; человеку без переключателя туда не попасть.",
            a0=len(graph["only_hreflang"])))
    if graph["home_missing"]:
        notes.append(
            tr("главной страницы нет среди разобранных файлов, поэтому глубина клика и недостижимость не считались. Проверь --site и корень каталога."))

    for url, share in sorted(boiler["shares"].items()):
        if share < cfg["unique_share_min"] and url not in bare:
            issues.append(("critical", url, "low-uniqueness",
                           tr("только {a0:.0%} текста уникально — остальное шаблон", a0=share)))
    # Ссылки нужны странице, чтобы её нашли и проиндексировали. Закрытой от
    # индекса они ни к чему: «сирота» и «недостижима» на ней — следствие
    # решения её закрыть, а не отдельная беда. Сама находка noindex остаётся.
    # `robots: none` закрывает так же, как noindex.
    closed = {p.url for p in pages if p.noindex}
    # Заглушка-редирект и пустая оболочка тоже не сироты. Список чистится
    # один раз и здесь: раньше консоль, карточка в отчёте и JSON считали
    # каждый по-своему и показывали 0, 3 и 3 для одного и того же сайта.
    spared = closed | shells | {p.url for p in pages if redirect_target(p)}
    graph["orphans"] = [u for u in graph["orphans"] if u not in spared]
    orphaned = set(graph["orphans"])
    graph["unreachable"] = [u for u in graph["unreachable"]
                            if u not in spared and u not in orphaned]
    for url in graph["orphans"]:
        issues.append(("critical", url, "orphan",
                       tr("ни одна внутренняя ссылка не ведёт на страницу")))
    for url in graph["unreachable"]:
        issues.append(("critical", url, "unreachable",
                       tr("до страницы нельзя дойти от главной по ссылкам")))
    for url, d in sorted(graph["depth"].items()):
        if url in shells or url in closed:
            continue
        if d > cfg["max_click_depth"]:
            issues.append(("warning", url, "deep",
                           tr("{a0} кликов от главной — краулер доходит редко", a0=d)))

    # Одна находка на страницу, а не на пару: двести одинаковых страниц дают
    # 19 900 пар, и блок «чинить в этом порядке» сообщал «19 900 near-duplicate».
    partners = defaultdict(list)
    regional_shown = 0
    for a, b, j in dupes["pairs"]:
        if tuple(sorted((a.url, b.url))) in regional:
            regional_shown += 1
            continue
        partners[a.url].append((j, b.url))
        partners[b.url].append((j, a.url))
    if regional_shown:
        notes.append(tr("{a0} пар(ы) не попали в дубли: это версии одной "
                        "страницы для разных стран на одном языке, связанные "
                        "hreflang. Для них canonical — ошибка.",
                        a0=regional_shown))
    for url in sorted(partners):
        if url in bare:
            continue
        found = sorted(partners[url], reverse=True)
        best, other = found[0]
        more = tr(" и ещё {a0}", a0=len(found) - 1) if len(found) > 1 else ""
        if best >= cfg["near_duplicate"]:
            issues.append(("critical", url, "near-duplicate",
                           tr("совпадает на {a0:.0%} со страницей {a1}{a2} — поисковик оставит в индексе одну", a0=best, a1=other, a2=more)))
        else:
            issues.append(("info", url, "similar",
                           tr("похожа на {a0:.0%} на {a1}{a2}", a0=best, a1=other, a2=more)))

    # Дубли живут группами, а не парами. На живом каталоге виз 588 страниц
    # с кодом `near-duplicate` оказались 62 группами одинаковых по смыслу
    # страновых гайдов: «переписать 588 страниц» — приговор, «развести 62 темы»
    # — задача. Поэтому счёт групп говорится вслух.
    groups = _clusters([(a.url, b.url) for a, b, j in dupes["pairs"]
                        if j >= cfg["near_duplicate"] and a.url not in bare
                        and b.url not in bare
                        and tuple(sorted((a.url, b.url))) not in regional])
    if groups:
        biggest = max(len(g) for g in groups)
        notes.append(
            tr("почти-дубли образуют {a0} групп(ы), в самой большой {a1} страниц. Чинится по группам: одна остаётся, остальные переписываются под другой интент или отдают ей canonical.", a0=len(groups), a1=biggest))

    # Две пустые оболочки совпадают на 100% — и это ничего не значит.
    # Пока они оставались в `duplicates`, счётчик «похожих пар» показывал
    # сотни находок там, где находка ровно одна: пустой HTML.
    pairs = [(a, b, j) for a, b, j in dupes["pairs"]
             if a.url not in bare and b.url not in bare]

    # Заглушка-редирект — не страница: человек и поисковик видят то, куда она
    # ведёт. На каталоге виз девять языковых `/connect` и корень давали 40
    # находок «нет title», «JS-оболочка», «canonical на другую» о страницах,
    # которые живой сайт отдаёт кодом 307.
    stubs = {p.url for p in pages if redirect_target(p)}
    if stubs:
        issues = [i for i in issues if i[1] not in stubs]
        notes.append(tr(
            "заглушек-редиректов: {a0}. Как страницы они не проверялись — "
            "поисковик видит то, куда они ведут.", a0=len(stubs)))

    issues = _collapse_parked(issues, notes, pages, cfg)
    issues = drop_closed_noise(issues, pages)

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
