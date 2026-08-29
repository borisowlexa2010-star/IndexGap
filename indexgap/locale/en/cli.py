# -*- coding: utf-8 -*-
"""cli — English. Всё, что человек видит в терминале."""

MESSAGES = {
    "\n! Адрес сайта определить не удалось. Впиши его в indexgap.json полем `site`, иначе проверять нечего.":
        "\n! Could not determine the site address. Put it in indexgap.json under "
        "`site`, otherwise there is nothing to check.",
    "\nНи одна страничная находка не повторилась в двух проектах.":
        "\nNo page-level finding repeated across two projects.",
    "\nНовый ключ IndexNow для ЭТОГО проекта: {a0}":
        "\nA new IndexNow key for THIS project: {a0}",
    "\nОбщее в настройке сайтов:": "\nShared in how the sites are set up:",
    "\nОбщие грабли на страницах (доля страниц проекта):":
        "\nProblems shared across pages (as a share of each project's pages):",
    "\nОдин интент, разные формулировки (показаны первые 10 из {a0}):":
        "\nOne intent, different wordings (showing the first 10 of {a0}):",
    "\nОтчёт: {a0}\nДанные: {a1}": "\nReport: {a0}\nData: {a1}",
    "\nПочему страницы не в индексе:": "\nWhy pages are not indexed:",
    "\nПрервано.": "\nInterrupted.",
    "\nСводный отчёт: {a0}\nДанные: {a1}": "\nCombined report: {a0}\nData: {a1}",
    "\nСкиллы подхватит агент в этом проекте: Claude Code читает .claude/skills сам.":
        "\nYour agent will pick the skills up in this project: Claude Code reads "
        ".claude/skills on its own.",
    "\nСледующая команда:": "\nNext command:",
    "\nСоздано заготовок: {a0} в {a1}": "\nStubs created: {a0} in {a1}",
    "\nСравнение поисковиков:": "\nEngine by engine:",
    "\nЧто установлено:": "\nWhat was installed:",
    "\nЭто разбор без записи. Чтобы создать заготовки — добавь --write.":
        "\nThis was an audit with nothing written. To create the stubs, add --write.",
    "    Оставлена первая. Если это разные страницы — поправь ключи.":
        "    The first one was kept. If these really are different pages, fix the "
        "keywords.",
    "    Порог, срабатывающий почти на всех страницах всех проектов, —\n    это вопрос к порогу, а не к страницам. Правится в indexgap.json\n    или профилем: `indexgap profiles`.":
        "    A threshold that fires on nearly every page of every project is\n"
        "    a question about the threshold, not about the pages. Change it in\n"
        "    indexgap.json or with a profile: `indexgap profiles`.",
    "    С --send это отправит ВЕСЬ сайт. Если это не то, что нужно, восстанови .indexgap-manifest.json из истории.":
        "    With --send this would submit the WHOLE site. If that is not what you "
        "want, restore .indexgap-manifest.json from history.",
    "    Сверка с sitemap пропущена — это не значит, что страниц в нём нет.":
        "    The sitemap comparison was skipped — that does not mean the pages are "
        "missing from it.",
    "    Укажи каталог публикации: --key-dir ./public":
        "    Name the publish directory: --key-dir ./public",
    "   (угадано — проверь)": "   (guessed — check it)",
    "   (уже был, не тронут)": "   (already there, untouched)",
    "  ! --write-key без --key-dir: файл ключа должен лежать в КОРНЕ САЙТА, а не рядом с исходниками.":
        "  ! --write-key without --key-dir: the key file must sit at the SITE ROOT, "
        "not next to your sources.",
    "  ! sitemap не прочитан: {a0}": "  ! sitemap not read: {a0}",
    "  ! колонка с ключом не названа `keyword` — взята «{a0}». Если это не она, укажи явно: --keyword <имя колонки>":
        "  ! the keyword column is not called `keyword` — took “{a0}”. If that is "
        "the wrong one, say so: --keyword <column name>",
    "  ! манифест был повреждён и прочитан как пустой — у всех страниц будет сегодняшний lastmod":
        "  ! the manifest was corrupt and read as empty — every page will get "
        "today's lastmod",
    "  ! манифест повреждён и прочитан как пустой — очередь считается с нуля.":
        "  ! the manifest is corrupt and was read as empty — the queue starts from "
        "scratch.",
    "  ! файл прочитан как {a0}; для надёжности пересохрани его в UTF-8":
        "  ! the file was read as {a0}; to be safe, re-save it as UTF-8",
    "  ! шардов больше одного: если ./public не корень сайта, укажи --public-prefix, иначе индекс будет ссылаться не туда":
        "  ! more than one shard: if ./public is not the site root, pass "
        "--public-prefix, or the index will point to the wrong place",
    "  (потеряно {a0}: {a1})": "  (lost {a0}: {a1})",
    "  .gitignore — дописаны служебные файлы":
        "  .gitignore — working files appended",
    "  indexgap notify {a0} --site {a1} --key {a2} --write-key --key-dir <каталог публикации>":
        "  indexgap notify {a0} --site {a1} --key {a2} --write-key --key-dir "
        "<publish directory>",
    "  {a0:<24} {a1} проекта: {a2}{a3}": "  {a0:<24} {a1} projects: {a2}{a3}",
    "  {a0} — блок для Codex": "  {a0} — the block for Codex",
    "  · {a0:<20} {a1:>6} стр.  критично {a2:>4}  внимание {a3:>4}  [{a4}]":
        "  · {a0:<20} {a1:>6} pages  critical {a2:>4}  warnings {a3:>4}  [{a4}]",
    "  Не записано строк: {a0}": "  Rows not written: {a0}",
    "  Он привязан к домену файлом в корне сайта. Ключ от другого проекта здесь не сработает — протокол ответит 403.":
        "  It is bound to the domain by a file at the site root. A key from another "
        "project will not work here — the protocol answers 403.",
    "  батч {a0}: {a1}": "  batch {a0}: {a1}",
    "  датасет    {a0}": "  dataset    {a0}",
    "  датасет    не найден — сверка фактов работать не будет":
        "  dataset    not found — fact-checking will not run",
    "  не покрыто → {a0}": "  not covered → {a0}",
    "  не получат → {a0}": "  will not be told → {a0}",
    "  не сопоставлено: {a0} (проверь keyword во фронтматтере или имена папок)":
        "  unmatched: {a0} (check the keyword in the frontmatter, or the folder names)",
    "  он должен открываться как {a0}/{a1}.txt":
        "  it must be reachable at {a0}/{a1}.txt",
    "  сайт       {a0}": "  site       {a0}",
    "  страницы   {a0}": "  pages      {a0}",
    "  тип        {a0}   ({a1})": "  type       {a0}   ({a1})",
    "  удалён устаревший шард: {a0}": "  removed a stale shard: {a0}",
    "  черновиков не опубликовано: {a0} (status: draft во фронтматтере)":
        "  drafts held back: {a0} (status: draft in the frontmatter)",
    "  что это доказывает → {a0}": "  what that proves → {a0}",
    "  ← похоже на непонастроенный порог": "  ← looks like a misconfigured threshold",
    ", просрочено {a0}": ", {a0} stale",
    "--out {a0} уже существует и это не отчёт пакета.\n    Перезаписывать чужой файл я не буду — укажи другое имя.":
        "--out {a0} already exists and is not one of this tool's reports.\n"
        "    I will not overwrite someone else's file — pick another name.",
    "--out {a0} — это каталог. Укажи имя файла, например {a1}":
        "--out {a0} is a directory. Give a file name, for example {a1}",
    "CSV с семантикой": "keyword CSV",
    "JSON с описанием проектов": "JSON describing the projects",
    "URL главной; по умолчанию — сам --site":
        "URL of the home page; defaults to --site itself",
    "URL файла ключа, если он не в корне":
        "URL of the key file, if it is not at the root",
    "[движок=]файл.csv": "[engine=]file.csv",
    "[источник=]файл": "[source=]file",
    "sitemap не прочитан: {a0}\n    Пока он не читается, сверять не с чем — «потеряно всё» в такой ситуации было бы враньём.":
        "sitemap not read: {a0}\n    Until it can be read there is nothing to "
        "compare against — reporting “everything lost” here would be a lie.",
    "{a0} не читается: {a1}.\n    Это файл настроек проекта. Поправь его или удали и запусти `indexgap init` заново.":
        "{a0} cannot be read: {a1}.\n    This is the project settings file. Fix it, "
        "or delete it and run `indexgap init` again.",
    "{a0} — это файл, а нужен каталог со страницами.":
        "{a0} is a file — a directory of pages is needed.",
    "{a0}: ни одной строки с данными.": "{a0}: not a single data row.",
    "В {a0} нет ни одной страницы (.html, .htm, .md, .markdown).\n    Если страницы лежат глубже — укажи нужный подкаталог.":
        "There is not a single page in {a0} (.html, .htm, .md, .markdown).\n"
        "    If the pages sit deeper, name the subdirectory.",
    "Включено: {a0}   Исключено (noindex, canonical, черновики): {a1}":
        "Included: {a0}   Excluded (noindex, canonical, drafts): {a1}",
    "Дальше: попроси агента заполнить их по брифу внутри каждого файла.":
        "Next: ask your agent to fill them in, following the brief inside each file.",
    "Датировано страниц: {a0} из {a1}": "Pages carrying a date: {a0} of {a1}",
    "Если работаешь в Codex — добавь блок в AGENTS.md: `indexgap init --agents`":
        "Working in Codex? Add the block to AGENTS.md: `indexgap init --agents`",
    "Индексация — {a0}": "Indexation — {a0}",
    "К генерации:      {a0}": "To generate:      {a0}",
    "Каталога {a0} нет. Проверь путь.": "There is no {a0} directory. Check the path.",
    "Колонки «{a0}» в {a1} нет.\n    Есть: {a2}\n    Укажи нужную: --keyword <имя колонки>":
        "There is no “{a0}” column in {a1}.\n    There is: {a2}\n"
        "    Name the right one: --keyword <column name>",
    "Колонки с ключевым словом в {a0} не нашлось.\n    Есть: {a1}\n    Укажи нужную: --keyword <имя колонки>":
        "No keyword column was found in {a0}.\n    There is: {a1}\n"
        "    Name the right one: --keyword <column name>",
    "Контроль качества programmatic-конвейера":
        "Quality control for a programmatic SEO pipeline",
    "Критично: {a0}   Внимание: {a1}   Сирот: {a2}   Похожих пар: {a3}":
        "Critical: {a0}   Warnings: {a1}   Orphans: {a2}   Similar pairs: {a3}",
    "Не проверено проектов: {a0}": "Projects not checked: {a0}",
    "Не хватает данных о проекте.\n    Либо укажи их явно: indexgap check ./content --site https://example.com\n    Либо один раз выполни `indexgap init` в корне проекта — тогда\n    ежедневная команда станет просто `indexgap check`.":
        "Not enough is known about the project.\n"
        "    Either say it outright: indexgap check ./content --site https://example.com\n"
        "    Or run `indexgap init` once at the project root — after that\n"
        "    the daily command is just `indexgap check`.",
    "Новых: {a0}   Изменённых: {a1}   Без изменений: {a2}   Пропало: {a3}":
        "New: {a0}   Changed: {a1}   Unchanged: {a2}   Gone: {a3}",
    "Нужен хотя бы --sitemap или --indexed, иначе сверять не с чем.\n    --sitemap ./public/sitemap.xml\n    --indexed google=gsc.csv --indexed bing=bing.csv":
        "At least one of --sitemap or --indexed is needed, otherwise there is "
        "nothing to compare against.\n    --sitemap ./public/sitemap.xml\n"
        "    --indexed google=gsc.csv --indexed bing=bing.csv",
    "Отбраковано:      {a0}": "Rejected:         {a0}",
    "Отправлено, очередь очищена.": "Submitted, the queue is clear.",
    "Отправлять нечего.": "Nothing to submit.",
    "Отчёт: {a0}\nДанные: {a1}": "Report: {a0}\nData: {a1}",
    "Получат уведомление ({a0}): {a1}": "Will be notified ({a0}): {a1}",
    "Принято {a0} из {a1}. Принятые отмечены и повторно не поедут; остальные останутся в очереди.":
        "{a0} of {a1} accepted. The accepted ones are marked and will not be sent "
        "again; the rest stay in the queue.",
    "Проверка перед публикацией": "Pre-publish review",
    "Проверки текста здесь не запускались — это делает `indexgap check`.":
        "Text checks did not run here — `indexgap check` does that.",
    "Проект — ": "Project — ",
    "Проект: {a0}\n": "Project: {a0}\n",
    "Проектов в портфеле: {a0}": "Projects in the portfolio: {a0}",
    "Пропущено (файл уже есть): {a0}": "Skipped (the file already exists): {a0}",
    "Профили типов контента:\n": "Content-type profiles:\n",
    "Профиль — {a0} ({a1})": "Profile — {a0} ({a1})",
    "Прочие источники — {a0}": "Other sources — {a0}",
    "Разбор потерь": "Where the pages went",
    "Разбор целиком: {a0}": "Full breakdown: {a0}",
    "Разобрано страниц: {a0}": "Pages parsed: {a0}",
    "Сверено с датасетом: {a0} из {a1}": "Checked against the dataset: {a0} of {a1}",
    "Строк в датасете: {a0}": "Rows in the dataset: {a0}",
    "Файл ключа: {a0}": "Key file: {a0}",
    "Чинить в этом порядке:": "Fix in this order:",
    "Что понято про проект:": "What was worked out about the project:",
    "Это пробный прогон: {a0} URL готовы к отправке. Чтобы отправить — добавь --send.":
        "This was a dry run: {a0} URLs are ready to submit. To actually send them, "
        "add --send.",

    # ── справка по аргументам ─────────────────────────────────────────────────
    "адрес сайта целиком; по умолчанию из indexgap.json":
        "the full site address; taken from indexgap.json by default",
    "адрес сайта, если определить не удалось":
        "the site address, if it could not be worked out",
    "воронка: сгенерировано → sitemap → индексы поисковиков":
        "the funnel: generated → sitemap → search engine indexes",
    "все локальные проверки и отчёт": "every local check, plus the report",
    "выгрузка индексации; несколько раз для разных поисковиков":
        "an indexation export; repeat it for different engines",
    "выгрузка со списком страниц: панель вебмастера, Ahrefs, Semrush, Screaming Frog, GA4 и другие. CSV, XLSX, JSON или список адресов. Можно указывать несколько раз: --indexed google=gsc.csv --indexed ahrefs=pages.xlsx. Источник определяется сам; метка нужна, когда имя файла ни о чём не говорит":
        "an export listing pages: a webmaster panel, Ahrefs, Semrush, Screaming "
        "Frog, GA4 and others. CSV, XLSX, JSON or a plain list of addresses. Repeat "
        "it as needed: --indexed google=gsc.csv --indexed ahrefs=pages.xlsx. The "
        "source is detected on its own; a label is only needed when the filename "
        "says nothing",
    "действительно отправить; без него — пробный прогон":
        "actually submit; without it this is a dry run",
    "действительно создать файлы": "actually create the files",
    "доля заполненных колонок, ниже которой строка отбраковывается (по умолчанию 0 — не отбраковывать)":
        "the share of filled columns below which a row is rejected (default 0 — "
        "reject nothing)",
    "единиц измерения в датасете нет — сверка идёт по всем числам":
        "the dataset has no units — every number is checked",
    "единицы фактов ({a0}): {a1}": "fact units ({a0}): {a1}",
    "из датасета": "from the dataset",
    "из конфига": "from the config",
    "какие бывают типы контента и чем отличаются":
        "what content types exist and how they differ",
    "каталог для отдельных отчётов по каждому проекту":
        "directory for the per-project reports",
    "каталог проекта": "project directory",
    "каталог публикации": "publish directory",
    "каталог со страницами": "directory of pages",
    "каталог со страницами; по умолчанию из indexgap.json":
        "directory of pages; taken from indexgap.json by default",
    "ключ IndexNow: 8–128 символов латиницы и цифр, который ты придумываешь сам":
        "the IndexNow key: 8–128 latin characters and digits that you invent yourself",
    "колонка с ключом": "the keyword column",
    "колонка с ключом в датасете": "the keyword column in the dataset",
    "конфиг: {a0}": "config: {a0}",
    "куда записать разбор целиком": "where to write the full breakdown",
    "куда класть заготовки": "where to put the stubs",
    "куда писать; по умолчанию рядом со страницами":
        "where to write; next to the pages by default",
    "куда положить файл ключа — это КОРЕНЬ САЙТА":
        "where to put the key file — this is the SITE ROOT",
    "не ходить за реестром участников, взять встроенный список":
        "do not fetch the participant registry, use the built-in list",
    "ненулевой код возврата при критичных находках — для CI":
        "exit non-zero when there are critical findings — for CI",
    "один прогон по нескольким проектам и сводный разбор":
        "one run across several projects, plus a combined breakdown",
    "перезаписать существующий indexgap.json": "overwrite an existing indexgap.json",
    "пропустить проверки машинной читаемости":
        "skip the machine-readability checks",
    "пропустить проверки текста": "skip the text checks",
    "путь или URL sitemap.xml": "path or URL of sitemap.xml",
    "путь или URL sitemap.xml для сверки":
        "path or URL of sitemap.xml to compare against",
    "путь к indexgap.json; по умолчанию ищется рядом со страницами":
        "path to indexgap.json; looked for next to the pages by default",
    "путь к robots.txt проекта": "path to the project's robots.txt",
    "путь, по которому файлы будут доступны на сайте, если --out-dir не корень публикации":
        "the path the files will be served under, if --out-dir is not the publish root",
    "разобрать семантику и разложить заготовки под генерацию":
        "audit the keyword set and lay out stubs for generation",
    "сверка фактов и швов шаблона выключена профилем «{a0}»: страницы не порождаются датасетом, сверять не с чем. Молчание здесь — не «всё хорошо»":
        "the “{a0}” profile switches off fact-checking and template-seam detection: "
        "these pages are not generated from a dataset, so there is nothing to check "
        "against. Silence here does not mean “all good”",
    "сгенерировать новый ключ IndexNow для этого проекта":
        "mint a new IndexNow key for this project",
    "семантика (CSV или XLSX) — включает сверку фактов с данными строк":
        "the keyword set (CSV or XLSX) — switches on fact-checking against the rows",
    "собрать sitemap с шардингом и честным lastmod":
        "build a sitemap with sharding and an honest lastmod",
    "создать AGENTS.md для Codex, если его нет":
        "create AGENTS.md for Codex if it is missing",
    "создать файл ключа": "create the key file",
    "сообщить об изменившихся страницах через IndexNow":
        "tell IndexNow which pages changed",
    "тип контента: catalog, events, ugc, product":
        "content type: catalog, events, ugc, product",
    "тип контента: catalog, events, ugc, product. Меняет пороги и набор проверок — см. `indexgap profiles`":
        "content type: catalog, events, ugc, product. Changes thresholds and which "
        "checks run — see `indexgap profiles`",
    "то же, что --indexed google=... (для совместимости)":
        "the same as --indexed google=... (kept for compatibility)",
    "установить в проект: скиллы для агента и конфиг":
        "install into this project: the agent skills and a config",
    "файл со своим шаблоном брифа вместо стандартного":
        "a file with your own brief template instead of the default",
    "шаблон пути": "path template",
    "язык: {a0}": "language: {a0}",
    "не определён": "not detected",
}
