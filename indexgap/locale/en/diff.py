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
    "новых страниц: {a0}": "new pages: {a0}",
    "страницы нет, редирект ведёт на {a0} — а этой страницы в новой сборке тоже нет":
        "the page is gone and redirects to {a0} — which is not in the new build either",
    "страницы нет, редирект на {a0}": "the page is gone, redirected to {a0}",
    "была открыта для индекса, в новой сборке её нет и редиректа нет — на живом сайте будет 404":
        "it was open to indexing, it is not in the new build and nothing redirects it — "
        "the live site will answer 404",
    "страницы нет; она и раньше была закрыта от индекса":
        "the page is gone; it was already closed to indexing",
}
