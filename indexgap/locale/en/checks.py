# -*- coding: utf-8 -*-
"""checks, sources, profiles — English."""

MESSAGES = {
    # ── checks ────────────────────────────────────────────────────────────────
    " и ещё {a0}": " and {a0} more",
    "H1 на странице {a0}, нужен один": "{a0} H1 headings on the page, one is needed",
    "`{a0}` — на {a1} страницах из {a2} ({a3:.0%}). Это свойство шаблона, а не список страниц: чинится один раз в шаблоне и исчезает везде.":
        "`{a0}` — on {a1} pages out of {a2} ({a3:.0%}). That is a property of the "
        "template, not a list of pages: fix it once in the template and it is "
        "gone everywhere.",
    "canonical указывает на {a0} — страница отдаёт вес другой":
        "canonical points at {a0} — this page hands its weight to another one",
    "description {a0} символов": "description is {a0} characters",
    "title {a0} символов": "title is {a0} characters",
    "title {a0} символов, обрежется в выдаче":
        "title is {a0} characters — it will be cut off in the results",
    "{a0} групп(ы) страниц оказались настолько похожи, что сравнивались с образцом группы, а не попарно — иначе счёт занял бы часы. Пары внутри такой группы показаны не все.":
        "{a0} group(s) of pages were so alike that they were compared against a "
        "representative of the group rather than pairwise — otherwise the count "
        "would take hours. Not every pair inside such a group is listed.",
    "{a0} кликов от главной — краулер доходит редко":
        "{a0} clicks from the home page — crawlers rarely get that far",
    "в исходном HTML нет текста — его рисует JavaScript, а краулеры ИИ-поиска его не исполняют":
        "no text in the source HTML — JavaScript draws it, and AI-search crawlers "
        "do not execute JavaScript",
    "главной страницы нет среди разобранных файлов, поэтому глубина клика и недостижимость не считались. Проверь --site и корень каталога.":
        "the home page is not among the parsed files, so click depth and "
        "unreachability were not computed. Check --site and the root directory.",
    "до страницы нельзя дойти от главной по ссылкам":
        "the page cannot be reached from the home page by following links",
    "запрещён сниппет: страница может быть в индексе, но в ответы ИИ-поиска и в расширенную выдачу не попадёт":
        "snippets are forbidden: the page may sit in the index, but it will not "
        "appear in AI-search answers or rich results",
    "на странице нет заголовков": "the page has no headings",
    "нет H1 — поисковику нечем определить, о чём страница":
        "no H1 — the engine has nothing to tell what the page is about",
    "нет meta description": "no meta description",
    "нет title": "no title",
    "нет данных": "no data",
    "ни одна внутренняя ссылка не ведёт на страницу":
        "no internal link points at this page",
    "объём текста ≈ {a0} — тонкая страница":
        "about {a0} words of text — a thin page",
    "попарное сравнение": "pairwise comparison",
    "похожа на {a0:.0%} на {a1}{a2}": "{a0:.0%} similar to {a1}{a2}",
    "похоже, каталог не соответствует корню сайта: ссылки на страницах короче их собственных адресов на один сегмент. Из-за этого все страницы выглядят сиротами, и такой же сдвиг уедет в sitemap.\n    Проверь, какой каталог отображается в корень {a0} — сейчас это {a1}":
        "the directory does not seem to match the site root: links on the pages "
        "are one segment shorter than the pages' own addresses. That makes every "
        "page look orphaned, and the same shift will end up in the sitemap.\n"
        "    Check which directory maps to the root of {a0} — right now it is {a1}",
    "почти-дубли образуют {a0} групп(ы), в самой большой {a1} страниц. Чинится по группам: одна остаётся, остальные переписываются под другой интент или отдают ей canonical.":
        "the near-duplicates form {a0} group(s), the largest holding {a1} pages. "
        "Fix them by group: one page stays, the rest are rewritten for a "
        "different intent or point their canonical at it.",
    "пустых JS-каркасов: {a0} из {a1} ({a2:.0%}). На этих страницах не считались объём текста, уникальность, дубли и ссылки — в исходном HTML их неоткуда взять. Это одна беда, а не четыре: появится серверный HTML — проверки заработают.":
        "empty JavaScript shells: {a0} of {a1} ({a2:.0%}). Text volume, "
        "uniqueness, duplicates and links were not measured on these pages — "
        "there is nothing in the source HTML to measure. This is one problem, "
        "not four: once server-rendered HTML appears, the checks start working.",
    "совпадает на {a0:.0%} со страницей {a1}{a2} — поисковик оставит в индексе одну":
        "{a0:.0%} identical to {a1}{a2} — the engine will keep one of them",
    "страниц {a0}, для оценки шаблонности нужно хотя бы {a1} — на меньшей выборке результат меняется от одной добавленной страницы":
        "{a0} pages, and at least {a1} are needed to judge boilerplate — on a "
        "smaller sample one added page changes the answer",
    "страница закрыта от индексации — если это не задумано, трафика не будет":
        "the page is closed to indexing — unless that is deliberate, there will "
        "be no traffic",
    "такой же description ещё у {a0} страниц": "{a0} other pages share this description",
    "такой же title ещё у {a0} страниц": "{a0} other pages share this title",
    "только {a0:.0%} текста уникально — остальное шаблон":
        "only {a0:.0%} of the text is unique — the rest is template",
    "шаблонность не оценивалась: ": "boilerplate was not measured: ",

    # ── sources ───────────────────────────────────────────────────────────────
    "{a0} — это каталог, а нужен файл выгрузки.":
        "{a0} is a directory — an export file is needed.",
    "{a0}: в книге нет ни одного листа.": "{a0}: the workbook has no sheets.",
    "{a0}: файл начинается как zip-архив, но не открывается ни как xlsx, ни как книга Excel. Если это архив выгрузки — распакуй его и передай файл изнутри; если книга — пересохрани её или отдай CSV.":
        "{a0}: the file starts like a zip archive but opens neither as xlsx nor "
        "as an Excel workbook. If it is an export archive, unpack it and pass the "
        "file inside; if it is a workbook, re-save it or give CSV instead.",
    "Есть хотя бы в одном источнике": "In at least one source",
    "Известно поисковику или было посещено": "Known to an engine, or visited",
    "Известно стороннему сервису (не индекс поисковика)":
        "Known to a third-party service (not a search engine's index)",
    "Найдено краулером (это обход, а не индекс)":
        "Found by a crawler (that is a crawl, not an index)",
    "Файл не найден: {a0}": "File not found: {a0}",
    "Хотя бы в одном индексе": "In at least one index",
    "Яндекс.Вебмастер": "Yandex.Webmaster",
    "аналитика": "analytics",
    "карта сайта": "sitemap",
    "краулер": "crawler",
    "краулер дошёл до страницы — это обход, а не индексация":
        "a crawler reached the page — that is a crawl, not indexation",
    "на страницу был визит, значит она в индексе; молчание не значит обратного":
        "the page had a visit, so it is indexed; silence does not prove the opposite",
    "панель вебмастера": "webmaster panel",
    "поисковик знает про страницу — прямой ответ":
        "the engine knows about the page — a direct answer",
    "просто перечень адресов — что он значит, знаешь только ты":
        "just a list of addresses — only you know what it means",
    "список адресов": "list of addresses",
    "сторонний индекс": "third-party index",
    "страница есть в индексе стороннего сервиса, а не поисковика":
        "the page is in a third-party service's index, not a search engine's",

    # ── profiles ──────────────────────────────────────────────────────────────
    "\n    Что они значат — в README, раздел «Профили».":
        "\n    What they mean is in the README, section “Content-type profiles”.",
    "Афиша, расписания, площадки. Страницы живут недолго: главная беда не дубли, а прошедшее событие, оставшееся в индексе.":
        "Listings, schedules, venues. These pages are short-lived: the main "
        "problem is not duplication but an event that has passed while the page "
        "stays in the index.",
    "В настройках проекта раздел `{a0}` должен быть объектом с порогами, а не {a1}.\n    Путь к страницам записывается полем `pages`, не `content` — поправь indexgap.json.":
        "In the project settings the `{a0}` section must be an object of "
        "thresholds, not {a1}.\n    The path to the pages goes in the `pages` "
        "field, not `content` — fix indexgap.json.",
    "Главное здесь — тонкие страницы и глубина: обсуждение из двух реплик индексировать нечем, а лента прячет старое глубоко.":
        "What matters here is thin pages and depth: a two-reply thread has "
        "nothing to index, and a feed buries older items deep.",
    "Даты обязаны быть машиночитаемыми: в JSON-LD `Event.startDate` или во фронтматтере. Иначе ни проверить, ни показать в выдаче.":
        "Dates must be machine-readable: in JSON-LD `Event.startDate` or in the "
        "frontmatter. Otherwise they can neither be checked nor shown in results.",
    "Десятки страниц, а не тысячи. Дубли не проблема; проблема — машинная читаемость и попадание в ответы ИИ-поиска.":
        "Dozens of pages, not thousands. Duplication is not the issue; machine "
        "readability and getting into AI-search answers are.",
    "Здесь окупается AEO-часть: прямой ответ в первом абзаце, вопросные подзаголовки, валидная разметка, открытые ИИ-краулеры.":
        "This is where the AEO checks pay off: a direct answer in the first "
        "paragraph, question-shaped subheadings, valid markup, AI crawlers not "
        "blocked.",
    "Каталог или справочник": "Catalogue or directory",
    "Лендинги продукта или SaaS": "Product or SaaS landing pages",
    "На двух десятках страниц статистика дублей и шаблонности недостоверна — пакет это скажет сам, и спорить не надо.":
        "Across twenty pages the duplicate and boilerplate statistics are not "
        "reliable — the tool says so itself, and it is right.",
    "Обсуждения, отзывы, публикации людей. Страницы не порождаются датасетом, поэтому половина проверок пакета здесь неприменима — и честнее их выключить, чем показывать пустой результат.":
        "Threads, reviews, things people posted. These pages are not generated "
        "from a dataset, so half the checks do not apply — and switching them off "
        "is more honest than showing an empty result.",
    "Одинаковый скелет заголовков на всех страницах — первый признак того, что шаблон вытеснил содержание.":
        "The same heading skeleton on every page is the first sign that the "
        "template has crowded out the content.",
    "Пользовательский контент и лента": "User-generated content and feeds",
    "Профиль «{a0}» неизвестен. Доступны: ": "Unknown profile “{a0}”. Available: ",
    "Прошедшее событие, открытое для индексации, — мусор в выдаче и удар по доверию. Проверка `stale-event` смотрит именно это.":
        "An event that has passed while still open to indexing is junk in the "
        "results and a hit to trust. That is exactly what `stale-event` looks at.",
    "Сверка фактов здесь главная: цифры на странице обязаны быть в строке датасета.":
        "Fact-checking matters most here: a number on the page must exist in the "
        "dataset row.",
    "Сверка фактов не делается: датасета нет, сверять не с чем. Если пакет промолчал — это не «всё хорошо», это «нечем проверять».":
        "Fact-checking does not run: there is no dataset to check against. "
        "Silence here does not mean “all good”, it means “nothing to check with”.",
    "События и даты": "Events and dates",
    "Страницы порождаются строками данных: города, страны, услуги, товары. Классический programmatic — то, ради чего пакет и писался.":
        "Pages generated from data rows: cities, countries, services, products. "
        "Classic programmatic SEO — what this package was written for.",
    "Шаблонность почти не показательна: общая обвязка ленты одинакова по определению.":
        "Boilerplate tells you almost nothing here: a feed's shared chrome is "
        "identical by definition.",
}
