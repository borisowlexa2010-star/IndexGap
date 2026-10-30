# -*- coding: utf-8 -*-
"""summary — English. Сводка прогона для страницы сборки в CI."""

MESSAGES = {
    "к сведению": "info",
    "### indexgap: {a0} страниц(ы), {a1}": "### indexgap: {a0} pages, {a1}",
    "Против базовой линии: новых {a0}, из них критичных {a1}; исчезло {a2}.":
        "Against the baseline: new {a0}, critical among them {a1}; gone {a2}.",
    "**Новые находки**": "**New findings**",
    "**Новые критичные находки**": "**New critical findings**",
    "- … и ещё {a0}": "- … and {a0} more",
    "**Чаще всего**": "**Most frequent**",
    "уровень": "level",
    "код": "code",
    "страниц": "pages",
    "Находок нет.": "No findings.",
    "использование: python -m indexgap.summary indexgap-check.json (или indexgap-diff.json)":
        "usage: python -m indexgap.summary indexgap-check.json (or indexgap-diff.json)",
    "{a0}: это не данные прогона indexgap check или diff":
        "{a0}: this is not data from an indexgap check or diff run",
    "{a0}: это данные indexgap {a1}, а сводка строится по данным indexgap check или diff":
        "{a0}: this is data from indexgap {a1}, but the summary is built from indexgap "
        "check or diff data",
    "### indexgap diff: {a0} → {a1} страниц(ы), {a2}":
        "### indexgap diff: {a0} → {a1} pages, {a2}",
    "Находки check: новых критичных {a0}, новых «внимание» {a1}; исчезло критичных {a2}.":
        "check findings: new critical {a0}, new warnings {a1}; critical gone {a2}.",
    "**Критичное**": "**Critical**",
    "Разницы, которая ломает индекс, нет.": "Nothing in the difference breaks the index.",
}
