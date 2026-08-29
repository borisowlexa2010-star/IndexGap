# -*- coding: utf-8 -*-
"""hreflang и всё, что про многоязычность, — English."""

MESSAGES = {
    # ── коды ──────────────────────────────────────────────────────────────────
    "пустой код": "empty code",
    " — вероятно, имелось в виду `{a0}`": " — you probably meant `{a0}`",
    "«{a0}» не похож на код языка: ожидается вид `en`, `pt-BR`, `zh-Hant-TW` или `x-default`":
        "“{a0}” does not look like a language code: expected the shape `en`, "
        "`pt-BR`, `zh-Hant-TW` or `x-default`",
    "«{a0}» не является кодом языка по ISO 639-1":
        "“{a0}” is not an ISO 639-1 language code",
    "«uk» — это украинский язык, а не Великобритания":
        "“uk” is the Ukrainian language, not the United Kingdom",
    "«gb» — это страна, а не язык: перед ней нужен язык":
        "“gb” is a country, not a language: it needs a language in front of it",
    "«us» — это страна, а не язык: перед ней нужен язык":
        "“us” is a country, not a language: it needs a language in front of it",
    "«eu» — не язык и не страна по ISO 3166-1":
        "“eu” is neither a language nor an ISO 3166-1 country",
    "«cn» — это страна, а не язык: перед ней нужен язык":
        "“cn” is a country, not a language: it needs a language in front of it",
    "«jp» — это страна, код языка — «ja»":
        "“jp” is a country; the language code is “ja”",
    "«br» — это бретонский язык, а не Бразилия":
        "“br” is the Breton language, not Brazil",
    "«in» — устаревший код индонезийского, а не Индия":
        "“in” is the deprecated code for Indonesian, not India",
    "«ua» — это страна, код украинского языка — «uk»":
        "“ua” is a country; the Ukrainian language code is “uk”",
    "у альтернативы «{a0}» пустой href":
        "the “{a0}” alternate has an empty href",

    # ── кластер ───────────────────────────────────────────────────────────────
    "в кластере нет ссылки на саму эту страницу — без self-ссылки Google считает кластер невалидным целиком":
        "the cluster has no link to this page itself — without a self-reference "
        "Google treats the whole cluster as invalid",
    "страница ссылается на {a0}, а та не ссылается обратно. Односторонняя связь не «учитывается частично» — она отбрасывается вся":
        "this page links to {a0}, and that page does not link back. A one-way "
        "link is not “partly counted” — the whole link is discarded",
    "альтернатива {a0} не найдена среди разобранных страниц — проверить взаимность нельзя":
        "the alternate {a0} is not among the parsed pages — reciprocity cannot "
        "be verified",
    "альтернатива {a0} закрыта от индексации или отдаёт canonical другой странице — кластер указывает на то, чего в индексе не будет":
        "the alternate {a0} is closed to indexing, or its canonical points "
        "elsewhere — the cluster points at something that will not be in the index",
    "canonical ведёт на версию другого языка ({a0}) — это отменяет hreflang: поисковик склеит версии вместо того, чтобы показывать нужную":
        "the canonical points at a different language version ({a0}) — that "
        "cancels hreflang: the engine will collapse the versions instead of "
        "showing the right one",
    "self-ссылка объявлена как «{a0}», а страница объявляет lang=«{a1}»":
        "the self-reference is declared as “{a0}” while the page declares "
        "lang=“{a1}”",
    "на сайте есть версии на разных языках, а у этой страницы нет ни одной альтернативы — поисковик не узнает, что версии связаны":
        "the site has versions in several languages, and this page declares no "
        "alternate at all — the engine will not learn that the versions belong "
        "together",
    "ни одна страница не объявляет `x-default`. Он не обязателен, но именно он говорит, что показать тому, чей язык не совпал ни с одним объявленным.":
        "no page declares `x-default`. It is not required, but it is what tells "
        "the engine which version to show someone whose language matches none of "
        "the declared ones.",

    # ── гео ───────────────────────────────────────────────────────────────────
    "региональных пар (один язык, разные страны): {a0}. Они законно похожи почти дословно — это работа hreflang, а не повод ставить canonical.":
        "regional pairs (same language, different countries): {a0}. They are "
        "legitimately near-identical — that is what hreflang is for, not a reason "
        "to set a canonical.",
    "{a0} пар(ы) не попали в дубли: это версии одной страницы для разных стран на одном языке, связанные hreflang. Для них canonical — ошибка.":
        "{a0} pair(s) were kept out of the duplicates: they are versions of one "
        "page for different countries in the same language, linked by hreflang. "
        "A canonical between them would be a mistake.",
    "языков на сайте: {a0} ({a1}). Объём текста и длины title и description считаются по письменности каждой страницы, а не по языку сайта.":
        "languages on this site: {a0} ({a1}). Text volume and the title and "
        "description lengths are measured by each page's script, not by the "
        "site's language.",
    "`{a0}` — на {a1} страницах языка «{a2}» из {a3}, то есть почти на всех. По сайту это лишь {a4:.0%}, но чинится один раз: в шаблоне этой языковой версии.":
        "`{a0}` — on {a1} of the {a3} pages in “{a2}”, so on nearly all of them. "
        "Across the site that is only {a4:.0%}, but it is fixed once: in that "
        "language version's template.",

    # ── описания кодов в отчёте ───────────────────────────────────────────────
    "В кластере hreflang нет ссылки на саму страницу. Без self-ссылки кластер невалиден целиком.":
        "The hreflang cluster has no link to the page itself. Without a "
        "self-reference the whole cluster is invalid.",
    "Односторонняя связь hreflang: обратной ссылки нет. Google отбрасывает такую связь, а не учитывает частично.":
        "A one-way hreflang link: there is no link back. Google discards such a "
        "link rather than counting it partly.",
    "Альтернатива указывает на страницу, которой нет среди разобранных — взаимность не проверить.":
        "The alternate points at a page that is not among the parsed ones — "
        "reciprocity cannot be checked.",
    "Альтернатива закрыта от индексации или отдаёт canonical другой странице.":
        "The alternate is closed to indexing, or its canonical points elsewhere.",
    "Canonical ведёт на другую языковую версию — это отменяет hreflang.":
        "The canonical points at another language version — that cancels hreflang.",
    "Код языка в hreflang неверен — частая подмена языка страной.":
        "The hreflang language code is wrong — usually a country code where a "
        "language belongs.",
    "Код в self-ссылке не совпадает с lang страницы.":
        "The code in the self-reference does not match the page's lang.",
    "Сайт мультиязычный, а у страницы нет ни одной альтернативы.":
        "The site is multilingual and this page declares no alternate at all.",

    "{a0} страниц из {a1} объявляют один и тот же набор альтернатив ({a2}) и ни одна не ссылается на себя. Шаблон печатает кластер главной на каждой странице — для поисковика связей между версиями нет вообще. Чинится один раз, в шаблоне.":
        "{a0} pages out of {a1} declare the same set of alternates ({a2}) and not "
        "one of them references itself. The template prints the home page's "
        "cluster on every page — as far as a search engine is concerned there are "
        "no links between the versions at all. Fixed once, in the template.",
    "Шаблон печатает один и тот же кластер hreflang на всех страницах — связей между версиями нет.":
        "The template prints the same hreflang cluster on every page — there are "
        "no links between the versions.",

    # ── обновлённая справка ───────────────────────────────────────────────────
    "язык вывода: en или ru. По умолчанию — из INDEXGAP_LANG или системной локали, иначе английский":
        "output language: en or ru. By default from INDEXGAP_LANG or the system "
        "locale, otherwise English",
}
