# -*- coding: utf-8 -*-
"""diff — English. Что меняется между двумя сборками."""

MESSAGES = {
    "страница выпала из индексируемых": "the page dropped out of the indexable set",
    "появился noindex: meta robots «{a0}»": "noindex appeared: meta robots “{a0}”",
    "canonical теперь ведёт на {a0}": "the canonical now points to {a0}",
    "страница стала черновиком": "the page became a draft",
    "страница стала заглушкой-редиректом на {a0}": "the page became a redirect stub to {a0}",
    "появился запрет сниппета: страница останется в индексе, но пропадёт из ответов ИИ-поиска":
        "a snippet ban appeared: the page stays indexed but disappears from AI-search answers",
    "текста стало меньше на {a0:.0%}: {a1} → {a2} слов":
        "text shrank by {a0:.0%}: {a1} → {a2} words",
    "{a0} изменился на {a1} страницах из {a2}; например {a3}: «{a4}» → «{a5}»":
        "{a0} changed on {a1} of {a2} pages; for example {a3}: “{a4}” → “{a5}”",
    "страница стала открытой для индекса": "the page became open to indexing",
    "редирект на главную поиск считает мягким 404: страница выпадет из индекса":
        "search engines treat a redirect to the home page as a soft 404: the page drops out "
        "of the index",
    "а цепочка редиректов приводит к странице, закрытой от индекса: {a0}":
        "and the redirect chain ends on a page closed from indexing: {a0}",
    "а дальше редиректы идут по кругу": "and from there the redirects go round in a loop",
    "новых страниц: {a0}": "new pages: {a0}",
    "страницы нет, редирект ведёт на {a0} — а этой страницы в новой сборке тоже нет":
        "the page is gone and redirects to {a0} — which is not in the new build either",
    "страницы нет, редирект на {a0}": "the page is gone, redirected to {a0}",
    "была открыта для индекса, в новой сборке её нет и редиректа нет — на живом сайте будет 404":
        "it was open to indexing, it is not in the new build and nothing redirects it — "
        "the live site will answer 404",
    "страницы нет; она и раньше была закрыта от индекса":
        "the page is gone; it was already closed to indexing",
    "страница стала заглушкой-редиректом на {a0} — а этой страницы в новой сборке нет":
        "the page became a redirect stub to {a0} — which is not in the new build",
    "страница есть в новой сборке, но правило из {a0} срабатывает раньше файла и уводит её на "
    "{a1} — а этой страницы в новой сборке нет":
        "the page is in the new build, but a rule in {a0} runs before the file and sends it to "
        "{a1} — which is not in the new build",
    "страница есть в новой сборке, но правило из {a0} срабатывает раньше файла и уводит её на {a1}":
        "the page is in the new build, but a rule in {a0} runs before the file and sends it to {a1}",
    "страница есть в новой сборке, но правило из {a0} срабатывает раньше файла и отвечает кодом {a1}":
        "the page is in the new build, but a rule in {a0} runs before the file and answers {a1}",
    "страница есть в новой сборке, но правило из {a0} срабатывает раньше файла и отдаёт по её "
    "адресу главную с кодом 200 — это мягкий 404":
        "the page is in the new build, but a rule in {a0} runs before the file and serves the "
        "home page at its address with 200 — a soft 404",
    "была открыта для индекса, в новой сборке её нет, а правило из {a0} отдаёт по этому адресу "
    "главную с кодом 200 — это мягкий 404":
        "it was open to indexing, it is not in the new build, and a rule in {a0} serves the home "
        "page at its address with 200 — a soft 404",
    "была открыта для индекса, в новой сборке её нет, а правило из {a0} отвечает по этому адресу "
    "кодом {a1}":
        "it was open to indexing, it is not in the new build, and a rule in {a0} answers {a1} "
        "at its address",
}
