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

import functools
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict, deque

from . import hreflang
from .core import EMPTY_MOUNT, INERT, NOT_LIVE, SourceError, drop_spans, is_dense
from .core import ALWAYS_SKIP, tokenize, url_key
from urllib.parse import urlsplit
from .publish import indexable
from .settings import display_width, text_volume
from .i18n import tr
from .subject import Said

# ── настройки, которые имеет смысл крутить под свой проект ────────────────────
CONFIG = {
    "shingle_size": 5,          # длина словесной n-граммы
    "minhash_perms": 32,        # чем больше, тем точнее оценка и медленнее счёт
    "lsh_bands": 8,             # bands * rows == minhash_perms
    "exact_below": 400,         # столько страниц сравниваем попарно и точно
    "near_duplicate": 0.80,     # Jaccard, выше которого пара — почти-дубль
    "similar": 0.55,            # ниже дубля, но уже повод посмотреть
    # Шаблон у порога: столько страниц одного шаблона совпадают между собой
    # не ниже чем на near_duplicate − duplicate_risk_margin.
    "duplicate_risk_margin": 0.05,
    "duplicate_risk_pages": 5,
    "thin_words": 250,          # меньше слов — тонкая страница
    "boilerplate_share": 0.90,  # биграмма в этой доле страниц считается шаблонной
    "boilerplate_min_pages": 8, # меньше — статистики нет, вердикта не будет
    # Подставленные значения шаблона: пара страниц считается одним текстом,
    # если различающихся слов у каждой не больше этого числа или этой доли.
    "slot_words": 6,
    "slot_share": 0.04,
    # Доля вхождений, а не словаря: у страницы-клона подставленные значения
    # (город, штат, пять чисел, три соседних города) занимают несколько
    # процентов текста, у разных статей разное — десятки процентов.
    "slot_token_share": 0.12,
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


_WORD_IDS = {}


def _word_ids(words: list) -> list:
    """
    Слово -> 64-битное число, детерминированно (blake2b), по разу на слово.
    Хэш `hash(str)` здесь нельзя: он меняется от запуска к запуску.
    """
    ids = _WORD_IDS
    out = list(map(ids.get, words))
    if None in out:
        for i, v in enumerate(out):
            if v is None:
                w = words[i]
                v = ids.get(w)
                if v is None:
                    v = ids[w] = int.from_bytes(
                        hashlib.blake2b(w.encode("utf-8"), digest_size=8).digest(), "little")
                out[i] = v
    return out


def _shingles(words: list, k: int) -> set:
    # Шингл — хэш кортежа чисел. hash() кортежа из int не зависит от
    # PYTHONHASHSEED, а считается в C: втрое быстрее blake2b на каждый шингл.
    if not words:
        return set()
    ids = _word_ids(words)
    if len(ids) < k:
        return {hash(tuple(ids))}
    return set(map(hash, zip(*(ids[i:] for i in range(k)))))


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

    def shingle_set(url):
        own = words.get(url, [])
        # У иероглифики слово — один знак: пять знаков подряд совпадают у любых
        # двух текстов на одну тему. Шингл берётся вдвое длиннее.
        return _shingles(own, k * 2 if is_dense(own) else k)

    urls = sorted({p.url for p in pages if words.get(p.url)})
    if len(urls) < 2:
        return {"pairs": [], "notes": notes, "method": tr("нет данных"), "method_id": "none",
                "sampled_urls": frozenset()}

    if len(urls) <= cfg["exact_below"]:
        method, method_id = tr("попарное сравнение"), "pairwise"
        sampled = set()
        shingles = {u: shingle_set(u) for u in urls}
        get = shingles.__getitem__
        candidates = [(urls[i], urls[j])
                      for i in range(len(urls)) for j in range(i + 1, len(urls))]
    else:
        method, method_id = "LSH", "lsh"
        perms, bands = cfg["minhash_perms"], cfg["lsh_bands"]
        rows = max(1, perms // bands)
        # Множества шинглов всех страниц разом не держатся: на 50 000 страниц
        # это восемь гигабайт. Подпись считается потоком, а множества
        # пересобираются только для пар-кандидатов.
        signatures = {u: _minhash(shingle_set(u), perms) for u in urls}
        get = functools.lru_cache(maxsize=4096)(shingle_set)
        buckets = defaultdict(list)
        for url in urls:
            sig = signatures[url]
            for b in range(bands):
                band = sig[b * rows:(b + 1) * rows]
                key = (b, hashlib.blake2b(repr(band).encode(), digest_size=8).digest())
                buckets[key].append(url)
        # Клоны шаблона с подставленным городом совпадают по шинглам на 0,6:
        # каждое вхождение города портит k соседних шинглов, и полосы ловили
        # такую пару через раз — попарно находились все, а после 400 страниц
        # треть пропадала. Словарь у них почти один и тот же, поэтому
        # кандидатов дают и полосы по множеству слов — длинные, чтобы разные
        # тексты на одну тему кандидатами не становились. Проверка пары та же.
        # Четырёх полос мало: у клона с тридцатью подстановками словарь
        # совпадает на 0,85, и пара становилась кандидатом в трёх случаях из
        # четырёх — пары и тройки клонов пропадали целиком. Подпись словаря
        # считается за один проход, поэтому полос шестнадцать, а строк в
        # полосе на две больше, чтобы случайных кандидатов прибавилось меньше.
        word_rows = min(perms, max(rows * 2 + 2, 1))
        word_perms = word_rows * 16
        for url in urls:
            own = words.get(url, [])
            sig = _minhash(_shingles(own, 1), word_perms)
            for b in range(word_perms // word_rows):
                band = sig[b * word_rows:(b + 1) * word_rows]
                key = ("w", b, hashlib.blake2b(repr(band).encode(), digest_size=8).digest())
                buckets[key].append(url)

        cap = 200
        candidate_set = set()
        # Пары «образец — остальные» из переполненной корзины: предмет такой
        # находки — образец, а он зависит от того, какой адрес первым по
        # алфавиту. Удалили одну страницу — у тысячи сменился «близнец».
        sampled = set()
        overflow = set()
        for bucket in buckets.values():
            if len(bucket) < 2:
                continue
            if len(bucket) <= cap:
                for i in range(len(bucket)):
                    for j in range(i + 1, len(bucket)):
                        candidate_set.add((bucket[i], bucket[j]))
            else:
                # Одна группа попадает в корзину каждой полосы: разбираем
                # группу, а не полосу.
                overflow.add(tuple(bucket))
        if overflow:
            # Переполненная корзина — не обязательно кластер одинаковых
            # страниц: полосы по множеству слов собирают в одну корзину
            # всё, что написано одним словарём. Сравнение «все с образцом»
            # теряло в такой корзине настоящие пары клонов. Корзина
            # разбирается ещё раз — по полосам из пар слов: подстановка
            # портит две пары, а не пять шинглов, и клоны совпадают на 0,85,
            # тогда как разные тексты одного словаря — на десятые доли.
            pair_sig = {}

            def pair_signature(url):
                if url not in pair_sig:
                    own = words.get(url, [])
                    pair_sig[url] = _minhash(_shingles(own, 4 if is_dense(own) else 2), perms)
                return pair_sig[url]

            for bucket in sorted(overflow):
                sub = defaultdict(list)
                for url in bucket:
                    sig = pair_signature(url)
                    for b in range(bands):
                        band = sig[b * rows:(b + 1) * rows]
                        sub[(b, hashlib.blake2b(repr(band).encode(), digest_size=8).digest())].append(url)
                for part in sub.values():
                    if len(part) < 2:
                        continue
                    if len(part) <= cap:
                        for i in range(len(part)):
                            for j in range(i + 1, len(part)):
                                candidate_set.add((part[i], part[j]))
                        continue
                    # А такая корзина — уже кластер почти одинаковых страниц.
                    # Полный перебор внутри неё квадратичен, поэтому
                    # сравниваем всех с образцом.
                    rep = part[0]
                    for other in part[1:]:
                        candidate_set.add((rep, other))
                        sampled.add((rep, other))
        candidates = sorted(candidate_set)

    by_url = {p.url: p for p in pages}
    vocab = functools.lru_cache(maxsize=4096)(lambda url: frozenset(words.get(url, ())))
    out = []
    for a, b in candidates:
        sa, sb = get(a), get(b)
        # |A ∪ B| = |A| + |B| - |A ∩ B|: объединение не строится — на
        # кластере похожих страниц это сотни тысяч лишних множеств.
        inter = len(sa & sb) if len(sa) <= len(sb) else len(sb & sa)
        union = len(sa) + len(sb) - inter
        if not union:
            continue
        j = inter / union
        # Дорвей, где город стоит через каждые пять слов, портит все шинглы:
        # сходство 0,1, и худшие клоны не перепроверялись вовсе. Ниже порога
        # пару перепроверяем, только если словарь почти тот же.
        if (cfg["slot_floor"] <= j < cfg["near_duplicate"]
                or j < cfg["slot_floor"] and _few_differ(vocab(a), vocab(b), cfg)):
            j = max(j, _without_slots(words.get(a, []), words.get(b, []), k, cfg,
                                      _anchor_words(by_url[a]), _anchor_words(by_url[b])))
        if j >= cfg["similar"]:
            out.append((by_url[a], by_url[b], round(j, 3)))
    out.sort(key=lambda t: (-t[2], t[0].url, t[1].url))
    # Заметка — о группах, где сравнение с образцом действительно нашло
    # похожие страницы. Корзина, переполненная словарём, а не сходством,
    # ничего не утверждает: «группы оказались похожи» при нуле пар — неправда.
    found = [(a.url, b.url) for a, b, _ in out if (a.url, b.url) in sampled]
    groups = _clusters(found)
    if groups:
        notes.append(
            tr("{a0} групп(ы) страниц оказались настолько похожи, что сравнивались с образцом группы, а не попарно — иначе счёт занял бы часы. Пары внутри такой группы показаны не все.", a0=len(groups)))
    # `method_id` — для машин: `method` переведён и на другом языке другой.
    # `sampled_urls` — страницы, чей «близнец» — образец группы: их предмет
    # зависит от выборки, а не от сайта.
    return {"pairs": out, "notes": notes, "method": method, "method_id": method_id,
            "sampled_urls": frozenset(u for pair in found for u in pair)}


def _slot_pattern(a: str, b: str) -> str:
    """
    `/en/visa/alpha/fees` и `/en/visa/beta/fees` — один шаблон
    `/en/visa/*/fees`: пути одной длины, различие ровно в одном сегменте.
    Иначе пустая строка.
    """
    pa = urlsplit(a).path.strip("/").split("/")
    pb = urlsplit(b).path.strip("/").split("/")
    if len(pa) != len(pb):
        return ""
    diff = [i for i, (x, y) in enumerate(zip(pa, pb)) if x != y]
    if len(diff) != 1:
        return ""
    pa[diff[0]] = "*"
    return "/" + "/".join(pa) + "/"


def duplicate_risk(pairs, cfg: dict, skip=frozenset()) -> list:
    """
    Шаблон, который вот-вот станет дублем.

    Порог почти-дубля — резкий: страницы шаблона на 78% одинаковы — это
    двести сведений «похожа», а на 80% — сотня критичных. На живом каталоге
    одна правка общего текста перевела так девять страниц разом, а ещё
    девяносто одна стояла в двух процентах от порога, размазанная по
    сведениям. Одна находка на шаблон говорит это вслух до того, как случится.
    """
    top = cfg["near_duplicate"]
    low = top - cfg.get("duplicate_risk_margin", 0.05)
    need = cfg.get("duplicate_risk_pages", 5)
    groups = defaultdict(lambda: {"pages": set(), "worst": 0.0, "crossed": set()})
    for a, b, j in pairs:
        if j < low or a.url in skip or b.url in skip:
            continue
        pattern = _slot_pattern(a.url, b.url)
        if not pattern:
            continue
        g = groups[pattern]
        if j >= top:
            g["crossed"] |= {a.url, b.url}
            continue
        g["pages"] |= {a.url, b.url}
        g["worst"] = max(g["worst"], j)
    out = []
    for pattern in sorted(groups):
        g = groups[pattern]
        near = g["pages"] - g["crossed"]
        if len(near) < need:
            continue
        message = tr(
            "шаблон {a0}: {a1} страниц(ы) совпадают между собой до {a2:.0%} при пороге "
            "почти-дубля {a3:.0%}. Одна правка общего текста — и они станут критичными "
            "дублями. Разведи их своими данными, пока это сведения",
            # Вниз, а не к ближайшему: 79,6% «до 80% при пороге 80%» звучало
            # как уже перешедшая граница.
            a0=pattern, a1=len(near), a2=math.floor(g["worst"] * 100) / 100, a3=top)
        if g["crossed"]:
            message += " " + tr("{a0} страниц(ы) этого шаблона порог уже перешли.",
                                a0=len(g["crossed"]))
        out.append(("warning", pattern, "duplicate-risk",
                    Said(message, sorted(url_key(u) for u in near))))
    return out


def _anchor_words(page) -> set:
    """Слова из текстов ссылок страницы: «соседние города» — тоже подстановка."""
    return {w.lower() for a in (getattr(page, "anchors", None) or ()) for w in tokenize(a)}


def _short_runs(words: list, differing: set, longest: int = 6, linked: set = frozenset()) -> bool:
    run = 0
    for word in words:
        # Слово из текста ссылки не удлиняет кусок своего текста: список
        # «Nearby: Round Rock, Cedar Park, Pflugerville» — пять подставленных
        # слов подряд, и все они — анкоры ссылок на соседние страницы строки.
        run = run + 1 if word in differing and word not in linked else 0
        if run > longest:
            return False
    return True


def _masked(words: list, slot: set) -> list:
    """
    Слова подстановки — меткой; несколько подряд — одной. Одно общее слово
    между ними — часть того же значения: «Ростове-на-Дону» против «Уфе».
    """
    out = []
    for i, w in enumerate(words):
        if w in slot:
            if out and out[-1] == "\x00":
                continue
            w = "\x00"
        elif out and out[-1] == "\x00" and i + 1 < len(words) and words[i + 1] in slot:
            continue
        out.append(w)
    return out


def _few_differ(va: frozenset, vb: frozenset, cfg: dict) -> bool:
    """
    Различаются ли словари двух страниц лишь несколькими словами — при том,
    что общих слов много: две страницы из одного заголовка различаются одним
    словом, но общего текста, в котором стоит подстановка, у них нет.
    """
    limit = max(cfg["slot_words"], int(min(len(va), len(vb)) * cfg["slot_share"]))
    if abs(len(va) - len(vb)) > limit or min(len(va), len(vb)) < 5 * limit:
        return False
    # Счёт с ранним выходом: у разных страниц лишнее слово находится сразу,
    # а пар на четыреста страниц — восемьдесят тысяч.
    for one, other in ((va, vb), (vb, va)):
        extra = 0
        for w in one:
            if w not in other:
                extra += 1
                if extra > limit:
                    return False
    return True


def _without_slots(a: list, b: list, k: int, cfg: dict,
                   linked_a: set = frozenset(), linked_b: set = frozenset()) -> float:
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
    if not (only_a or only_b) or not a or not b:
        return 0.0
    limit = max(cfg["slot_words"], int(min(len(va), len(vb)) * cfg["slot_share"]))
    few_words = len(only_a) <= limit and len(only_b) <= limit
    # Блок фактов и блок «соседние города» дают двенадцать-пятнадцать разных
    # слов — больше порога словаря, — хотя текст тот же. Мерим и долю вхождений.
    # Подстановка — короткая вставка: город, число, «Round Rock». Семь разных
    # слов подряд — уже свой текст, а не подставленное значение.
    share = cfg.get("slot_token_share", CONFIG["slot_token_share"])
    rare = (_short_runs(a, only_a, linked=linked_a) and _short_runs(b, only_b, linked=linked_b)
            and sum(1 for w in a if w in only_a) <= len(a) * share
            and sum(1 for w in b if w in only_b) <= len(b) * share)
    if not (few_words or rare):
        return 0.0
    k = k * 2 if is_dense(a) else k
    # Подстановка разной длины — «Austin» и «St. Louis» — одна метка, а не
    # одна и две: иначе каждый шингл через «St. Louis» не совпадал с парным.
    sa = _shingles(_masked(a, only_a), k)
    sb = _shingles(_masked(b, only_b), k)
    inter = len(sa & sb)
    union = len(sa) + len(sb) - inter
    return inter / union if union else 0.0


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
    # Списки не копируются: их никто не меняет, а копия — ещё одно слово на
    # каждое слово сайта (на 3 000 страниц по 70 КБ — 280 МБ пика).
    words = {p.url: p.words for p in pages}
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
    # Общее у девяти страниц из десяти — не всегда шапка и подвал. Когда один
    # шаблон занимает 90% сайта, общим становится и его неизменный текст, и он
    # отрезался как подвал: пятьдесят клонов теряли половину слов и выходили
    # «похожими», а стоило добавить пять постов блога — «дублями».
    if head:
        head = _site_frame(head, [p for p in plain if words[p.url][:len(head)] == head],
                           pages, False)
    if tail:
        tail = _site_frame(tail, [p for p in plain if words[p.url][-len(tail):] == tail],
                           pages, True)
    if not head and not tail:
        return words
    for p in plain:
        w = words[p.url]
        if head and w[:len(head)] == head:
            w = w[len(head):]
        if tail and w[-len(tail):] == tail:
            w = w[:-len(tail)]
        words[p.url] = w
    return words


def _template_group(page) -> tuple:
    """Каталог страницы внутри языка; главная языка — своя группа."""
    _, lang, rest = _locale_split(page.url)
    if not rest:
        return lang, None
    return lang, rest.rsplit("/", 1)[0] if "/" in rest else ""


def _site_frame(run: list, bearers: list, pages: list, at_end: bool) -> list:
    """
    Часть общего начала или конца `run`, которая — обвязка сайта, а не текст
    шаблона.

    Обвязка сайта стоит и вне шаблона: на главной, «О нас», в другом разделе —
    у страницы без `<main>` в тексте, у страницы с `<main>` вокруг него. Или
    она размечена: `<header>`, `<footer>`, `<nav>`, `<aside>`, или состоит из
    текстов ссылок. Что общее только у страниц одного каталога и ничем таким
    не отмечено, — текст шаблона, и сравнивать страницы надо вместе с ним.
    Если вне каталога шаблона страниц нет вовсе, сравнить не с чем, и общее
    по-прежнему считается обвязкой: молчать безопаснее, чем ошибиться.
    """
    if not bearers:
        return run
    home = Counter(_template_group(p) for p in bearers).most_common(1)[0][0]
    outside = [p for p in pages if _template_group(p) != home]
    if not outside:
        return run
    seq = run[::-1] if at_end else run         # от края страницы внутрь
    size = len(seq)
    support = 0
    for p in outside[:2000]:
        own = tokenize(p.chrome) if p.chrome else p.words
        n, limit = 0, min(size, len(own))
        if at_end:
            while n < limit and own[-1 - n] == seq[n]:
                n += 1
        else:
            while n < limit and own[n] == seq[n]:
                n += 1
        support = max(support, n)
        if support == size:
            return run
    # Дальше — только разметка и ссылки. Слово считается служебным, если оно
    # такое у половины страниц шаблона: одна ссылка в тексте не решает.
    sample = bearers[:20]
    votes = Counter()
    for p in sample:
        votes.update(set(tokenize(getattr(p, "framed", "") or "")) | _anchor_words(p))
    marked = {w for w, c in votes.items() if c * 2 >= len(sample)}
    keep = support
    hits = 0
    for i, word in enumerate(seq[support:], 1):
        if word in marked:
            hits += 1
            if hits >= 0.8 * i:
                keep = support + i
    if keep == size:
        return run
    return run[size - keep:] if at_end else run[:keep]


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
        # Пара слов кортежем: слова интернированы, и кортеж из двух ссылок
        # дешевле строки «a b», а смысл тот же — пробела в слове не бывает.
        return list(zip(seq, seq[1:]))

    # Шаблон свой у каждого языка. Если считать фразы по всем страницам сразу,
    # на сайте из двух языков ни одна не встретится «в 90% страниц» — и
    # проверка молчала именно там, где шаблонов больше одного: шестьсот
    # страниц одного шаблона давали шестьсот находок, дважды по триста — ноль.
    cohorts = defaultdict(list)
    for p in pages:
        cohorts[_cohort(p)].append(p)

    def measure(members):
        # Порог не может требовать «на всех страницах»: при девяти страницах
        # ceil(9*0.9) давал ровно 9, шаблон переставал находиться, и добавление
        # десятой страницы переворачивало вердикт с «всё чисто» на «10 критичных».
        threshold = max(2, min(len(members) - 1,
                               math.ceil(len(members) * cfg["boilerplate_share"])))
        # Частоты всех фраз сайта не держатся: общая фраза стоит хотя бы на
        # одной из первых (n - порог + 1) страниц — иначе её нет как минимум
        # на n - порог + 1 страницах, и до порога она не дотянет. Считаем
        # только фразы этих страниц, а безнадёжные выбрасываем по дороге.
        # Результат тот же, что у полного подсчёта.
        n = len(members)
        seed = n - threshold + 1
        df = Counter()
        for p in members[:seed]:
            df.update(set(bigrams(words.get(p.url, []))))
        for i, p in enumerate(members[seed:], seed + 1):
            for g in set(bigrams(words.get(p.url, []))):
                if g in df:
                    df[g] += 1
            if i % 256 == 0:
                left = n - i
                df = Counter({g: c for g, c in df.items() if c + left >= threshold})
        common = {g for g, c in df.items() if c >= threshold}
        del df
        out = {}
        for p in members:
            grams = bigrams(words.get(p.url, []))
            if not grams:
                out[p.url] = 0.0
                continue
            unique = sum(1 for g in grams if g not in common)
            out[p.url] = round(unique / len(grams), 3)
        return out

    shares, small = {}, 0
    for members in cohorts.values():
        if len(members) < cfg["boilerplate_min_pages"]:
            small += len(members)
            continue
        shares.update(measure(members))
        # Шаблон бывает и у раздела: двадцать карточек /items/ одного шаблона
        # рядом с блогом не дотягивают до 90% страниц языка, и стоило добавить
        # два поста, как шаблон переставал находиться вовсе. Раздел меряется
        # так же, как язык, и у страницы остаётся меньшая доля.
        sections = defaultdict(list)
        for p in members:
            rest = _locale_split(p.url)[2]
            if "/" in rest:
                sections[rest.split("/", 1)[0]].append(p)
            elif rest:
                # Плоские адреса (`/rent-town-1/`): раздел — первое слово адреса.
                head = [t for t in re.split(r"[-_.]+", rest.lower()) if t]
                if len(head) > 1:
                    sections[("-", head[0])].append(p)
        for part in sections.values():
            if cfg["boilerplate_min_pages"] <= len(part) < len(members):
                for url, share in measure(part).items():
                    shares[url] = min(shares[url], share)
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
# Кавычки у атрибута необязательны: минификатор HTML пишет
# `content=0;url=/en/`, и главная-заглушка не узнавалась.
# `url=` по спецификации HTML необязателен: `content="0; /path/"` браузер
# тоже исполняет как переадресацию.
_REFRESH_CONTENT = re.compile(
    r"(?<![-\w])content\s*=\s*[\"']?\s*(\d+(?:\.\d+)?)\s*[;,]\s*(?:url\s*=\s*)?['\"]?"
    r"([^\"'\s>]+)", re.I)
# Заглушка на одном скрипте: весь <script> — это `location.replace("/x/")`
# (`assign`) или `window.location.href = "/x/"`, и ничего больше. Условный переход
# внутри приложения (`if (!user) location.href = …`) сюда не попадает.
_JS_REDIRECT = re.compile(
    r"^\s*(?:(?:window|self|top|document)\.)?location"
    r"(?:\.(?:replace|assign)\(\s*([\"'])([^\"'\s]+)\1\s*\)|(?:\.href)?\s*=\s*([\"'])([^\"'\s]+)\3)"
    r"\s*;?\s*$")
# RSC-поток Next.js с ошибкой-редиректом (`"digest":"NEXT_REDIRECT;…"`):
# redirect() сработал при отрисовке, и шапка с подвалом вокруг пустого
# <main> — не содержание страницы.
_NEXT_DIGEST = re.compile(r'digest\\*"\s*:\s*\\*"NEXT_REDIRECT;')
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
    few_words = len((getattr(page, "text", "") or "").split()) < 30
    by_script = "NEXT_REDIRECT" in raw and (few_words or bool(_NEXT_DIGEST.search(raw)))
    by_js = few_words and "location" in raw
    # Подстрока ищется на порядок быстрее выражения без учёта регистра, а на
    # большинстве страниц `http-equiv` нет вовсе.
    # `equiv` и `EQUIV` покрывают и `HTTP-equiv`: раньше смешанный регистр
    # пропускался, и редирект не узнавался.
    by_meta = (("equiv" in raw or "EQUIV" in raw or "Equiv" in raw)
               and bool(_REFRESH.search(raw)))
    if not by_script and not by_meta and not by_js:
        return ""
    live = drop_spans(raw, NOT_LIVE)
    if by_meta:
        for tag in _META_TAG.findall(drop_spans(live, INERT)):
            if not _REFRESH.search(tag):
                continue
            found = _REFRESH_CONTENT.search(tag)
            if found and float(found.group(1)) <= 1:
                target = urljoin(page.url, found.group(2).strip())
                # Переадресация на себя — не заглушка, а страница, которая
                # перезагружается: её содержимое и есть то, что видит поисковик.
                if url_key(target) != url_key(page.url):
                    return target
    if by_script:
        for script in _SCRIPT.findall(live):
            found = _NEXT_REDIRECT.search(script)
            if found and (few_words or _NEXT_DIGEST.search(script)):
                return urljoin(page.url, found.group(1).strip())
    if by_js:
        for script in _SCRIPT.findall(live):
            found = _JS_REDIRECT.match(script)
            if found:
                target = urljoin(page.url, (found.group(2) or found.group(4)).strip())
                if url_key(target) != url_key(page.url):
                    return target
    return ""


def link_graph(pages: list, home_url: str = None, blocked: set = frozenset()) -> dict:
    """
    Строит граф внутренних ссылок и считает то, что влияет на индексацию:
    входящие, исходящие, глубина клика от главной, сироты и тупики.

    Главная задаётся явно (из --site). Раньше за неё брался самый короткий URL,
    и на каталоге без главной 11 страниц из 12 объявлялись недостижимыми —
    катастрофа, которой нет. Если главной среди страниц нет, глубина
    не считается вовсе, и об этом сообщается.

    `blocked` — страницы, закрытые в robots.txt: поисковик их не читает, и
    ссылки с них никуда не ведут. Страница, до которой доходят только через
    них, попадает в `behind_robots`.
    """
    by_key = {p.key: p.url for p in pages}
    inbound = defaultdict(set)
    outbound = {}
    # Ссылки страницы с `<meta name="robots" content="nofollow">` (или `none`)
    # краулер не проходит, как и `rel="nofollow"` у одной ссылки. Входящими
    # они остаются — ссылка есть, — но глубину и достижимость через них не
    # считаем. Редирект заглушки — не ссылка, и он остаётся.
    followed = {}
    nofollow = set()
    by_hreflang = defaultdict(set)
    unresolved = set()
    unresolved_from = defaultdict(set)
    unresolved_dirs = set()
    soft = defaultdict(set)
    soft_inbound = set()
    landing_of = {}
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
                unresolved_from[p.url].add(key)
                if urlsplit(link).path.endswith("/"):
                    unresolved_dirs.add(key)
        # Заглушка-редирект ведёт туда, куда перебрасывает, — хотя ссылки <a>
        # в ней нет. Алиасы Hugo так и устроены, и всё за ними считалось
        # недостижимым.
        raw_landing = redirect_target(p)
        landing = (by_key.get(url_key(raw_landing))
                   or by_key.get(url_key(raw_landing).split("?", 1)[0])) if raw_landing else None
        if landing and landing != p.url:
            targets.add(landing)
            landing_of[p.url] = landing
        elif raw_landing and not landing:
            # Заглушка ведёт на страницу, которой в сборке нет: на живом сайте
            # это 404 за редиректом. Ссылкой <a> её могли и не продублировать.
            key = url_key(raw_landing)
            if key and urlsplit(key).netloc == urlsplit(url_key(p.url)).netloc:
                unresolved.add(key)
                unresolved_from[p.url].add(key)
        # `rel="nofollow"` у ссылки: входящей она остаётся — страница не
        # сирота, — но по ней не идут. Битая такая ссылка — 404 для человека;
        # из корня сайта она обычно ведёт на /login или /cart, которых в
        # статической сборке нет, поэтому битой считается только внутри раздела.
        for link in p.__dict__.get("_nofollow_links", ()):
            key = url_key(link)
            target = by_key.get(key) or by_key.get(key.split("?", 1)[0])
            if target and target != p.url:
                soft[p.url].add(target)
                soft_inbound.add(target)
            elif not target and key.split("?", 1)[0].count("/") >= 4:
                unresolved.add(key)
                unresolved_from[p.url].add(key)
                if urlsplit(link).path.endswith("/"):
                    unresolved_dirs.add(key)
        outbound[p.url] = targets
        if getattr(p, "nofollow", False):
            nofollow.add(p.url)
            followed[p.url] = {landing} if landing and landing != p.url else set()
        elif landing and landing != p.url:
            # Заглушку поисковик не читает как страницу — он уходит по
            # редиректу. Ссылки из её тела никуда не ведут.
            followed[p.url] = {landing}
        else:
            followed[p.url] = targets
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

    # Поисковик верит hreflang, только если версия называет страницу в ответ,
    # и не читает его на странице под noindex. Иначе связи нет: страница, на
    # которую указал один hreflang с главной, оставалась «не сиротой».
    by_page = {p.url: p for p in pages}
    by_hreflang = defaultdict(set, {
        source: {t for t in twins if source in by_hreflang.get(t, ())}
        for source, twins in by_hreflang.items()
        if not getattr(by_page[source], "noindex", False)})

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
        # Редирект заглушки — не клик: шаг к цели бесплатный (обход 0-1).
        # Раньше `/go/` с meta refresh посреди пути добавлял уровень, и
        # `deep` срабатывал на клик раньше.
        found = {}
        if home:
            found[home] = 0
            queue = deque([home])
            while queue:
                cur = queue.popleft()
                for nxt in sorted(edges(cur)):
                    free = landing_of.get(cur) == nxt
                    step = found[cur] + (0 if free else 1)
                    if nxt not in found or step < found[nxt]:
                        found[nxt] = step
                        if free:
                            queue.appendleft(nxt)
                        else:
                            queue.append(nxt)
        return found

    by_links = walk(lambda u: () if u in blocked else followed.get(u, ()))
    depth = walk(lambda u: set() if u in blocked
                 else set(followed.get(u, ())) | by_hreflang.get(u, set()))
    behind_robots = []
    if blocked and home:
        anyway = walk(lambda u: set(followed.get(u, ())) | by_hreflang.get(u, set()))
        behind_robots = sorted(u for u in anyway if u not in depth)
    behind_nofollow = []
    if (nofollow or soft) and home:
        loose = walk(lambda u: set() if u in blocked
                     else set(followed.get(u, ()) if u in landing_of and u not in nofollow
                              else outbound.get(u, ())) | soft.get(u, set())
                     | by_hreflang.get(u, set()))
        behind_nofollow = sorted(u for u in loose if u not in depth)
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
        "unresolved_from": {u: sorted(k) for u, k in unresolved_from.items()},
        # Ссылка со слешем в конце — на каталог: `/node.js/` — страница, а не файл.
        "unresolved_dirs": sorted(unresolved_dirs),
        "home_redirected_from": redirected_from,
        # Сама заглушка — не страница: на неё не должны вести ссылки, и из неё
        # никуда не нужно доходить.
        "only_hreflang": only_hreflang,
        "orphans": sorted(u for u in urls if not inbound.get(u) and u != home
                          and u != redirected_from and not hreflang_inbound.get(u)
                          and u not in soft_inbound),
        "dead_ends": sorted(u for u in urls if not outbound.get(u)),
        "unreachable": sorted(u for u in urls if u not in depth
                              and u != redirected_from) if home else [],
        "behind_robots": behind_robots,
        "behind_nofollow": behind_nofollow,
    }


def _parent(key: str) -> str:
    return key[:key.rfind("/")] if key.count("/") > 2 else key.rstrip("/")


_ROUTE_LEAF = {"index", "page", "route", "+page", "+server", "default"}
_DYNAMIC = re.compile(r"^\[{1,2}(\.\.\.)?[^\]]*\]{1,2}$")
MAX_ROUTE_ENTRIES = 200_000


def build_routes(root: str) -> tuple:
    """
    Маршруты, которые сборка знает, даже если HTML у них нет.

    Next.js кладёт динамический маршрут как `[lang]/start/page.js`: страница
    отдаётся сервером, а файла `start.html` нет. Без этого на сайте виз
    `broken-link` стоял на 527 страницах со ссылкой на /en/start. Группы
    `(marketing)` и параллельные `@slot` в адрес не входят; `[x]` — любой
    сегмент, `[...x]` и `[[...x]]` — любой хвост.
    """
    literal, dynamic = set(), []
    if not root or not os.path.isdir(root):
        return literal, dynamic
    seen = 0
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ALWAYS_SKIP]
        rel = os.path.relpath(current, root)
        base = [] if rel == "." else rel.replace(os.sep, "/").split("/")
        # Каталог — маршрут, только если в нём есть страница или файл маршрута
        # (`index.html`, `page.js`): `/downloads/` с одним PDF внутри на живом
        # хостинге — 404. Сам файл — тоже адрес: `/download/setup.exe`.
        # `oslo.json` и `photo.jpg` — только файлы: адреса /rent/oslo у них нет.
        names = ([[]] if not base else []) + [
            base + [os.path.splitext(f)[0]] for f in files
            if f.rsplit(".", 1)[-1].lower() not in _DATA_EXTS]
        literal.update("/" + "/".join(base + [f]) for f in files)
        seen += len(files) + 1
        for segs in names:
            if segs and segs[-1] in _ROUTE_LEAF:
                segs = segs[:-1]
            segs = [x for x in segs if not (x.startswith("(") and x.endswith(")"))
                    and not x.startswith("@")]
            if any(_DYNAMIC.match(x) for x in segs):
                dynamic.append(tuple(segs))
            else:
                literal.add("/" + "/".join(segs))
        if seen > MAX_ROUTE_ENTRIES:
            break
    return literal, sorted(set(dynamic))


def _route_matches(pattern: tuple, segs: list) -> bool:
    for n, part in enumerate(pattern):
        m = _DYNAMIC.match(part)
        if m and m.group(1):                       # [...x] / [[...x]]: хвост
            return len(segs) > n or part.startswith("[[")
        if n >= len(segs):
            return False
        if not m and part != segs[n]:
            return False
    return len(segs) == len(pattern)


# Расширения файлов, а не страниц. Точка в слаге — не расширение: `/v1.2/`,
# `/gost-12.4.011/`, `/asp.net` — страницы, и о пропаже таких молчали.
ASSET_EXTS = frozenset("""
    html htm xhtml xml json jsonld txt pdf png jpg jpeg gif svg webp avif bmp tif tiff ico
    heic css js mjs cjs map woff woff2 ttf otf eot zip gz tgz tar bz2 xz 7z rar rss atom
    csv tsv md yml yaml toml ics vcf epub doc docx xls xlsx ppt pptx odt mp3 mp4 m4a ogg
    wav webm mov avi wasm webmanifest
""".split())
# У этих файлов нет адреса без расширения (в отличие от `page.js`, `about.md`).
_DATA_EXTS = ASSET_EXTS - {"html", "htm", "xhtml", "js", "mjs", "cjs", "md"}


def _is_file_link(key: str, dirs: set) -> bool:
    last = key.split("?", 1)[0].rsplit("/", 1)[-1]
    if "." not in last or key in dirs:
        return False
    return last.rsplit(".", 1)[-1].lower() in ASSET_EXTS


def missing_sections(pages: list, graph: dict, base_path: str = "",
                     least: int = 10) -> list:
    """
    Разделы, на страницы которых сайт ссылается, а в сборке их нет вовсе:
    [(раздел, сколько разных адресов)].

    Битой такая ссылка не считается — другая часть домена бывает отдана
    другим приложением. Но когда генератор раздела упал, двенадцать ссылок
    главной на /rent/… молчали, и отчёт выходил чистым. Порог — `least`
    разных адресов в одном разделе: одна-две ссылки на /login — это не раздел.
    """
    base = "/" + base_path.strip("/") if base_path.strip("/") else ""
    dirs = set(graph.get("unresolved_dirs") or ())

    def local_of(key):
        local = "/" + key.split("/", 3)[-1] if key.count("/") >= 3 else "/"
        if base:
            if local != base and not local.startswith(base + "/"):
                return None
            local = local[len(base):] or "/"
        return local

    present = set()
    for p in pages:
        local = local_of(p.key)
        if local:
            present.add(local.strip("/").split("/", 1)[0])
    targets = defaultdict(set)
    for key in graph.get("unresolved") or ():
        path = key.split("?", 1)[0]
        if _is_file_link(path, dirs):
            continue
        local = local_of(path)
        segs = [x for x in (local or "").strip("/").split("/") if x]
        if len(segs) >= 2 and segs[0] not in present:
            targets[segs[0]].add(path)
    return sorted(((section, len(found)) for section, found in targets.items()
                   if len(found) >= least), key=lambda x: (-x[1], x[0]))


def broken_links(pages: list, graph: dict, base_path: str = "",
                 case_twins: dict = None) -> dict:
    """
    Ссылки на страницы, которых в сборке нет: страница → пути.

    Ссылка считается битой, только если ведёт в раздел, который в сборке есть:
    хотя бы одна страница лежит в том же каталоге или каталог сам страница.
    Проверяли только /blog — ссылка в /pricing ведёт в другую часть сайта,
    а не в пустоту. Ассеты, ленты и sitemap — не страницы: у них остаётся
    известное расширение после того, как `url_key` снял `.html`.

    Ссылка, которая совпала со страницей только без учёта регистра
    (`/blog/Tag/` при каталоге `tag/`), — не пропажа, а опечатка: GitHub
    Pages, S3 и nginx на Linux отдают на неё 404. Такие ссылки уходят в
    `case_twins` (страница → [(ссылка, адрес страницы)]), а не в битые.
    """
    keys = {p.key for p in pages}
    folded = {}
    for p in pages:
        folded.setdefault(p.key.lower(), p.url)
    dirs = set(graph.get("unresolved_dirs") or ())
    sections = keys | {_parent(k) for k in keys}
    folded_sections = {k.lower() for k in sections}
    paths = [os.path.dirname(os.path.abspath(p.path)) for p in pages if p.path]
    try:
        root = os.path.commonpath(paths) if paths else ""
    except ValueError:                         # разные диски Windows
        root = ""
    literal, dynamic = build_routes(root) if graph.get("unresolved_from") else (set(), [])
    stub_aims = {p.url: url_key(redirect_target(p)).split("?", 1)[0]
                 for p in pages if redirect_target(p)}
    base = "/" + base_path.strip("/") if base_path.strip("/") else ""

    def is_route(path):
        local = "/" + path.split("/", 3)[-1] if path.count("/") >= 3 else "/"
        if base and (local == base or local.startswith(base + "/")):
            local = local[len(base):] or "/"
        local = local.rstrip("/") or "/"
        if local in literal:
            return True
        segs = [x for x in local.strip("/").split("/") if x]
        return any(_route_matches(pattern, segs) for pattern in dynamic)

    found = {}
    for source, targets in (graph.get("unresolved_from") or {}).items():
        bad = []
        for key in targets:
            path = key.split("?", 1)[0]
            twin = folded.get(path.lower())
            if twin:
                if case_twins is not None:
                    case_twins.setdefault(source, []).append((path, twin))
                continue
            if _is_file_link(key, dirs):
                continue
            if base:
                # Сайт под префиксом: всё вне него — другая часть домена
                # (/pricing рядом с /docs) или чужой проект на том же
                # github.io, а не пустота. Ссылку, забывшую префикс, отсюда
                # от блога компании не отличить; когда префикс забыт
                # системно, это ловит `root_mismatch`.
                local = "/" + path.lstrip("/").partition("/")[2]
                if local != base and not local.startswith(base + "/"):
                    continue
            # Цель заглушки-редиректа — её единственное содержание: раздел,
            # куда переехали страницы, выпал из сборки — типовая ошибка
            # алиасов Hugo. Поблажка «раздел отдаёт другое приложение» — для
            # ссылок <a>, а не для редиректа, который генератор написал сам.
            # `/Rent/nowhere/` при разделе `rent/`: раздел тот же, только
            # регистр другой, — на живом хостинге это всё равно 404.
            # `/faq.html/`: `url_key` сняла бы `.html`, если бы за ним не шёл
            # слэш, — файл `faq.html` по такому адресу хостинг не отдаёт.
            slashed = path in dirs and re.search(r"\.html?$", path, re.I)
            if ((_parent(path) in sections or _parent(path).lower() in folded_sections
                 or stub_aims.get(source) == path)
                    and (slashed or not is_route(path))):
                bad.append(path)
        if bad:
            found[source] = sorted(set(bad))
    return found


def _local(path: str) -> str:
    return "/" + path.split("/", 3)[-1] if path.count("/") >= 3 else "/"


def wrong_form_issues(pages: list, case_twins: dict) -> list:
    """
    Ссылки, которые ведут на страницу сборки, но в форме, которую хостинг не
    отдаёт: другой регистр букв (`case_twins` из `broken_links`) или чужая
    форма адреса — `/about.html` при `about/index.html`, `/faq/` при
    `faq.html` (её отмечает разбор, `_wrong_forms` страницы).
    """
    by_key = {p.key: p.url for p in pages}
    issues = []
    for page in pages:
        written = []
        pairs = sorted(set(case_twins.get(page.url, ())))
        for path, twin in pairs:
            written.append(tr("{a0} вместо {a1}", a0=_local(path), a1=urlsplit(twin).path))
        if written:
            more = tr(" и ещё {a0}", a0=len(written) - 3) if len(written) > 3 else ""
            issues.append(("warning", page.url, "wrong-link-form", Said(tr(
                "ссылки расходятся со страницей регистром букв: {a0}{a1}. GitHub Pages, "
                "S3 и nginx на Linux различают регистр и отдают на них 404",
                a0=", ".join(written[:3]), a1=more), (_local(p) for p, _ in pairs))))
        forms = {(path, urlsplit(by_key[key]).path)
                 for key, path in page.__dict__.get("_wrong_forms", ()) if key in by_key}
        written = sorted({tr("{a0} вместо {a1}", a0=path, a1=aim) for path, aim in forms})
        if written:
            more = tr(" и ещё {a0}", a0=len(written) - 3) if len(written) > 3 else ""
            issues.append(("warning", page.url, "wrong-link-form", Said(tr(
                "ссылки в форме, которой нет в сборке: {a0}{a1}. Сервер сводит формы "
                "адреса только по своим правилам: GitHub Pages и S3 отдают "
                "`about/index.html` по /about/, но не по /about.html, а `faq.html` — "
                "по /faq.html, но не по /faq/; на такие ссылки они отвечают 404",
                a0=", ".join(written[:3]), a1=more), (p for p, _ in forms))))
    return issues


def canonical_form_issues(pages: list) -> list:
    """
    Canonical на саму страницу, но в форме, которой раскладка файлов не
    отдаёт (её отмечает разбор, `_canonical_form` страницы): `about.html`
    с canonical `/about/`, `a/index.html` с `/a.html` — это 404, а
    `a/index.html` с `/a` — редирект на `/a/`. Страница закрытая или
    заглушка-редирект не в счёт: в индекс её canonical не идёт.
    """
    issues = []
    for page in pages:
        mark = page.__dict__.get("_canonical_form")
        if not mark or not indexable(page) or redirect_target(page):
            continue
        form, served = mark
        own = urlsplit(page.url).path
        if form != "bare":
            issues.append(("warning", page.url, "canonical-form", tr(
                "canonical объявляет адрес {a0}, а страница лежит как {a1}: этой формы "
                "сборка не отдаёт, и GitHub Pages, S3 и nginx отвечают на {a0} 404. "
                "Тот же адрес уходит в sitemap и hreflang", a0=own, a1=served)))
            continue
        issues.append(("warning", page.url, "canonical-form", tr(
            "canonical объявляет адрес {a0}, а страница лежит как {a1}: GitHub Pages, "
            "Netlify, Cloudflare Pages, S3 и nginx отвечают на {a0} редиректом на {a1}. "
            "Тот же адрес уходит в sitemap и hreflang", a0=own, a1=served)))
    return issues


def _other_host(pages: list) -> str:
    """Хост, под которым сайт ссылается на собственные страницы, если такой есть."""
    keys = {p.key.split("/", 3)[3] if p.key.count("/") >= 3 else "" for p in pages}
    hits = Counter()
    for p in pages:
        for key in p.__dict__.get("_foreign_links", ()):
            host, _, path = key.lstrip("/").partition("/")
            if path.rstrip("/") in keys or (not path and "" in keys):
                hits[host] += 1
    if not hits:
        return ""
    host, n = hits.most_common(1)[0]
    return host if n >= max(5, len(pages) * 0.3) else ""


def _home_resolves(pages: list, unresolved: set, base_path: str) -> bool:
    """
    Главная лежит в корне каталога, и её ссылки почти все сходятся: корень
    выбран верно, а короткие ссылки — ошибка одного раздела (`/de/` ссылается
    на /rent/… без префикса), а не сдвиг всего сайта.
    """
    home = "/" + base_path.strip("/") if base_path.strip("/") else "/"
    for p in pages:
        if (urlsplit(p.key).path or "/") != home:
            continue
        host = urlsplit(p.key).netloc
        own = [k for k in (url_key(u) for u in p.links) if urlsplit(k).netloc == host]
        return bool(own) and sum(k in unresolved for k in own) * 2 < len(own)
    return False


def root_mismatch(pages: list, graph: dict, base_path: str = "") -> str:
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
    lost = len(orphans) + len(graph.get("unreachable") or [])
    if pages and lost >= max(3, len(pages) * 0.3):
        other = _other_host(pages)
        if other:
            return tr("ссылки на страницах ведут на {a0}, а сайт проверяется как {a1}: "
                      "для пакета это чужой сайт, и страницы выглядят сиротами. Если "
                      "{a0} — тот же сайт (старый домен, github.io за CNAME), задай его "
                      "в --site или поправь адрес сайта в генераторе — на живом сайте "
                      "каждая такая ссылка идёт через редирект.",
                      a0=other, a1=pages[0].url.split("/")[2])
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
    if hits >= max(2, len(unresolved) * 0.5) and not _home_resolves(pages, unresolved, base_path):
        prefix = "/" + base_path.strip("/") if base_path.strip("/") else ""
        if prefix:
            # Сайт живёт под префиксом, а ссылки его не несут: на живом сайте
            # они ведут в 404 — это ошибка шаблона, а не запуска.
            return tr("ссылки на страницах не несут префикса {a0}: сайт живёт под ним, а "
                      "ссылки ведут от корня домена — на живом сайте это 404. Задай "
                      "базовый путь в генераторе (pathPrefix, baseURL, basePath) и "
                      "пересобери. Из-за этого же все страницы выглядят сиротами.",
                      a0=prefix)
        paths = [os.path.dirname(p.path) for p in pages if p.path]
        try:
            # Прямые слэши на любой системе: путь печатается и в CI-логах.
            first = (os.path.commonpath(paths) if paths else ".").replace(os.sep, "/")
        except ValueError:
            first = "."
        return (tr("похоже, каталог не соответствует корню сайта: ссылки на страницах короче их собственных адресов на один сегмент. Из-за этого все страницы выглядят сиротами, и такой же сдвиг уедет в sitemap.\n    Проверь, какой каталог отображается в корень {a0} — сейчас это {a1}", a0=pages[0].url.split('/')[2], a1=first))
    return ""


def _length_bounds(cfg: dict, language: str = "") -> dict:
    """
    Пороги длины. Один и тот же для всех языков — потому что меряется ширина.

    Раньше здесь был множитель «для CJK», выбираемый по языку страницы.
    На смешанной строке — а мультиязычные сайты состоят из них: иероглифы
    плюс бренд и «Form B14» латиницей — он ошибался в обе стороны, и выбирать
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
    "orphan", "unreachable", "deep", "description-length", "broken-link",
    "wrong-link-form",
}


def _consolidated(page, target) -> bool:
    """
    Вариант страницы, отданный основной: печатная копия, второй адрес. Перевод
    с canonical на другой язык — не вариант, а потерянная версия: он остаётся
    критичным (на apisix /zh/comparisons/ → /comparisons/).
    """
    if not indexable(target):
        return False
    lang_a = (page.lang or "").lower().split("-")[0]
    lang_b = (target.lang or "").lower().split("-")[0]
    if lang_a and lang_b and lang_a != lang_b:
        return False
    first = lambda p: urlsplit(p.url).path.strip("/").split("/")[0].lower()
    a, b = first(page), first(target)
    return not (a != b and (_is_locale(a) or _is_locale(b)))


def _slug(url: str) -> str:
    return urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1].lower()


def _text_overlap(a, b, k: int = None) -> float:
    """Доля общих словесных n-грамм двух страниц (Jaccard)."""
    k = k or CONFIG["shingle_size"]
    sa, sb = _shingles(list(a.words or ()), k), _shingles(list(b.words or ()), k)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _a_variant_of(page, target) -> bool:
    """
    Похожа ли страница на вариант той, на которую ведёт её canonical: печатная
    копия `/x/print/` под `/x/`, старая версия документации с тем же именем
    `/v1/install/` → `/install/`, или просто тот же текст. Шаблон, собравший
    canonical из чужой переменной (`/rent/hamburg/` → `/rent/berlin/`), даёт
    страницу с другим именем и другим текстом — это не вариант.
    """
    path, home = urlsplit(page.url).path, urlsplit(target.url).path
    if _slug(page.url) == _slug(target.url):
        return True
    # Вариантом считается только служебная копия под страницей: `/x/print/`,
    # `/x/amp/`, `/x/page/2/`. Раньше подходил любой адрес под целью, и для
    # canonical на главную или на хаб раздела вариантом становился весь сайт:
    # ошибка шаблона пряталась вместе со всеми находками о страницах.
    prefix = home.rstrip("/") + "/"
    if path.startswith(prefix) and _VARIANT_TAIL.match(path[len(prefix):].strip("/")):
        return True
    # Шаблонная копия под другой запрос (`/rent/hamburg/` → `/rent/berlin/`)
    # почти совпадает текстом, но у неё свои title и H1: это не вариант.
    return (_text_overlap(page, target) >= CONFIG["near_duplicate"]
            and not _another_subject(page, target))


def _another_subject(page, target) -> bool:
    """Разные и title, и H1 — страница о другом, а не вторая копия той же."""
    def h1(p):
        return next((t for lvl, t in p.headings if lvl == 1), "")
    norm = lambda s: " ".join((s or "").lower().split())
    return (bool(norm(page.title)) and norm(page.title) != norm(target.title)
            and bool(norm(h1(page))) and norm(h1(page)) != norm(h1(target)))


_VARIANT_TAIL = re.compile(
    r"^(?:(?:index[.-])?(?:print|printable|print-version|printer-friendly|amp|pdf|embed|"
    r"preview|mobile|m)(?:\.html?)?|(?:page/|p/)?\d+(?:/)?|page-\d+(?:\.html?)?)$", re.I)


def misdirected(pages: list) -> dict:
    """
    {url: цель} — страницы, чей canonical ведёт на открытую страницу того же
    языка, которая на них не похожа. Раньше такие страницы считались
    «намеренно закрытыми копиями»: находка была справкой, а всё остальное о
    странице — выдуманная цена, сирота, дубль — пропадало из отчёта. Ошибка
    шаблона делала отчёт зеленее.
    """
    by_key = {p.key: p for p in pages}
    out = {}
    for p in pages:
        if not p.canonical or p.noindex or url_key(p.canonical) == p.key:
            continue
        target = by_key.get(url_key(p.canonical))
        if target is not None and _consolidated(p, target) and not _a_variant_of(p, target):
            out[p.url] = target.url
    return out


class _Bare:
    """Кусок текста, который `text_volume` меряет как страницу."""

    def __init__(self, text: str):
        self.text = text
        self.word_count = len(tokenize(text))


_CLOSED_BY_DESIGN = {"print", "print.html", "toc", "toc.html", "search", "search.html",
                     "404", "404.html", "search-results"}


def technical_issues(pages: list, cfg: dict = None, language: str = "",
                     shells: set = None) -> list:
    """Плоский список находок: (уровень, url, код, пояснение)."""
    cfg = {**CONFIG, **(cfg or {})}
    by_key = {p.key: p for p in pages}
    bounds = _length_bounds(cfg)
    shells = shells or set()
    issues = []
    wrong = misdirected(pages)
    # Одна цель у нескольких страниц — canonical собран шаблоном из чужой
    # переменной: это одна ошибка на весь шаблон, и она критична.
    collected = defaultdict(int)
    for target_url in wrong.values():
        collected[target_url] += 1

    titles = defaultdict(list)
    descriptions = defaultdict(list)
    # Шапка, меню и подвал страницы без <main>: одинаковые у многих страниц —
    # обвязка сайта, и в объём статьи она не входит.
    frames = Counter(p.framed for p in pages
                     if not p.chrome and getattr(p, "framed", ""))
    for p in pages:
        # Отдельные noindex/canonical-находки не отменяют намеренную
        # консолидацию URL и не делают её дублем индексируемой страницы.
        if not indexable(p):
            continue
        # Перевод с тем же заголовком — не соперник: `/de/` и `/fr/` в выдаче
        # разных стран не конкурируют (Congo: 147 «дублей» из пяти языков).
        language = (p.lang or "").lower().split("-")[0]
        if not language:
            # Без lang язык — по тексту: `/ca/`, `/de/`, `/pa/` бывают и
            # штатами. Префикс пути — только когда текст не говорит ничего.
            from . import langid
            head = (p.title or "") + " " + (p.description or "")
            language = (langid.identify(" ".join(list(p.paragraphs or [])[:30]))[0]
                        or langid.identify(head, min_tokens=8)[0])
            if not language:
                first = urlsplit(p.url).path.strip("/").split("/")[0].lower()
                language = first if _is_locale(first) else ""
        if p.title:
            titles[(language, p.title.strip().lower())].append(p.url)
        if p.description:
            descriptions[(language, p.description.strip().lower())].append(p.url)

    for p in pages:
        for note in p.notes:
            issues.append(("warning", p.url, "source-note", note))
        if p.noindex:
            # Печатная копия и оглавление mdBook, поиск Docusaurus, страница 404
            # закрыты генератором намеренно: это сведение, а не авария.
            last = urlsplit(p.url).path.rstrip("/").rsplit("/", 1)[-1].lower()
            issues.append(("info" if last in _CLOSED_BY_DESIGN else "critical", p.url,
                           "noindex",
                           tr("страница закрыта от индексации — если это не задумано, трафика не будет")))
        if p.nosnippet:
            issues.append(("critical", p.url, "nosnippet",
                           tr("запрещён сниппет: страница может быть в индексе, но в ответы ИИ-поиска и в расширенную выдачу не попадёт")))
        # Title из одних невидимых знаков (U+200B, BOM, &shy;) не виден в выдаче.
        if not p.title or not display_width(p.title):
            issues.append(("critical", p.url, "no-title", tr("нет title")))
        else:
            n = display_width(p.title)
            if n < bounds["title_min"]:
                issues.append(("warning", p.url, "title-short", tr("title {a0} символов", a0=n)))
            elif n > bounds["title_max"]:
                issues.append(("info", p.url, "title-long",
                               tr("title {a0} символов, обрежется в выдаче", a0=n)))
        if not p.description or not display_width(p.description):
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

        # На закрытой странице canonical — часть того же решения: одна находка,
        # а не две. Старые версии документации давали восемь тысяч критичных.
        if p.canonical and url_key(p.canonical) != p.key and not p.noindex:
            target = by_key.get(url_key(p.canonical))
            if p.url in wrong:
                many = collected[wrong[p.url]]
                clone = _text_overlap(p, target) >= cfg["near_duplicate"]
                issues.append(("critical" if many > 1 else "warning", p.url, "canonical-elsewhere",
                               (tr("canonical указывает на {a0}, а это другая страница: текст "
                                   "почти тот же, но другие имя, title и H1 — копия шаблона под "
                                   "другой запрос. Страница просит убрать её из индекса",
                                   a0=target.url) if clone else
                                tr("canonical указывает на {a0}, а это другая страница: другое имя "
                                  "и почти нет общего текста. Так бывает, когда шаблон берёт "
                                  "адрес из чужой переменной; страница просит убрать её из "
                                  "индекса", a0=target.url))
                               + (tr(" (на эту же страницу ведут canonical ещё {a0} стр.)",
                                     a0=many - 1) if many > 1 else "")))
            elif target is not None and _consolidated(p, target):
                issues.append(("info", p.url, "canonical-elsewhere",
                               tr("копия страницы {a0}: canonical указывает на неё, и та в сборке "
                                  "открыта — так и должно быть, если это вариант (печатная версия, "
                                  "второй адрес)", a0=target.url)))
            else:
                issues.append(("critical", p.url, "canonical-elsewhere",
                               tr("canonical указывает на {a0} — страница отдаёт вес другой",
                                  a0=p.canonical)))
        elif p.__dict__.get("_canonical_origin") and not p.noindex:
            # Та же страница, но по другому адресу: `http://` или `www.` там,
            # где остальной сайт называет себя иначе. Сверено с сайтом, а не с
            # --site (`core._settle_canonical_origins`).
            issues.append(("warning", p.url, "canonical-elsewhere",
                           tr("canonical указывает на {a0} — та же страница, но по другому "
                              "адресу, а сайт живёт по {a1}. Поисковик "
                              "считает эту страницу копией того адреса, в sitemap она не идёт",
                              a0=p.canonical, a1=p.__dict__["_canonical_origin"])))
        volume = text_volume(p, language)
        if not p.chrome and getattr(p, "framed", "") and frames[p.framed] >= 3:
            rest = volume - text_volume(_Bare(p.framed), language)
            if rest > 0:
                volume = rest
        if volume < cfg["thin_words"]:
            issues.append(("warning", p.url, "thin",
                           tr("объём текста ≈ {a0} — тонкая страница", a0=volume)))

    issues = [i for i in issues if not (i[1] in shells and i[2] in SHELL_DEPENDENT)]

    for groups in (titles, descriptions):
        # Страница без языка — не другой перевод, если язык у этого текста один.
        named = defaultdict(set)
        for language, text in groups:
            named[text].add(language)
        for text, languages in named.items():
            if "" in languages and len(languages) == 2:
                other = next(l for l in languages if l)
                groups[(other, text)] += groups.pop(("", text))
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
    "stale-event": 0, "translations-parked": 1, "unsupported-number": 1, "still-draft": 2, "brief-left": 3, "unfilled-slot": 2, "llm-leftover": 3, "mojibake": 4,
    "noindex": 3, "noindex-group": 2, "nosnippet": 4, "canonical-elsewhere": 5,
    "hreflang-static-cluster": 4, "hreflang-canonical-conflict": 5,
    "hreflang-no-self": 5, "hreflang-no-return": 6, "hreflang-in-body": 6,
    "hreflang-target-blocked": 7, "hreflang-missing": 12, "hreflang-bad-code": 13,
    "hreflang-lang-mismatch": 15, "hreflang-conflict": 14, "hreflang-relative": 13, "hreflang-unknown-target": 19, "lang-script-mismatch": 12, "lang-text-mismatch": 12, "fact-drift": 20,
    "robots-blocks-page": 5, "orphan": 6, "unreachable": 7, "hub-missing-links": 8,
    "jsonld-mismatch": 9, "microdata-mismatch": 9, "no-viewport": 10, "stale-year": 11, "heavy-html": 11, "near-duplicate": 8, "low-uniqueness": 9,
    "template-skeleton": 10, "same-opening": 11, "thin": 12,
    "no-title": 13, "no-h1": 14, "duplicate-title": 15, "deep": 16,
    "similar": 17, "duplicate-risk": 10, "broken-link": 17, "redirect-home": 16, "wrong-link-form": 17, "canonical-form": 17, "source-note": 18, "check-by-eye": 19, "stale-closed": 30,
}


# Находки, которые и должны встречаться массово: это их природа, а не шаблон.
NOT_TEMPLATE_WIDE = {"near-duplicate", "similar", "duplicate-risk", "js-shell", "unsupported-number",
                     "translations-parked", "noindex-group",
                     "stale-event", "still-draft", "brief-left",
                     "hreflang-no-return", "hreflang-unknown-target"}


class TemplateNote(str):
    """Строка заметки о шаблоне плюс адреса, которые она покрывает (`urls`)."""

    urls = frozenset()

    @classmethod
    def of(cls, text: str, urls) -> "TemplateNote":
        note = cls(text)
        note.urls = frozenset(urls)
        return note


def _url_pattern(url: str) -> str:
    """`/plumbing/austin/` → `/plumbing/*/`: последний сегмент пути — переменная шаблона."""
    parts = [s for s in urlsplit(url).path.split("/") if s]
    if not parts:
        return ""
    return "/" + "".join(f"{s}/" for s in parts[:-1]) + "*/"


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

    И по шаблонам адресов. 170 страниц `/plumbing/<город>/` рядом с 30
    записями блога: дефект городского шаблона — 85% сайта и 100% шаблона.
    Сайтовый порог его не видит, а чинится он так же — один раз.

    Каждая заметка — `TemplateNote`: помнит, какие адреса покрывает, чтобы
    наряд шаблона забирал только их, а не ту же находку со всего сайта.
    """
    if page_count < 20:
        return []
    by_code = defaultdict(set)
    for level, url, code, _ in issues:
        if code in NOT_TEMPLATE_WIDE or not url or url == "robots.txt":
            continue
        by_code[code].add(url)
    notes = []
    covered = defaultdict(set)
    for code, urls in sorted(by_code.items()):
        got = len(urls) / page_count
        if got >= share:
            notes.append(TemplateNote.of(
                tr("`{a0}` — на {a1} страницах из {a2} ({a3:.0%}). Это свойство "
                   "шаблона, а не список страниц: чинится один раз в шаблоне "
                   "и исчезает везде.", a0=code, a1=len(urls), a2=page_count,
                   a3=got), urls))
            covered[code] |= urls

    total_by_lang = defaultdict(set)
    where = {}
    for page in pages or ():
        code = (page.lang or "").split("-")[0].lower()
        where[page.url] = code
        if code:
            total_by_lang[code].add(page.url)

    if len(total_by_lang) >= 2:
        for code, urls in sorted(by_code.items()):
            if code in covered:
                continue                  # уже сказано про весь сайт
            hit = defaultdict(set)
            for url in urls:
                language = where.get(url)
                if language:
                    hit[language].add(url)
            for language, got in sorted(hit.items()):
                total = len(total_by_lang.get(language) or ())
                if total >= 20 and len(got) / total >= share:
                    notes.append(TemplateNote.of(
                        tr("`{a0}` — на {a1} страницах языка «{a2}» из {a3}, то есть "
                           "почти на всех. По сайту это лишь {a4:.0%}, но чинится "
                           "один раз: в шаблоне этой языковой версии.",
                           a0=code, a1=len(got), a2=language, a3=total,
                           a4=len(urls) / page_count), got))
                    covered[code] |= got

    by_pattern = defaultdict(set)
    for page in pages or ():
        pattern = _url_pattern(page.url)
        if pattern:
            by_pattern[pattern].add(page.url)
    for pattern, members in sorted(by_pattern.items()):
        if len(members) < 20:
            continue
        for code, urls in sorted(by_code.items()):
            got = (urls & members) - covered[code]
            if len(got) < 20 or len(urls & members) / len(members) < share:
                continue
            notes.append(TemplateNote.of(
                tr("`{a0}` — на {a1} страницах шаблона {a2} из {a3}. По сайту это "
                   "{a4:.0%}, но страницы одного шаблона и чинятся один раз — "
                   "в этом шаблоне.", a0=code, a1=len(urls & members), a2=pattern,
                   a3=len(members), a4=len(urls) / page_count), got))
            covered[code] |= got
    return notes


RISK_MIN_PAGES = 10
RISK_OTHER = "other"


def _severity(level: str, code: str) -> float:
    """Тяжесть одной находки, 0–1: см. `template_risk`."""
    if level not in ("critical", "warning"):
        return 0.0
    hard = 1.0 - min(CODE_WEIGHT.get(code, 50), 20) / 40
    return hard if level == "critical" else 0.3 * hard


def template_risk(issues: list, pages: list, min_pages: int = RISK_MIN_PAGES) -> list:
    """
    Какой шаблон чинить первым: риск 0–100 по каждому шаблону адресов.

    Шаблон — `_url_pattern` страницы; шаблоны меньше `min_pages` страниц
    сложены в `other`. Нет ни одного шаблона такого размера — сайт и есть
    один шаблон, и сказать нечего: возвращается пустой список.

    Формула. Тяжесть находки берётся из `CODE_WEIGHT` (меньше вес — тяжелее):

        критичная:  1 − min(вес, 20) / 40      от 1.0 до 0.5
        внимание:   0.3 × то же самое           от 0.3 до 0.15
        мелочь:     0

    Код без веса считается весом 50, то есть самым лёгким. Страница весит
    по своей самой тяжёлой находке — сто мелочей на одной странице не делают
    её опаснее одной закрытой от индекса. Риск шаблона — средняя тяжесть по
    его страницам × 100, округлённая: доля задетых страниц входит в него сама.

    Находки уровня сайта (robots.txt, без адреса) ни к одному шаблону
    не относятся.
    """
    by_url = {}
    for page in pages or ():
        by_url[page.url] = page.url
        by_url.setdefault(url_key(page.url), page.url)
    groups = defaultdict(list)
    for page in pages or ():
        groups[_url_pattern(page.url)].append(page.url)
    if not any(len(m) >= min_pages for p, m in groups.items() if p):
        return []
    template_of = {}
    for pattern, members in groups.items():
        name = pattern if pattern and len(members) >= min_pages else RISK_OTHER
        for url in members:
            template_of[url] = name

    worst = defaultdict(float)
    levels = defaultdict(set)
    codes = defaultdict(Counter)
    for level, url, code, message in issues:
        if level not in ("critical", "warning") or not url:
            continue
        owners = [by_url.get(url) or by_url.get(url_key(url))]
        if code == "noindex-group":
            # Находка о разделе стоит на пути `/visa/`, а закрыты страницы её
            # веток: их собственный noindex понижен до сведений, и риск шаблона
            # иначе обнулялся тем вернее, чем больше веток закрыто.
            owners = [by_url.get(k) for k in getattr(message, "subject", None) or ()]
        seen = set()
        for own in owners:
            if own is None:
                continue
            worst[own] = max(worst[own], _severity(level, code))
            levels[own].add(level)
            if template_of[own] not in seen:
                seen.add(template_of[own])
                codes[template_of[own]][code] += 1

    members = defaultdict(list)
    for url, name in template_of.items():
        members[name].append(url)
    out = []
    for name, urls in members.items():
        total = len(urls)
        out.append({
            "pattern": name,
            "pages": total,
            "critical_share": round(sum(1 for u in urls if "critical" in levels[u]) / total, 3),
            "warning_share": round(sum(1 for u in urls if "warning" in levels[u]) / total, 3),
            "top_codes": [{"code": c, "count": n}
                          for c, n in sorted(codes[name].items(),
                                             key=lambda x: (-x[1], x[0]))[:3]],
            "risk": int(100 * sum(worst[u] for u in urls) / total + 0.5),
        })
    return sorted(out, key=lambda t: (-t["risk"], -t["pages"], t["pattern"]))


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
    # Предмет — языки: перевод, запаркованный после базовой линии, — новая
    # находка, а не та же самая с другим числом в тексте.
    kept.append(("critical", "hreflang", "translations-parked", Said(message, by_lang)))
    notes.append(tr(
        "запаркованные переводы: {a0} страниц(ы) сведены в одну находку, "
        "снято {a1} повторов — у каждой страницы было до семи находок "
        "с одной причиной.", a0=len(parked), a1=removed))
    return kept


# Что имеет смысл говорить о странице, закрытой от индекса: само закрытие и
# то, что касается связей с другими страницами.
KEEP_ON_CLOSED = {"noindex", "canonical-elsewhere", "nosnippet", "stale-closed",
                  "still-draft", "brief-left", "hreflang-canonical-conflict",
                  "translations-parked"}


CLOSED_SECTION_MIN = 20


class _SectionNote(str):
    """Заметка о закрытом разделе: помнит раздел, чтобы её можно было снять."""

    def __new__(cls, section, text):
        self = super().__new__(cls, text)
        self.section = section
        return self

    def __reduce__(self):
        return (_SectionNote, (self.section, str(self)))


def _closed_sections(issues: list, notes: list, pages: list) -> list:
    """
    Закрытый раздел — решение, а не четыре тысячи ошибок.

    Docusaurus закрывает старые версии документации, pkgdown — `/dev/`, Hugo —
    журнал изменений. На apisix это 4 172 критичных `noindex` и первое место
    в «чинить в этом порядке». Раздел, где закрыто не меньше 90% из двадцати
    и более страниц и который меньше половины сайта, получает одну заметку,
    а его страницы — сведения вместо критичных. Закрытый целиком сайт —
    по-прежнему беда: это правило его не трогает.
    """
    from collections import Counter as _Counter
    total, closed = _Counter(), _Counter()
    for p in pages:
        parts = urlsplit(p.url).path.strip("/").split("/")
        for depth in range(1, min(len(parts), 4)):
            prefix = "/" + "/".join(parts[:depth]) + "/"
            total[prefix] += 1
            if p.noindex:
                closed[prefix] += 1
    # Ветки каталога, закрытые рядом с такими же открытыми, — не старая
    # версия документации, а `noindex-group`: двадцать вопросов на страну
    # тихо уходили в сведения, и большая авария выглядела зеленее малой.
    branches = _catalogue_branches(
        {i[1] for i in issues if i[2] == "noindex" and i[0] == "critical"}, pages)
    sections = sorted(
        (prefix for prefix, n in total.items()
         if n >= CLOSED_SECTION_MIN and closed[prefix] >= 0.9 * n and n < 0.5 * len(pages)
         and not any(prefix.startswith(b) or b.startswith(prefix) for b in branches)),
        key=lambda s: (s.count("/"), s))
    chosen = []
    for prefix in sections:
        if not any(prefix.startswith(c) for c in chosen):
            chosen.append(prefix)
    # Каждый раздел меньше половины, а вместе — половина сайта и больше: это
    # закрытый сайт, а не решение о разделе. Чем больше веток закрыто, тем
    # зеленее был отчёт. Сведением остаются только разделы с именем версии.
    if sum(total[c] for c in chosen) * 2 >= len(pages):
        chosen = [c for c in chosen if _VERSION_BRANCH.match(c.strip("/").rsplit("/", 1)[-1])]
    if not chosen:
        return issues
    for prefix in chosen:
        notes.append(_SectionNote(prefix, tr(
            "раздел {a0}: закрыто от индекса {a1} страниц из {a2}. Похоже на решение, а "
            "не на ошибку — старые версии документации, черновики, служебные копии. "
            "Если так и задумано, делать ничего не нужно; находки noindex там понижены "
            "до сведений", a0=prefix, a1=closed[prefix], a2=total[prefix])))

    def inside(url):
        path = urlsplit(url).path
        path = path if path.endswith("/") else path + "/"
        return any(path.startswith(c) for c in chosen)

    return [("info",) + tuple(i[1:]) if i[2] == "noindex" and i[0] == "critical"
            and inside(i[1]) else i for i in issues]


CLOSED_GROUP_ENTITIES = 3

# Имена веток, которые выдают версии документации: `/docs/1.2/`, `/v3/`, `/next/`.
# Голое число из трёх цифр и больше (`/city/101/`) — номер в каталоге, а не
# версия; год (`/2019/`) — архив.
_VERSION_BRANCH = re.compile(
    r"^(v\d+(?:[._-]\d+)*(?:[._-]x)?|\d+(?:[._-]\d+)+(?:[._-]x)?|\d{1,2}(?:[._-]x)?"
    r"|(?:19|20)\d\d|next|dev|nightly|canary|legacy|archive|old)$", re.I)


def _closed_groups(closed: set, pages: list) -> tuple:
    """
    Разделы, в которых закрыты целиком три ветки и больше: {раздел: [ветки]},
    а ещё ветки каждого раздела и размеры веток (всех и закрытых страниц).
    """
    size, shut = Counter(), Counter()
    by_parent = defaultdict(list)
    if len(closed) < CLOSED_SECTION_MIN:
        return {}, by_parent, size, shut
    for p in pages:
        path = [x for x in urlsplit(p.url).path.split("/") if x]
        for depth in range(2, len(path) + 1):
            entity = tuple(path[:depth])
            size[entity] += 1
            if p.url in closed:
                shut[entity] += 1
    for entity in size:
        by_parent[entity[:-1]].append(entity)
    chosen = {}
    for parent, entities in by_parent.items():
        full = [e for e in entities
                if size[e] >= 3 and shut[e] >= 0.9 * size[e]]
        pages_closed = sum(shut[e] for e in full)
        if (len(full) >= CLOSED_GROUP_ENTITIES and pages_closed >= CLOSED_SECTION_MIN
                and len(full) * 2 <= len(entities)):
            chosen[parent] = sorted(full)
    # Внешний раздел поглощает вложенный: одна находка на ветку дерева.
    for parent in sorted(chosen, key=len):
        for other in list(chosen):
            if other != parent and other[:len(parent)] == parent and other in chosen:
                if any(other[:len(e)] == e for e in chosen[parent]):
                    del chosen[other]
    return chosen, by_parent, size, shut


def _catalogue_branches(closed: set, pages: list) -> set:
    """
    Закрытые ветки, которые `noindex-group` должен увидеть, даже если каждая
    сама по себе — большой закрытый раздел: рядом стоят такие же открытые
    ветки (не меньше трёх страниц, и их не меньше, чем закрытых), и ни одна
    закрытая не названа как версия документации. Пути веток — `/visa/alpha/`.
    """
    chosen, by_parent, size, _ = _closed_groups(closed, pages)
    out = set()
    for parent, full in chosen.items():
        if any(_VERSION_BRANCH.match(e[-1]) for e in full):
            continue
        shaped = sum(1 for e in by_parent[parent] if e not in full and size[e] >= 3)
        if shaped >= len(full):
            out |= {"/" + "/".join(e) + "/" for e in full}
    return out


def collapse_closed_groups(issues: list, pages: list) -> list:
    """
    Закрытые целиком ветки одного раздела — одно правило, а не сто находок.

    Каталог закрывает noindex страны, по которым нет проверенного текста: у
    каждой десять вопросов, и одиннадцать стран давали 106 критичных `noindex`
    подряд в «чинить в этом порядке». Ветка `/visa/alpha/` закрыта, если
    закрыто не меньше 90% её страниц (их не меньше трёх). Когда в одном
    разделе таких веток три и больше, закрытых страниц не меньше двадцати, а
    открытых веток рядом не меньше, чем закрытых, — находка одна, критичная:
    решение это или ошибка, без sitemap не видно. Страницы ветки понижаются
    до сведений. sitemap, из которого ветки убраны, понижает и саму находку.
    """
    closed = {i[1] for i in issues if i[2] == "noindex" and i[0] == "critical"}
    chosen, by_parent, _, _ = _closed_groups(closed, pages)
    if not chosen:
        return issues

    def parts(url):
        return [x for x in urlsplit(url).path.split("/") if x]

    member = {}
    for parent, full in chosen.items():
        for e in full:
            member[e] = parent

    def group_of(url):
        path = tuple(parts(url))
        for depth in range(len(path), 1, -1):
            if path[:depth] in member:
                return member[path[:depth]]
        return None

    grouped = defaultdict(list)
    out = []
    for item in issues:
        parent = group_of(item[1]) if item[2] == "noindex" and item[0] == "critical" else None
        if parent is None:
            out.append(item)
            continue
        grouped[parent].append(item[1])
        out.append(("info",) + tuple(item[1:]))
    for parent, urls in sorted(grouped.items()):
        full = chosen[parent]
        address = "/" + "/".join(parent) + "/" if parent else "/"
        names = ", ".join(e[-1] for e in full[:8])
        more = tr(" и ещё {a0}", a0=len(full) - 8) if len(full) > 8 else ""
        siblings = len(by_parent[parent])
        out.append(("critical", address, "noindex-group", Said(tr(
            "в {a0} закрыты noindex целиком {a1} ветк(и) из {a2} — {a3} страниц: "
            "{a4}{a5}. Это одно правило шаблона, а не {a3} проблем. Если закрытие "
            "задумано, убери эти страницы и из sitemap — тогда находка станет "
            "сведением", a0=address, a1=len(full), a2=siblings, a3=len(urls),
            a4=names, a5=more), sorted(url_key(u) for u in urls))))
    return out


def closed_off_map(issues: list, sitemap_urls, complete: bool = True) -> list:
    """
    noindex на странице, которой нет и в sitemap, — два согласованных решения
    владельца, а не ошибка шаблона: служебные страницы, юридические, закрытые
    по стране. На живом многоязычном каталоге все 136 критичных noindex были такими и
    вытесняли настоящие беды из «чинить в этом порядке». Закрытая страница,
    которая стоит в sitemap, — противоречие и остаётся критичной.

    `complete=False` — часть sitemap не прочитана: «нет в списке» тогда не
    значит «убрана из sitemap», и критичные noindex не понижаются.
    """
    if not sitemap_urls:
        return issues
    listed = _listed_keys(sitemap_urls)
    # Страницы, которые уже представлены находкой `noindex-group`: поднимать
    # каждую обратно в критичные — считать одно правило шаблона дважды.
    in_group = set()
    for item in issues:
        if item[2] == "noindex-group":
            in_group.update(getattr(item[3], "subject", None) or ())
    out = []
    for item in issues:
        if item[2] == "noindex-group":
            subjects = list(getattr(item[3], "subject", None) or ())
            if (complete and item[0] == "critical" and subjects
                    and not any(k in listed for k in subjects)):
                item = ("info", item[1], item[2], Said(
                    str(item[3]).rstrip(". ") + ". "
                    + tr("В sitemap их нет — похоже на решение, а "
                         "не на ошибку шаблона."), subjects), *item[4:])
            out.append(item)
            continue
        key = url_key(item[1]) if item[1] else ""
        if (complete and item[0] == "critical" and item[2] == "noindex" and key
                and key not in listed):
            item = ("info", item[1], item[2], tr(
                "страница закрыта от индексации и убрана из sitemap — похоже на "
                "решение, а не на ошибку шаблона"), *item[4:])
        elif (item[0] == "info" and item[2] == "noindex" and key in listed
              and key not in in_group
              and _slug(item[1]) not in _CLOSED_BY_DESIGN):
            # Закрытый раздел понижен до сведений ещё при разборе сборки, когда
            # sitemap не было видно. Раздел, который всё ещё отдан в sitemap,
            # — то же противоречие, что и одна такая страница.
            item = ("critical", item[1], item[2], tr(
                "страница закрыта от индексации, но стоит в sitemap — противоречие: "
                "если закрытие не задумано, трафика не будет"), *item[4:])
        out.append(item)
    return out


def _listed_keys(sitemap_urls) -> set:
    listed = set()
    for u in sitemap_urls or ():
        key = url_key(u)
        # `/a/?utm_source=feed` в sitemap — это страница `/a/`, как и в воронке.
        listed |= {key, key.split("?", 1)[0]}
    return listed


SITEMAP_COVERAGE_MIN = 0.5


def closed_against_sitemap(issues: list, notes: list, pages: list, sitemap_urls,
                           complete: bool = True, build: bool = False) -> list:
    """
    `closed_off_map` с проверкой, что sitemap вообще можно верить, и с
    заметками, которые совпадают с тем, что случилось.

    «Нет в sitemap — значит убрана намеренно» верно только для полного
    списка. Устаревший sitemap сборки с одной главной или собранный для
    `localhost:3000` не называет и открытых страниц: по нему любой noindex
    выглядел решением. Если в sitemap меньше половины открытых страниц,
    noindex не понижается, и об этом сказано. Закрытая страница, которая в нём
    стоит, по-прежнему противоречие. Заметка «раздел понижен до сведений»
    снимается, если sitemap поднял его страницы обратно. `build` — sitemap
    взят из сборки, без `--sitemap`.
    """
    if not sitemap_urls:
        return issues
    listed = _listed_keys(sitemap_urls)
    open_keys = {url_key(p.url) for p in pages if indexable(p)}
    covered = len(open_keys & listed)
    sparse = not open_keys or covered < SITEMAP_COVERAGE_MIN * len(open_keys)
    out = closed_off_map(issues, sitemap_urls, complete=complete and not sparse)

    def lowered(after):
        n = 0
        for was, now in zip(issues, after):
            if was[0] == "critical" and now[0] == "info":
                if now[2] == "noindex":
                    n += 1
                elif now[2] == "noindex-group":
                    n += len(getattr(now[3], "subject", None) or ())
        return n

    if complete and sparse and lowered(closed_off_map(issues, sitemap_urls)):
        notes.append(tr(
            "noindex не сверен с sitemap: в нём {a0} из {a1} открытых страниц — "
            "список неполный, устарел или собран для другого адреса. «Нет в "
            "sitemap» по нему не значит «убрана намеренно», и закрытые страницы "
            "остаются критичными", a0=covered, a1=len(open_keys)))
    down = lowered(out)
    if build and down:
        notes.append(tr(
            "noindex сверен с sitemap.xml сборки: {a0} закрытых страниц в нём нет "
            "— это решение, а не ошибка, и они понижены до сведений. Остальная "
            "сверка с sitemap идёт только с --sitemap", a0=down))
    raised = [now[1] for was, now in zip(issues, out)
              if was[0] == "info" and now[0] == "critical" and now[2] == "noindex"]
    if raised:
        paths = []
        for url in raised:
            path = urlsplit(url).path
            paths.append(path if path.endswith("/") else path + "/")
        notes[:] = [n for n in notes if not (
            isinstance(n, _SectionNote) and any(p.startswith(n.section) for p in paths))]
    return out
def stubs_in_sitemap(pages: list, sitemap_urls) -> list:
    """
    Заглушки-редиректы, которые стоят в sitemap. Как страницы они не
    проверяются, поэтому и находки о них нет, а Search Console отметит такой
    адрес как «страница с переадресацией»: в sitemap место цели.
    """
    if not sitemap_urls:
        return []
    listed = set()
    for u in sitemap_urls:
        key = url_key(u)
        listed |= {key, key.split("?", 1)[0]}
    return sorted(p.url for p in pages if p.key in listed and redirect_target(p))


def drop_closed_noise(issues: list, pages: list) -> list:
    """
    Убирает находки о содержимом страниц, закрытых от индекса.

    mdBook кладёт в каждый сайт `print.html` и `toc.html` с noindex, и обе
    получали «нет title», «тонкая», «нет description». Закрытая страница в
    выдаче не появится: её заголовок, объём и первый абзац никому не видны.
    Остаются само закрытие и находки hreflang — они про связи, а не про текст.
    """
    # Закрыта и страница с canonical на другую: печатная копия Hugo
    # получала «тонкая», «нет описания» и «глубоко» — 800 находок на сайте.
    # Страница с ошибочным canonical закрыта не намеренно: о ней важно всё.
    # Так же и canonical на `http://`/`www.`-версию самой страницы.
    closed = ({p.url for p in pages if not indexable(p)} - set(misdirected(pages))
              - {p.url for p in pages if p.__dict__.get("_canonical_origin")
                 and indexable(p, origin=False)})
    if not closed:
        return issues
    # Заглушка-редирект с canonical на цель тоже «закрыта», но редирект в
    # пустоту — её единственная находка, и она остаётся.
    stubs = {p.url for p in pages if p.url in closed and redirect_target(p)}
    return [i for i in issues if i[1] not in closed or i[2] in KEEP_ON_CLOSED
            or (i[2] in ("broken-link", "redirect-home") and i[1] in stubs)]


def apply_ignore(issues: list, ignore: dict, site: str = "") -> tuple:
    """
    Находки, принятые намеренно: `ignore` в indexgap.json.

    `{"noindex": ["/login/", "/search/*"], "ai-crawler-blocked": true,
    "*": ["/drafts/*"]}` — код находки и адреса (шаблоны fnmatch по пути от
    адреса сайта) или `true` для всех. Возвращает (оставшиеся, принятые).
    Принятые не валят `--strict` и не попадают в наряды, но считаются и
    пишутся в JSON отдельно: молча находка не пропадает. Опечатка в коде —
    ошибка со словами: иначе правило тихо не действовало бы.
    """
    import difflib
    import fnmatch
    if not ignore:
        return issues, []
    if not isinstance(ignore, dict):
        raise SourceError(tr("ignore в indexgap.json должен быть объектом: {\"код\": "
                             "[\"/путь/*\"]} или {\"код\": true}"))
    from .report import CODE_HELP
    from .repair import FIX
    known = set(CODE_HELP) | set(FIX) | set(CODE_WEIGHT)
    rules = {}
    for code, value in ignore.items():
        if code.startswith("_"):
            continue
        if code != "*" and code not in known:
            close = difflib.get_close_matches(code, sorted(known), n=1, cutoff=0.7)
            raise SourceError(tr("ignore: кода «{a0}» нет", a0=code)
                              + (tr(" — возможно, имелось в виду «{a0}»", a0=close[0])
                                 if close else ""))
        if value is True:
            rules[code] = True
        elif isinstance(value, list) and all(isinstance(v, str) for v in value):
            rules[code] = value
        else:
            raise SourceError(tr("ignore: у «{a0}» нужен список путей или true, а стоит {a1}",
                                 a0=code, a1=json.dumps(value, ensure_ascii=False)))
    base = urlsplit(site).path.rstrip("/") if site else ""

    def path_of(url):
        # Находка о разделе адресована путём (`/blog/rent/`), а не адресом:
        # префикс сайта снимается и с него, как с адреса страницы.
        path = (url or "") if "://" not in (url or "") else (urlsplit(url).path or "/")
        if base and path.startswith(base + "/"):
            path = path[len(base):]
        return path

    def pattern_of(pattern):
        # Адрес целиком или путь без ведущей косой черты не совпадали ни с чем:
        # сравнивается путь, а он всегда начинается с «/».
        if "://" in pattern:
            pattern = path_of(pattern)
        elif pattern and pattern[0] not in "/*?[":
            pattern = "/" + pattern
        return pattern

    rules = {code: (rule if rule is True else [pattern_of(p) for p in rule])
             for code, rule in rules.items()}
    kept, accepted = [], []
    for issue in issues:
        path = path_of(issue[1])
        hit = False
        for code in (issue[2], "*"):
            rule = rules.get(code)
            if rule is True or (rule and any(
                    fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(path.rstrip("/"), p.rstrip("/"))
                    for p in rule)):
                hit = True
                break
        (accepted if hit else kept).append(issue)
    return kept, accepted


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
                "slot_share", "slot_floor", "slot_token_share"):
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


def redirect_chain(page, by_key: dict, hops: int = 20) -> tuple:
    """
    Куда в итоге ведёт заглушка: (адреса по пути, петля ли). Каждый шаг —
    `redirect_target` следующей заглушки сборки; цель вне сборки или обычная
    страница — конец цепочки.
    """
    chain, seen = [page.url], {page.key}
    current = page
    for _ in range(hops):
        target = redirect_target(current)
        key = url_key(target) if target else ""
        nxt = (by_key.get(key) or by_key.get(key.split("?", 1)[0])) if key else None
        if nxt is None:
            break
        if nxt.key in seen:
            return chain + [nxt.url], True
        chain.append(nxt.url)
        seen.add(nxt.key)
        if not redirect_target(nxt):
            break
        current = nxt
    return chain, False


def redirect_stub_issues(pages: list, home_url: str = None) -> list:
    """
    Заглушки, у которых плоха сама цель, хотя она и есть в сборке.

    Петля заглушек (`/a/` → `/b/` → `/a/`) — ERR_TOO_MANY_REDIRECTS в
    браузере и ошибка для поисковика, а находки о ней не было: каждая цель
    «в сборке есть». Заглушка на главную — мягкий 404 (так же оценивает и
    `diff` правило vercel.json на главную); заглушка с текстом страницы —
    чаще всего ошибка шаблона, превратившая статьи в редиректы.
    """
    by_key = {p.key: p for p in pages}
    home = url_key(home_url) if home_url else ""
    issues = []
    for page in sorted(pages, key=lambda p: p.url):
        target = redirect_target(page)
        if not target:
            continue
        chain, loop = redirect_chain(page, by_key)
        if loop:
            shown = " → ".join(urlsplit(u).path or "/" for u in chain)
            issues.append(("warning", page.url, "broken-link", tr(
                "заглушка-редирект ведёт по кругу: {a0}. Браузер покажет ошибку «слишком "
                "много переадресаций», поисковик страницу не получит", a0=shown)))
            continue
        if home and page.key != home and url_key(target) == home:
            words = len((getattr(page, "text", "") or "").split())
            if words >= 50:
                issues.append(("warning", page.url, "redirect-home", tr(
                    "страница с текстом (около {a0} слов) сразу перебрасывает на главную — "
                    "текста поисковик не увидит, а редирект на главную он считает мягким "
                    "404. Чаще всего это ошибка шаблона", a0=words)))
            else:
                issues.append(("info", page.url, "redirect-home", tr(
                    "заглушка-редирект ведёт на главную — поисковик считает такой "
                    "редирект мягким 404: лучше вести на ближайшую по смыслу страницу")))
    return issues


def run_all(pages: list, home_url: str = None, cfg: dict = None,
            language: str = "", blocked: set = frozenset()) -> dict:
    """
    Единая точка входа: всё, что считается локально, без сети. `blocked` —
    страницы, закрытые в robots.txt (`aeo.blocked_urls`): ссылки с них не в счёт.
    """
    unknown = validate_config(cfg)
    cfg = {**CONFIG, **(cfg or {})}
    graph = link_graph(pages, home_url, blocked)
    words = trimmed_words(pages)
    boiler = boilerplate_profile(pages, cfg, words)
    dupes = find_near_duplicates(pages, cfg, words)
    shells = {p.url for p in pages if is_shell(p, cfg)}
    by_url_all = {p.url: p for p in pages}
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
    issues += canonical_form_issues(pages)
    issues += issues_hreflang
    # Цифры, разошедшиеся между языковыми версиями одной страницы.
    from . import facts
    issues += facts.drift(pages)
    notes = list(dupes["notes"]) + list(multi["notes"]) + unknown
    # Заглушка-редирект без текста — тоже «пустой каркас» по виду, но о ней
    # своя строка ниже: совет про серверный HTML к ней не относится.
    real_shells = sorted(url for url in shells if not redirect_target(by_url_all[url]))
    for url in real_shells:
        issues.append(("critical", url, "js-shell",
                       tr("в исходном HTML нет текста — его рисует JavaScript, а краулеры ИИ-поиска его не исполняют")))
    if real_shells:
        share = len(real_shells) / len(pages) if pages else 0
        notes.append(
            tr("пустых JS-каркасов: {a0} из {a1} ({a2:.0%}). На этих страницах не считались объём текста, уникальность, дубли и ссылки — в исходном HTML их неоткуда взять. Это одна беда, а не четыре: появится серверный HTML — проверки заработают.", a0=len(real_shells), a1=len(pages), a2=share))
    if boiler["skipped"]:
        notes.append(tr("шаблонность не оценивалась: ") + boiler["skipped"])
    mismatch = root_mismatch(pages, graph, urlsplit(home_url).path if home_url else "")
    if mismatch:
        notes.append(mismatch)
    else:
        # При сдвинутом корне битой выглядит каждая ссылка: причина одна,
        # и о ней уже сказано.
        base_path = urlsplit(home_url).path if home_url else ""
        twins = {}
        redirects = {p.url: redirect_target(p) for p in pages if redirect_target(p)}
        for url, paths in sorted(broken_links(pages, graph, base_path, twins).items()):
            if url in redirects:
                # У заглушки в счёт идёт только цель редиректа: остальные её
                # ссылки (шапка в редиректе Next.js) как страницу не проверяют.
                aim = url_key(redirects[url]).split("?", 1)[0]
                paths = [p for p in paths if p == aim]
                if not paths:
                    continue
            shown = ", ".join("/" + p.split("/", 3)[-1] if p.count("/") >= 3 else "/"
                              for p in paths[:3])
            more = tr(" и ещё {a0}", a0=len(paths) - 3) if len(paths) > 3 else ""
            subjects = [url_key(p) for p in paths]
            if url not in redirects:
                issues.append(("warning", url, "broken-link", Said(tr(
                    "ссылок на страницы, которых нет в сборке: {a0} — {a1}{a2}. На живом "
                    "сайте это 404, если сервер их не перенаправляет",
                    a0=len(paths), a1=shown, a2=more), subjects)))
                continue
            # Заглушку как страницу не проверяют, но то, куда она ведёт, —
            # её единственное содержание: эта находка у неё остаётся.
            issues.append(("warning", url, "broken-link", Said(tr(
                "заглушка-редирект ведёт на страницу, которой нет в сборке: {a0}. "
                "На живом сайте это 404 за редиректом", a0=shown), subjects)))
        issues += wrong_form_issues(pages, twins)
        for section, n in missing_sections(pages, graph, base_path):
            notes.append(tr(
                "в раздел {a0} ведут ссылки на {a1} разных страниц, а ни одной страницы "
                "этого раздела в сборке нет. Если раздел собирает этот же генератор, он "
                "выпал из сборки, и на живом сайте это 404; если его отдаёт другое "
                "приложение, всё в порядке.", a0=base_path.rstrip("/") + "/" + section + "/", a1=n))
    issues += redirect_stub_issues(pages, home_url)
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
    # Закрытую в robots.txt страницу назовёт robots-blocks-page; дойти до неё
    # можно, прочитать — нет.
    behind = set(graph.get("behind_robots") or ())
    unfollowed = set(graph.get("behind_nofollow") or ())
    graph["unreachable"] = [u for u in graph["unreachable"]
                            if not (u in behind and u in blocked)]
    for url in graph["unreachable"]:
        issues.append(("critical", url, "unreachable",
                       tr("до страницы ведут только ссылки со страниц, закрытых в robots.txt, "
                          "а их поисковик не читает") if url in behind else
                       tr("до страницы ведут только ссылки nofollow — со страниц с meta "
                          "robots nofollow или с rel=\"nofollow\", — а по ним краулер "
                          "не идёт") if url in unfollowed else
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
        # Близнец из сравнения с образцом группы — артефакт выборки: сменился
        # образец, сменился и он, и --baseline считал новой каждую находку
        # группы. У такой находки предмета нет — она сверяется по странице.
        twins = [] if url in dupes.get("sampled_urls", ()) else [url_key(u) for _, u in found]
        if best >= cfg["near_duplicate"]:
            issues.append(("critical", url, "near-duplicate",
                           Said(tr("совпадает на {a0:.0%} со страницей {a1}{a2} — поисковик оставит в индексе одну", a0=best, a1=other, a2=more), twins)))
        else:
            issues.append(("info", url, "similar",
                           Said(tr("похожа на {a0:.0%} на {a1}{a2}", a0=best, a1=other, a2=more), twins)))

    # Региональные версии одной страницы и не станут дублями: hreflang для того
    # и нужен. Из near-duplicate они уже убраны — и из «вот-вот станут» тоже.
    issues += duplicate_risk([(a, b, j) for a, b, j in dupes["pairs"]
                              if tuple(sorted((a.url, b.url))) not in regional],
                             cfg, skip=bare)

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
    # Региональные версии — тоже: заметка говорит «не дубли», а счётчик и
    # таблица «похожих пар» показывали их красным.
    pairs = [(a, b, j) for a, b, j in dupes["pairs"]
             if a.url not in bare and b.url not in bare
             and tuple(sorted((a.url, b.url))) not in regional]

    # Заглушка-редирект — не страница: человек и поисковик видят то, куда она
    # ведёт. На каталоге виз девять языковых `/connect` и корень давали 40
    # находок «нет title», «JS-оболочка», «canonical на другую» о страницах,
    # которые живой сайт отдаёт кодом 307.
    stubs = {p.url for p in pages if redirect_target(p)}
    if stubs:
        issues = [i for i in issues if i[1] not in stubs or i[2] in ("broken-link", "redirect-home")]
        notes.append(tr(
            "заглушек-редиректов: {a0}. Как страницы они не проверялись — "
            "поисковик видит то, куда они ведут.", a0=len(stubs)))

    from . import signals
    living = [p for p in pages if p.url not in shells]
    issues += signals.page_signals(living)
    issues += signals.lang_script(living)
    issues += signals.stale_years([p for p in living if p.url not in spared],
                                  base_path=urlsplit(home_url).path if home_url else "")
    # Двойник с canonical на другую страницу — не ребёнок, которого хаб забыл.
    from .publish import indexable as _indexable
    issues += signals.hub_links(pages, graph,
                                skip=spared | {p.url for p in pages if not _indexable(p)})
    issues += signals.heavy_images(pages)
    issues = _collapse_parked(issues, notes, pages, cfg)
    issues = _closed_sections(issues, notes, pages)
    issues = drop_closed_noise(issues, pages)

    return {
        "pages": pages,
        "graph": graph,
        "unique_share": boiler["shares"],
        "duplicates": pairs,
        "duplicate_method": dupes["method_id"],
        "duplicate_method_label": dupes["method"],
        # Пары крупных групп-клонов показаны выборкой: «похожих пар» тогда
        # не сравнить с попарным прогоном — 399 клонов дают 79 401 пару.
        "duplicates_sampled": bool(dupes.get("sampled_urls")),
        "issues": sort_issues(issues),
        "notes": notes,
        "config": cfg,
    }
