# -*- coding: utf-8 -*-
"""core, freshness, publish, portfolio, engines, install — English."""

MESSAGES = {
    "{a0} файл(ов) HTML — куски шаблонов без <html> и <title>, а не страницы; не проверялись: {a1}":
        "{a0} HTML file(s) are template fragments with no <html> or <title>, not "
        "pages; not checked: {a1}",
    "каталоги со служебными именами пропущены, страницы в них не проверялись: {a0}":
        "directories with service names were skipped and their pages not checked: {a0}",
    " и ещё {a0}": " and {a0} more",
    "{a0} различаются только регистром букв: на macOS, Windows и хостинге без учёта регистра один файл затрёт другой":
        "{a0} differ only in letter case: on macOS, Windows and case-insensitive hosts "
        "one file overwrites the other",
    "каталог {a0}/ пропущен как сборочный. Если проверять нужно собранный сайт — передай его каталог явно.":
        "the {a0}/ directory was skipped as build output. If the built site is "
        "what you want checked, pass that directory explicitly.",
    # ── core ──────────────────────────────────────────────────────────────────
    "--site {a0} — так не годится: нужен полный адрес со схемой.\n    Попробуй: --site https://{a1}":
        "--site {a0} won't do: a full address with the scheme is required.\n"
        "    Try: --site https://{a1}",
    "--site {a0} — так не годится: в адресе сайта не бывает «?» и «#».\n    Попробуй: --site {a1}":
        "--site {a0} won't do: a site address has no “?” or “#”.\n"
        "    Try: --site {a1}",
    "{a0}: значение `{a1}` должно быть списком строк, а там {a2}.":
        "{a0}: the value of `{a1}` must be a list of strings, but it is {a2}.",
    "{a0} и {a1} дают один URL {a2} — взят {a3}, второй пропущен":
        "{a0} and {a1} produce the same URL {a2} — kept {a3}, skipped the other",
    "{a0} файл(ов) .md рядом со сборкой HTML — это файлы, которые сайт отдаёт как есть, а не страницы; не проверялись: {a1}":
        "{a0} .md file(s) beside the built HTML are files the site serves as they "
        "are, not pages; not checked: {a1}",
    "{a0}: не удалось определить кодировку. Пересохрани файл в UTF-8.":
        "{a0}: could not determine the encoding. Re-save the file as UTF-8.",
    "{a0}: файл не читается ({a1}).":
        "{a0}: cannot read the file ({a1}).",
    "Не указан адрес сайта. Добавь --site https://example.com":
        "No site address given. Add --site https://example.com",
    "в файле {a0} байт(а) не в UTF-8 — на их месте знак замены; остальной текст прочитан как UTF-8":
        "the file has {a0} byte(s) that are not UTF-8 — they show as the replacement "
        "character; the rest of the text was read as UTF-8",
    "{a0}: каталог не прочитан ({a1}) — страницы в нём не проверялись":
        "{a0}: the directory could not be read ({a1}) — its pages were not checked",
    "canonical не разбирается как адрес: {a0}": "the canonical cannot be parsed as an address: {a0}",
    "на странице {a0} разных canonical: {a1} — поисковик не учтёт ни один. Оставь один в <head>":
        "the page has {a0} different canonicals: {a1} — the search engine will use none of "
        "them. Keep one in <head>",
    "canonical в <body> ({a0}) поисковик не читает — перенеси его в <head>":
        "the search engine does not read a canonical in <body> ({a0}) — move it into <head>",
    "{a0}: шаблон {a1} не разобран — какие страницы закрывает его X-Robots-Tag: noindex, не проверялось":
        "{a0}: pattern {a1} could not be read — which pages its X-Robots-Tag: noindex "
        "closes was not checked",
    "{a0} закрывает от индекса {a1} страниц(ы) заголовком X-Robots-Tag: noindex — правило {a2}":
        "{a0} closes {a1} page(s) to indexing with an X-Robots-Tag: noindex header — rule {a2}",
    "файл прочитан как {a0}, а не UTF-8":
        "read as {a0}, not UTF-8",
    "в <meta charset> объявлен UTF-8, а файл в {a0}: браузер и поисковик покажут вместо букв знаки «�». Пересохрани файл в UTF-8":
        "<meta charset> declares UTF-8, but the file is {a0}: browsers and search engines "
        "will show “�” instead of the letters. Re-save the file as UTF-8",
    "в <meta charset> объявлен {a0}, а файл в UTF-8: если сервер не присылает charset в Content-Type, браузер покажет кракозябры. Исправь объявление на utf-8":
        "<meta charset> declares {a0}, but the file is UTF-8: unless the server sends a "
        "charset in Content-Type, browsers will show garbled text. Change the declaration "
        "to utf-8",
    "фронтматтер не распознан":
        "frontmatter not recognised",
    "фронтматтер открыт, но не закрыт: строка `---` в конце блока":
        "frontmatter opened but never closed — a `---` line is missing at the end",

    # ── settings ──────────────────────────────────────────────────────────────
    "{a0}: ожидался объект верхнего уровня.":
        "{a0}: expected an object at the top level.",
    "Не удалось прочитать {a0}: {a1}": "Could not read {a0}: {a1}",
    "нужно число не меньше 0": "a number of at least 0 is needed",
    "нужно конечное число не больше 100000000": "a finite number no greater than 100000000 is needed",
    "записан в {a0}": "saved in {a0}",
    "{a0} {a1}: такого {a2} нет ни в {a3}, ни в рабочем каталоге.":
        "{a0} {a1}: no such {a2} in {a3} or in the working directory.",
    "каталога": "directory",
    "файла": "file",
    "поле «{a0}» в indexgap.json мне не знакомо и не действует":
        "field “{a0}” in indexgap.json is not one I know and has no effect",

    # ── freshness ─────────────────────────────────────────────────────────────
    "дата {a0} прошла более {a1} дней назад, а страница открыта для индексации — поисковик показывает людям то, чего уже нет. Закрой noindex, поставь редирект на актуальную или перепиши в отчёт о прошедшем":
        "the date {a0} passed more than {a1} days ago and the page is still open "
        "to indexing — the engine is showing people something that no longer "
        "exists. Close it with noindex, redirect to the current one, or rewrite "
        "it as a report on what happened",
    "дата {a0} прошла более {a1} дней назад, но на странице есть и бессрочная серия ({a2}), поэтому сама страница актуальна. Убери прошедшее событие из разметки и текста или перенеси его в архив":
        "the date {a0} passed more than {a1} days ago, but the page also carries "
        "an open-ended series ({a2}), so the page itself is current. Remove the "
        "past event from the markup and the text, or move it to an archive",
    "дата {a0} прошла, страница уже закрыта от индексации — это правильно":
        "the date {a0} has passed and the page is already closed to indexing — "
        "that is correct",
    "даты нашлись только у {a0} страниц из {a1}. Для датированного контента это мало: без машиночитаемой даты нельзя ни проверить актуальность, ни показать её в выдаче":
        "only {a0} pages out of {a1} carry a date. For dated content that is too "
        "few: without a machine-readable date you can neither check freshness nor "
        "show it in the results",

    # ── publish ───────────────────────────────────────────────────────────────
    "URL не принадлежат указанному host, либо ключ не совпадает":
        "the URLs do not belong to the given host, or the key does not match",
    "Ключ IndexNow — это 8–128 символов из латиницы, цифр и дефиса, которые ты придумываешь сам (например uuid без скобок).\n    Он же станет именем файла в корне сайта: /<ключ>.txt":
        "An IndexNow key is 8–128 characters of latin letters, digits and hyphens "
        "that you invent yourself (a uuid without braces works).\n"
        "    It also becomes a file at the site root: /<key>.txt",
    "ключ не найден по keyLocation — проверь, что файл лежит в корне и доступен":
        "the key was not found at keyLocation — check that the file is at the "
        "site root and publicly reachable",
    "неверный формат запроса":
        "malformed request",
    "неизвестная ошибка":
        "unknown error",
    "остановился, чтобы не усугублять; принятые батчи сохранены":
        "stopped rather than make it worse; the batches already accepted are kept",
    "слишком часто — притормози и повтори позже":
        "too many requests — slow down and retry later",

    # ── portfolio ─────────────────────────────────────────────────────────────
    ".\n    Обязательные: name (имя), root (каталог со страницами), site (адрес сайта со схемой).":
        ".\n    Required: name, root (the directory with the pages), "
        "site (the site address including the scheme).",
    "sitemap не прочитан: {a0}":
        "sitemap not read: {a0}",
    "{a0}: имя проекта «{a1}» повторяется.":
        "{a0}: the project name “{a1}” appears twice.",
    "{a0}: не разбирается как JSON ({a1}, строка {a2}).":
        "{a0}: not valid JSON ({a1}, line {a2}).",
    "{a0}: ожидался список проектов в поле `projects`.":
        "{a0}: expected a list of projects in the `projects` field.",
    "{a0}: проект №{a1} — не объект.":
        "{a0}: project #{a1} is not an object.",
    "{a0}: у проекта №{a1} нет полей ":
        "{a0}: project #{a1} is missing the fields ",
    "Проверка — {a0}":
        "Checking — {a0}",
    "robots.txt в сборке не действует: сайт живёт под /{a0}/, а поисковики читают только {a1}://{a2}/robots.txt. Правила из него не проверялись; настоящий файл хоста можно назвать полем `robots` проекта":
        "the robots.txt in the build has no effect: the site lives under /{a0}/, and "
        "search engines read only {a1}://{a2}/robots.txt. Its rules were not checked; "
        "the host's real file can be named in the project's `robots` field",
    "Файл портфеля {a0} не найден.":
        "Portfolio file {a0} not found.",
    "в {a0} нет ни одной страницы":
        "no pages found in {a0}",
    "профиль «{a0}» рассчитан на страницы из датасета, но датасет не указан — сверка фактов не выполнялась":
        "the “{a0}” profile expects pages generated from a dataset, but no "
        "dataset was given — fact-checking did not run",
    "сверка фактов и швов шаблона выключена профилем: страницы не порождаются датасетом, сверять не с чем":
        "the profile switches off fact-checking and template-seam detection: "
        "these pages are not generated from a dataset, so there is nothing to "
        "check against",

    # ── engines ───────────────────────────────────────────────────────────────
    "встроенный список": "built-in list",
    "кэш": "cache",
    "не поддерживает IndexNow. Остаются sitemap и Search Console — проверка индексации в отчёте, отправка через интерфейс.":
        "does not support IndexNow. That leaves the sitemap and Search Console — "
        "indexation is checked in the report, submission goes through the web UI.",
    "реестр indexnow.org": "the indexnow.org registry",
    "своя система подачи, требует отдельной регистрации.":
        "has its own submission system and needs a separate registration.",

    # ── install ───────────────────────────────────────────────────────────────
    "{a0}\n## SEO-конвейер\n\nВ проекте установлен indexgap. Профиль контента — `{a1}`, страницы в `{a2}`.\n\nПеред публикацией сгенерированных страниц:\n\n```bash\nindexgap check {a3} --site {a4}{a5}\n```\n\nПолные инструкции — в `.claude/skills/indexgap-*/SKILL.md`: разбор семантики (`indexgap-plan`), проверка перед публикацией (`indexgap-review`), sitemap и IndexNow (`indexgap-publish`), несколько сайтов сразу (`indexgap-portfolio`), ИИ-поиск и цитирование (`indexgap-cite`).\n{a6}":
        "{a0}\n## SEO pipeline\n\nThis project has indexgap installed. Content "
        "profile: `{a1}`, pages in `{a2}`.\n\nBefore publishing generated "
        "pages:\n\n```bash\nindexgap check {a3} --site {a4}{a5}\n```\n\nFull "
        "instructions live in `.claude/skills/indexgap-*/SKILL.md`: keyword "
        "planning (`indexgap-plan`), the pre-publish review (`indexgap-review`), "
        "sitemap and IndexNow (`indexgap-publish`), several sites at once "
        "(`indexgap-portfolio`), AI search and citations (`indexgap-cite`).\n{a6}",
    "{a0} страниц без явных признаков другого типа":
        "{a0} pages with no clear sign of another type",
    "{a0} страниц, почти все собранный HTML — похоже на лендинги":
        "{a0} pages, nearly all of them built HTML — looks like landing pages",
    "Каталога {a0} нет.":
        "There is no {a0} directory.",
    "Настройки этого проекта. Профиль задаёт пороги по типу контента; всё, что написано здесь явно, сильнее профиля. Ключ IndexNow сюда не пишется: он свой у каждого сайта.":
        "Settings for this project. The profile sets thresholds by content type; "
        "anything written here explicitly beats the profile. The IndexNow key is "
        "never written here: every site has its own.",
    "в пакете не оказалось ни одного скилла":
        "the package shipped without any skills",
    "датасета нет, {a0} из {a1} страниц короткие — похоже на ленту":
        "no dataset, and {a0} of {a1} pages are short — looks like a feed",
    "задан флагом": "given by a flag",
    "каталог страниц не найден, взят профиль по умолчанию":
        "no content directory found, falling back to the default profile",
    "не найден каталог скиллов внутри пакета — переустанови indexgap":
        "the skills directory is missing from the installed package — reinstall indexgap",
    "рядом лежит датасет {a0}": "a dataset sits next to it: {a0}",
    "страниц не найдено, взят профиль по умолчанию":
        "no pages found, falling back to the default profile",
    "у {a0} из {a1} страниц есть дата события":
        "{a0} of {a1} pages carry an event date",
    'canonical {a0} из {a1} страниц называют сайт адресом {a2}, а --site — {a3}. Страницы сверены с {a2}; адреса в sitemap и в отчёте строятся от --site — если сайт живёт по {a2}, укажи --site {a2}':
        'the canonical of {a0} of {a1} pages names the site {a2}, but --site is {a3}. Pages were compared against {a2}; addresses in the sitemap and in the report are built from --site, so if the site lives at {a2}, pass --site {a2}',
    '{a0} страниц(ы) в каталоге с именем кода ответа (…/404/) никто не ссылается — сочтены страницами ошибки, не проверялись и в sitemap не попадут: {a1}. Если это статьи — поставь на них ссылку':
        '{a0} page(s) in a directory named after a status code (…/404/) are not linked from anywhere — taken for error pages, not checked, and left out of the sitemap: {a1}. If they are articles, link to them',
    'поле «{a0}» проекта мне не знакомо и не действует':
        'project field “{a0}” is not one I know and has no effect',
    '{a0}: не удалось записать или прочитать ({a1}).':
        '{a0}: could not write or read it ({a1}).',
    'Колонки «{a0}» в {a1} нет.\n    Есть: {a2}\n    Укажи нужную: поле `keyword` проекта':
        "There is no “{a0}” column in {a1}.\n    There is: {a2}\n    Name the right one: the project's `keyword` field",
    'колонка с ключом не названа `keyword` — взята «{a0}». Если это не она, укажи поле `keyword` проекта':
        "the keyword column is not called `keyword` — took “{a0}”. If that is not it, set the project's `keyword` field",
    'Колонки с ключевым словом в {a0} не нашлось.\n    Есть: {a1}\n    Укажи нужную: поле `keyword` проекта':
        "No keyword column was found in {a0}.\n    There is: {a1}\n    Name the right one: the project's `keyword` field",
    'нужно число дней не больше 36500':
        'a number of days no larger than 36500 is needed',
}
