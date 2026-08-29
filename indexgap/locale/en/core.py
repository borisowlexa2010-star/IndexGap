# -*- coding: utf-8 -*-
"""core, freshness, publish, portfolio, engines, install — English."""

MESSAGES = {
    # ── core ──────────────────────────────────────────────────────────────────
    "--site {a0} — так не годится: нужен полный адрес со схемой.\n    Попробуй: --site https://{a1}":
        "--site {a0} won't do: a full address with the scheme is required.\n"
        "    Try: --site https://{a1}",
    "{a0} и {a1} дают один URL {a2} — взят {a3}, второй пропущен":
        "{a0} and {a1} produce the same URL {a2} — kept {a3}, skipped the other",
    "{a0}: не удалось определить кодировку. Пересохрани файл в UTF-8.":
        "{a0}: could not determine the encoding. Re-save the file as UTF-8.",
    "{a0}: файл не читается ({a1}).":
        "{a0}: cannot read the file ({a1}).",
    "Не указан адрес сайта. Добавь --site https://example.com":
        "No site address given. Add --site https://example.com",
    "файл прочитан как {a0}, а не UTF-8":
        "read as {a0}, not UTF-8",
    "фронтматтер не распознан":
        "frontmatter not recognised",
    "фронтматтер открыт, но не закрыт: строка `---` в конце блока":
        "frontmatter opened but never closed — a `---` line is missing at the end",

    # ── settings ──────────────────────────────────────────────────────────────
    "{a0}: ожидался объект верхнего уровня.":
        "{a0}: expected an object at the top level.",
    "Не удалось прочитать {a0}: {a1}": "Could not read {a0}: {a1}",

    # ── freshness ─────────────────────────────────────────────────────────────
    "дата {a0} прошла более {a1} дней назад, а страница открыта для индексации — поисковик показывает людям то, чего уже нет. Закрой noindex, поставь редирект на актуальную или перепиши в отчёт о прошедшем":
        "the date {a0} passed more than {a1} days ago and the page is still open "
        "to indexing — the engine is showing people something that no longer "
        "exists. Close it with noindex, redirect to the current one, or rewrite "
        "it as a report on what happened",
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
    "{a0}\n## SEO-конвейер\n\nВ проекте установлен indexgap. Профиль контента — `{a1}`, страницы в `{a2}`.\n\nПеред публикацией сгенерированных страниц:\n\n```bash\nindexgap check {a3} --site {a4}{a5}\n```\n\nПолные инструкции — в `.claude/skills/indexgap-*/SKILL.md`: разбор семантики (`indexgap-plan`), проверка перед публикацией (`indexgap-review`), sitemap и IndexNow (`indexgap-publish`), несколько сайтов сразу (`indexgap-portfolio`).\n{a6}":
        "{a0}\n## SEO pipeline\n\nThis project has indexgap installed. Content "
        "profile: `{a1}`, pages in `{a2}`.\n\nBefore publishing generated "
        "pages:\n\n```bash\nindexgap check {a3} --site {a4}{a5}\n```\n\nFull "
        "instructions live in `.claude/skills/indexgap-*/SKILL.md`: keyword "
        "planning (`indexgap-plan`), the pre-publish review (`indexgap-review`), "
        "sitemap and IndexNow (`indexgap-publish`), several sites at once "
        "(`indexgap-portfolio`).\n{a6}",
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
    "у {a0} из {a1} страниц есть дата во фронтматтере":
        "{a0} of {a1} pages carry a date in their frontmatter",
}
