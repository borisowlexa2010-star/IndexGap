# -*- coding: utf-8 -*-
"""content, generate — English."""

MESSAGES = {
    # ── content ───────────────────────────────────────────────────────────────
    " и ещё": " and more",
    " и ещё {a0}": " and {a0} more",
    "status: {a0} — страница помечена как незаконченная":
        "status: {a0} — the page is marked unfinished",
    "{a0} страниц(ы) подошли сразу к нескольким строкам датасета — сверка фактов для них не делалась. Добавь `keyword` во фронтматтер, чтобы связь была однозначной.":
        "{a0} page(s) matched more than one dataset row, so fact-checking was "
        "skipped for them. Add a `keyword` to the frontmatter to make the link "
        "unambiguous.",
    "в тексте есть числа, которых нет в данных: ":
        "the text contains numbers that are not in your data: ",
    "неинформативные анкоры: ": "uninformative anchors: ",
    "первые слова текста совпадают ещё у {a0} страниц":
        "{a0} other pages open with the same words",
    "страниц {a0} — мало для оценки шаблонности":
        "{a0} pages — too few to judge boilerplate",
    "те же {a0} заголовков в том же порядке ещё у {a1} страниц":
        "the same {a0} headings in the same order on {a1} other pages",
    "числа, которых нет в данных — просмотри глазами: ":
        "numbers that are not in your data — read these with your own eyes: ",
    "швы шаблона не оценивались: ": "template seams were not measured: ",

    # ── generate ──────────────────────────────────────────────────────────────
    "  (нет)": "  (none)",
    " в датасете нет.\n    Доступны: ":
        " is not in the dataset.\n    Available: ",
    " — останется только последняя из одноимённых":
        " — only the last of the same-named columns will survive",
    '---\ntitle: ""\ndescription: ""\nkeyword: {keyword_yaml}\nstatus: draft\n---\n\n<!-- БРИФ ДЛЯ АГЕНТА. Удали этот блок, когда страница написана.\n\nКлюч: {keyword}\nДанные строки:\n{variables}\n\nТребования:\n  * title {title_min}–{title_max} символов, содержит ключ,\n    не совпадает с другими страницами;\n  * description {desc_min}–{desc_max} символов, без повтора title;\n  * не меньше {min_words} слов осмысленного текста;\n  * первый абзац — прямой ответ на запрос, 40–320 символов, без разгона\n    вроде «в этой статье мы рассмотрим»: именно его цитируют ИИ-поиск\n    и блок быстрых ответов;\n  * структура — под данные строки и под то, что человеку нужно решить\n    на этой странице. НЕ переноси одни и те же разделы со страницы на страницу:\n    одинаковый скелет заголовков читается как штамповка;\n  * минимум {min_links} ссылки на соседние страницы этого раздела,\n    анкоры описательные — иначе страница останется сиротой;\n  * ничего не выдумывать. Каждое число должно быть в данных строки.\n    Если данных нет, раздел не пишем.\n-->\n':
        '---\ntitle: ""\ndescription: ""\nkeyword: {keyword_yaml}\nstatus: draft\n'
        '---\n\n<!-- BRIEF FOR THE AGENT. Delete this block once the page is '
        'written.\n\nKeyword: {keyword}\nRow data:\n{variables}\n\nRequirements:\n'
        '  * title {title_min}–{title_max} characters, contains the keyword,\n'
        '    and does not match any other page;\n'
        '  * description {desc_min}–{desc_max} characters, not a repeat of the '
        'title;\n'
        '  * at least {min_words} words of text that says something;\n'
        '  * the first paragraph is a direct answer to the query, 40–320\n'
        '    characters, with no run-up like "in this article we will look at":\n'
        '    that paragraph is what AI search and the featured-answer block quote;\n'
        '  * structure follows the row data and what the reader needs to decide\n'
        '    on this page. Do NOT carry the same sections from page to page:\n'
        '    an identical heading skeleton reads as stamping;\n'
        '  * at least {min_links} links to neighbouring pages of this section,\n'
        '    with descriptive anchors — otherwise the page stays an orphan;\n'
        '  * invent nothing. Every number must exist in the row data.\n'
        '    If the data is missing, the section does not get written.\n-->\n',
    "--brief: в шаблоне есть подстановка {a0}, которой пакет не знает.\n    Доступны: keyword, keyword_yaml, variables, min_words, min_links, title_min, title_max, desc_min, desc_max.\n    Если нужны фигурные скобки как текст — удвой их: {{{{ и }}}}.":
        "--brief: the template uses a placeholder {a0} the package does not know.\n"
        "    Available: keyword, keyword_yaml, variables, min_words, min_links, "
        "title_min, title_max, desc_min, desc_max.\n"
        "    If you need literal braces, double them: {{{{ and }}}}.",
    "--pattern «{a0}»: {a1}. Фигурные скобки должны быть парными, а внутри них — имя колонки.":
        "--pattern “{a0}”: {a1}. Braces must be balanced, with a column name inside.",
    "--pattern «{a0}»: колонок ": "--pattern “{a0}”: column ",
    "slug совпадает с «{a0}»": "slug collides with “{a0}”",
    "{a0} — это каталог, а нужен файл с ключами.":
        "{a0} is a directory — a file of keywords is needed.",
    "{a0}: в книге нет данных.": "{a0}: the workbook has no data.",
    "{a0}: не удалось прочитать шапку — файл пустой?":
        "{a0}: could not read the header row — is the file empty?",
    "Файл {a0} не найден. Проверь путь и имя.":
        "File {a0} not found. Check the path and the name.",
    "в {a0} строк(ах) колонок больше, чем в шапке — лишнее отброшено (строки {a1}{a2})":
        "{a0} row(s) have more columns than the header — the extras were dropped "
        "(rows {a1}{a2})",
    "в шаблоне пути пустое значение колонки — заполни её или убери из --pattern":
        "the path template hit an empty column value — fill the column in or take "
        "it out of --pattern",
    "в шапке повторяются колонки: ": "the header repeats columns: ",
    "заполнено {a0} из {a1} полей": "{a0} of {a1} fields filled in",
    "ключ не содержит ни одной буквы или цифры":
        "the keyword contains no letter or digit at all",
    "колонка «{a0}» пуста в {a1} строках из {a2}":
        "column “{a0}” is empty in {a1} rows out of {a2}",
    "колонка «{a0}» пуста во всех строках — её можно удалить из файла":
        "column “{a0}” is empty in every row — it can be removed from the file",
    "пустой ключ": "empty keyword",
    "тот же интент, что и у другой строки":
        "same intent as another row",
    "точный дубль ключа": "exact duplicate keyword",
    "шаблон пути: {a0}": "path template: {a0}",
    "шаблон уводит файл за пределы --out-dir":
        "the template puts the file outside --out-dir",
}
