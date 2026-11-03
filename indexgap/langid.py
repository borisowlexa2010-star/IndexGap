# -*- coding: utf-8 -*-
"""
Язык текста по частым служебным словам — без словарей и зависимостей.

Письменность (`signals.text_script`) отличает русский от арабского, но не
немецкий от английского, арабский от фарси и урду, индонезийский от
малайского. А непереведённая страница многоязычного сайта — это как раз
английский текст под `lang="de"` или индонезийский под `lang="ms"`: шаблон
перевели, тело — нет.

Служебные слова («the», «und», «که», «کے», «bisa») составляют треть любого
текста и почти не пересекаются между языками; там, где пересекаются
(индонезийский и малайский), в списках стоят именно различающие слова.
Вердикт выносится только при запасе: лучший язык набирает заметно больше
второго, а слов в тексте достаточно. Иначе — «не знаю».
"""

from __future__ import annotations

import re

# Слова пишутся в нижнем регистре; для арабицы — как есть.
STOPWORDS = {
    "en": "the of and to in is that for it with as was on are be this by not or have "
          "from at an but they which you your will can all their has more if about "
          "would there what when been its also who into than",
    "de": "der die und in den von zu das mit sich des auf für ist im dem nicht ein eine "
          "als auch es an werden aus er hat dass sie nach wird bei einer um am sind noch "
          "wie einem über so zum kann oder",
    "fr": "le la les de des et en du un une est pour que qui dans ne pas sur au par plus "
          "avec ce il se sont vous ou elle aux nous mais leur cette être été sa son",
    "es": "el la de que y en los las del se por un una para con no es al lo como más pero "
          "sus su le ya o este fue ha sí porque esta son entre cuando muy sin sobre",
    "it": "il di che la e per un in è non una sono del con le si da al lo della gli dei "
          "anche più ma come nel alla questo delle ha nella essere sul",
    "pt": "de que o a e do da em um para é com não uma os no se na por mais as dos como "
          "mas foi ao ele das tem à seu sua ou ser quando muito há nos já está",
    "nl": "de het een en van in is dat op te zijn met voor niet aan er ook als bij door "
          "maar om dan zou of wordt worden deze naar heeft hun",
    "sv": "och i att det som en på är av för med till den har de inte om ett men var jag "
          "sig så under från vid också eller",
    "da": "og i at det er en til på af med for den som de ikke har et kan vi var men fra "
          "jeg også skal eller når",
    "pl": "i w na z że do się nie to jest o jak po co ale od za czy przez dla jego są być "
          "tak już może jej oraz",
    "cs": "a v se na je že to s z do o i jako ale pro jsou by po k jeho jak tak už jen "
          "byl ve od které",
    "tr": "ve bir bu da de için ile çok gibi daha ne olarak olan kadar ama en sonra her "
          "veya değil var mı nasıl şu",
    "ro": "și de la în a cu pe că nu un o din care este pentru mai sau se fi ce sunt "
          "dar după prin acest",
    "vi": "và của là có không được cho trong các người một những với này đã để khi từ "
          "đến cũng thì như ra",
    # Индонезийский и малайский: общих слов много, различающие — в конце.
    "id": "yang dan di ini itu dengan untuk tidak dari dalam akan pada juga ke karena "
          "bisa sudah saja agar tetapi kami anda harus jika atau lebih seperti oleh "
          "dapat telah setelah selama",
    "ms": "yang dan di ini itu dengan untuk tidak dari dalam akan pada juga ke kerana "
          "boleh sudah sahaja supaya tetapi kami anda perlu jika atau lebih seperti oleh "
          "dapat telah selepas semasa ialah bagi",
    "ru": "и в не на что с по это как а из к у от для о же за то так но бы все только "
          "его или уже если вы при был",
    "uk": "і в не на що з до це як а та від для у за то так але б все тільки його або "
          "вже якщо ви при був",
    # Арабица: три языка одним письмом.
    "ar": "في من على أن إلى التي الذي هذا عن مع هذه كان ما لا هو قد ذلك بين كما أو "
          "عند تم لم إذا يمكن",
    "fa": "و در به از که این را با است برای آن یک می تا شود هم شده یا اما بر نیز "
          "باید کنید شما",
    "ur": "کے میں ہے کی اور سے کو یہ کا نے پر ہیں بھی کہ ایک ہو کر گا آپ جو اس "
          "لیے ساتھ",
    "hi": "के है में की और से को का एक यह पर हैं भी लिए कि नहीं या तो आप जो कर इस "
          "हो साथ",
    "bn": "এবং এই একটি করে থেকে না জন্য হয় আপনি যে কি তার করা আর হবে সঙ্গে বা "
          "ও কিন্তু এর",
}
WORDS = {lang: set(text.split()) for lang, text in STOPWORDS.items()}

# Пары, которые отличаются в основном различающими словами: для них порог мягче.
CLOSE = {frozenset(p) for p in (("id", "ms"), ("ru", "uk"), ("da", "sv"), ("es", "pt"),
                                ("cs", "pl"))}

MIN_TOKENS = 40

# Для близких пар служебных слов мало: индонезийский и малайский делят почти
# все. Различают их обиходные слова, и сайт на двух языках сам их показывает:
# paspor/pasport, tim/pasukan, periksa/semak, kantor/pejabat.
DISTINCT = {
    "id": set("paspor tim periksa kantor bisa karena saja agar silakan setelah "
              "selama hari uang mobil anda harus kartu formulir rincian dukungan "
              "pembayaran sekarang tetapi bagaimana".split()),
    "ms": set("pasport pasukan semak pejabat boleh kerana sahaja supaya sila selepas "
              "semasa wang kereta perlu kad borang butiran sokongan bayaran sekarang "
              "tetapi bagaimana ialah".split()),
}
for _a, _b in (("id", "ms"),):
    _shared = DISTINCT[_a] & DISTINCT[_b]
    DISTINCT[_a] -= _shared
    DISTINCT[_b] -= _shared


def tokens(text: str) -> list:
    """
    Слова текста. Разбор — общий с остальным пакетом: в деванагари и
    бенгальском знак гласной — отдельный символ, и выражение по буквам
    резало «रुपये» на «र», «प», «य».
    """
    from .core import tokenize
    return [t.lower() for t in tokenize(text or "") if not t.isdigit()]


def identify(text: str, candidates=None, min_tokens: int = MIN_TOKENS) -> tuple:
    """
    (язык, доля служебных слов, запас над вторым) или ("", 0, 0), если
    вердикта нет: слов мало, служебных почти нет или два языка идут вровень.
    """
    words = tokens(text)
    if len(words) < min_tokens:
        return "", 0.0, 0.0
    langs = [l for l in (candidates or WORDS) if l in WORDS]
    scores = {}
    for lang in langs:
        vocab = WORDS[lang]
        scores[lang] = sum(1 for w in words if w in vocab) / len(words)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked or ranked[0][1] < 0.08:
        return "", 0.0, 0.0
    best, share = ranked[0]
    if len(ranked) > 1 and {best, ranked[1][0]} <= set(DISTINCT):
        # Близкая пара — решают различающие слова, а не служебные.
        a, b = best, ranked[1][0]
        hits = {l: sum(1 for w in words if w in DISTINCT[l]) for l in (a, b)}
        top = max(hits, key=hits.get)
        other = b if top == a else a
        if hits[top] >= 3 and hits[top] >= 2 * hits[other]:
            return top, scores[top], (hits[top] / hits[other]) if hits[other] else float("inf")
        return "", share, 1.0
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = share / second if second else float("inf")
    needed = 1.15 if len(ranked) > 1 and frozenset((best, ranked[1][0])) in CLOSE else 1.5
    if margin < needed:
        return "", share, margin
    return best, share, margin


def primary(lang: str) -> str:
    """`pt-BR` → `pt`, `zh_Hans` → `zh`; пусто, если не код языка."""
    match = re.match(r"\s*([A-Za-z]{2,3})(?:[-_]|$)", lang or "")
    return match.group(1).lower() if match else ""


def mismatch(declared: str, text: str) -> str:
    """
    Язык текста, если он уверенно другой, чем объявленный — и пакет оба
    языка знает. Иначе пусто: неизвестный язык не повод для находки.
    """
    want = primary(declared)
    if want not in WORDS:
        return ""
    got, _, _ = identify(text)
    return got if got and got != want else ""
