# -*- coding: utf-8 -*-
"""hreflang и всё, что про многоязычность, — English."""

MESSAGES = {
    "hreflang взят из sitemap для {a0} страниц(ы): в самих страницах его нет или он неполный":
        "hreflang was taken from the sitemap for {a0} page(s): the pages "
        "themselves carry none or only part of it",
    "{a0} открыт(ых) страниц всё ещё называют их в своём hreflang — убрать нужно и оттуда.":
        "{a0} open page(s) still name them in their own hreflang — remove them "
        "there as well.",
    "У {a0} из них canonical ведёт на страницу, которой среди файлов нет.":
        "For {a0} of them the canonical points at a page that is not among the files.",
    "«{a0}» — не код страны по ISO 3166-1":
        "“{a0}” is not an ISO 3166-1 country code",
    "основной": "default",
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
    "по тому же пути есть страница на другом языке ({a0}), а эта не объявляет ни одной альтернативы. Если это перевод — свяжи их hreflang; если под каждый рынок написан свой текст, связывать не нужно":
        "a page at the same path exists in another language ({a0}), and this one "
        "declares no alternate at all. If it is a translation, link them with "
        "hreflang; if each market has its own text, there is nothing to link",
    "{a0} открыт(ых) страниц без hreflang и без пары на другом языке по тому же пути. Ошибкой не считается: hreflang нужен только переводам. Если переводы есть, но под другим адресом, — свяжи их вручную.":
        "{a0} open page(s) have no hreflang and no counterpart in another "
        "language at the same path. That is not counted as an error: hreflang is "
        "only for translations. If translations exist under a different address, "
        "link them by hand.",
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
    "Версии кластера противоречат друг другу: один код у двух адресов или разные коды у одного.":
        "The versions of a cluster contradict each other: one code for two "
        "addresses, or different codes for one.",
    "Адреса в hreflang записаны без схемы и хоста.":
        "hreflang addresses are written without a scheme and host.",
    "адреса в hreflang записаны не полностью ({a0}) — поисковики требуют полный адрес со схемой и хостом, например {a1}":
        "hreflang addresses are not fully qualified ({a0}) — search engines "
        "require the full address with scheme and host, for example {a1}",
    "код «{a0}» объявлен для нескольких адресов ({a1}) — у одного кода может быть только одна версия, и противоречивую разметку поисковик отбрасывает":
        "the code “{a0}” is declared for several addresses ({a1}) — one code "
        "can have only one version, and search engines discard contradictory "
        "markup",
    "альтернатива {a0} объявлена здесь как «{a1}», а сама она называет себя «{a2}» — версии кластера расходятся в том, на каком она языке":
        "the alternate {a0} is declared here as “{a1}”, while it calls itself "
        "“{a2}” — the versions of the cluster disagree about its language",
    "{a0}: текст страницы не украинский, а рядом в кластере — английская версия. Для Великобритании нужен код `en-GB`":
        "{a0}: the page text is not Ukrainian, and the cluster has an English "
        "version next to it. The United Kingdom needs the code `en-GB`",
    "по тому же пути есть страница на другом языке ({a0}), а hreflang этой страницы называет только её саму. Если это перевод — перечисли в нём все языковые версии":
        "a page at the same path exists in another language ({a0}), and this "
        "page's hreflang names only the page itself. If it is a translation, "
        "list every language version in it",
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
    '{a0} ссылок hreflang стоят в <body> — поисковики читают их только из <head>, и связи между версиями для них нет. Перенеси разметку в <head>':
        '{a0} hreflang links sit in <body> — search engines read them only from <head>, so they link no versions. Move the markup into <head>',
    '{a0} ссылается обратно на {a1} — это другой адрес (схема или хост не те, что у остальных ссылок сайта). Поисковик требует точный адрес версии, а не его редирект':
        "{a0} links back to {a1} — a different address (the scheme or host differs from the rest of the site's links). Search engines need the exact address of the version, not a redirect to it",
    'ссылки hreflang ведут на {a0}, а сами страницы в canonical называют себя адресами {a1} ({a2} из {a3}). Каждая альтернатива — редирект, а не версия, и поисковик отбрасывает кластер. Чинится один раз, в шаблоне hreflang':
        'hreflang links point at {a0}, while the pages name themselves {a1} in their canonical ({a2} of {a3}). Every alternate is a redirect, not a version, and search engines drop the cluster. Fix it once, in the hreflang template',
    'self-ссылка в кластере записана как {a0} — это другой адрес (схема или хост не те, что у остальных ссылок сайта), то есть редирект, а не сама страница. Поисковик требует точный адрес версии':
        "the cluster's self-link is written as {a0} — a different address (the scheme or host differs from the rest of the site's links), so it is a redirect, not the page itself. Search engines need the exact address of the version",
    '{a0} ссылается обратно на {a1}, а сама страница называет себя {a2} — это другой адрес (слэш на конце или index.html), то есть редирект. Поисковик требует точный адрес версии':
        '{a0} links back to {a1}, while the page names itself {a2} — a different address (the trailing slash or index.html), so it is a redirect. Search engines need the exact address of the version',
}
