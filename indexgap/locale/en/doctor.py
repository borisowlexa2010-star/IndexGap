# -*- coding: utf-8 -*-
"""doctor, aeo — English."""

MESSAGES = {
    # ── doctor ────────────────────────────────────────────────────────────────
    "\n    В файле только относительные пути — передай --site.":
        "\n    The file holds only relative paths — pass --site.",
    "\n    Нужен экспорт, где есть столбец с адресами (в Search Console — «Страницы», не «Запросы»).":
        "\n    An export with a column of addresses is needed (in Search Console "
        "that is “Pages”, not “Queries”).",
    "  из них в {a0}{a1}": "  of those in {a0}{a1}",
    "noindex или canonical на другую страницу":
        "noindex, or a canonical pointing elsewhere",
    "{a0} не читается: {a1}": "{a0} cannot be read: {a1}",
    "{a0} отдал {a1}": "{a0} returned {a1}",
    "{a0}: {a1} адресов были относительными путями — достроены до {a2}/…":
        "{a0}: {a1} addresses were relative paths — completed against {a2}/…",
    "{a0}: {a1} строк содержат пути вида /guide/… без домена, а --site не задан — они пропущены. Передай --site, чтобы их учесть.":
        "{a0}: {a1} rows hold paths like /guide/… with no domain and --site was not "
        "given, so they were skipped. Pass --site to count them.",
    "{a0}: в файле нет ни одного <loc>": "{a0}: the file has no <loc> at all",
    "{a0}: колонка «{a1}» нашлась, но ни одного адреса в ней нет.":
        "{a0}: the “{a1}” column was found, but it holds no addresses.",
    "{a0}: не нашёл колонку с адресами страниц.\n    Заголовки файла: ":
        "{a0}: could not find a column of page addresses.\n    File headers: ",
    "{a0}: не удалось распаковать gzip ({a1})": "{a0}: could not unpack gzip ({a1})",
    "{a0}: не удалось уверенно определить источник, файл засчитан как «{a1}» ({a2}). Если это не так, укажи явно: --indexed google={a3} или --indexed ahrefs={a4}":
        "{a0}: could not identify the source with confidence, the file was counted "
        "as “{a1}” ({a2}). If that is wrong, say so explicitly: --indexed "
        "google={a3} or --indexed ahrefs={a4}",
    "{a0}: файл пустой.": "{a0}: the file is empty.",
    "{a0}: это не похоже на XML ({a1})": "{a0}: this does not look like XML ({a1})",
    "В sitemap": "In the sitemap",
    "Пригодно к индексации": "Indexable",
    "Сгенерировано": "Generated",
    "Хотя бы в одном индексе": "In at least one index",
    "без title": "no title",
    "в шаг засчитаны источники, которые индексом не являются ({a0}). Реальную индексацию показывают строки панелей: {a1}.":
        "this step counts sources that are not an index ({a0}). Real indexation is "
        "shown by the panel rows: {a1}.",
    "везде": "everywhere",
    "во всех подключённых индексах — здесь вопросов нет":
        "in every index you connected — nothing to ask here",
    "глубже допустимого клика": "deeper than the click budget",
    "две выгрузки помечены как «{a0}» — они объединены; если это разные источники, задай метки явно":
        "two exports are labelled “{a0}” — they were merged; if these are different "
        "sources, label them explicitly",
    "добавить содержимое или убрать из индекса":
        "add content, or take them out of the index",
    "добавить ссылки на них с хабовых страниц раздела":
        "link to them from the section's hub pages",
    "другие поисковики страницу приняли, значит она доступна и валидна. Причина на стороне {a0}: оценка качества или более медленная индексация — техническими правками это обычно не лечится":
        "the other engines accepted the page, so it is reachable and valid. The "
        "reason sits with {a0}: a quality judgement or slower indexing — technical "
        "fixes rarely help with that",
    "есть в других источниках, но не в {a0}":
        "present in other sources, absent from {a0}",
    "заполнить title — без него страница почти не имеет шансов":
        "fill in the title — without one the page has almost no chance",
    "источник знает про URL, но страницы в нём нет":
        "the source knows the URL, but the page is not in it",
    "нет только в {a0}": "missing only from {a0}",
    "ни один из {a0} адресов выгрузки не совпал с адресами сайта. Скорее всего, это экспорт другого проекта или другой домен (проверь --site). Раздел индексации ниже смысла не имеет.":
        "not one of the {a0} addresses in the export matched the site's addresses. "
        "Most likely this is an export from another project or another domain "
        "(check --site). The indexation section below is meaningless.",
    "ни один поисковик не добавил в индекс — это техническая проблема, ищите причину в разделе ниже":
        "no engine added them to its index — that is a technical problem, look for "
        "the cause in the section below",
    "нигде": "nowhere",
    "панели вебмастера среди выгрузок нет, поэтому строгого ответа «в индексе или нет» здесь не будет: ":
        "there is no webmaster panel among the exports, so there will be no strict "
        "“indexed or not” answer here: ",
    "панели вебмастера среди выгрузок нет. Воронка построена на том, что есть, но подпись шага это учитывает: ":
        "there is no webmaster panel among the exports. The funnel is built on what "
        "there is, and the step label says so: ",
    "переписать под разные интенты или оставить одну, а с остальных поставить canonical на неё — связывать их ссылками между собой нельзя":
        "rewrite them for different intents, or keep one and point the others' "
        "canonical at it — linking them to each other is not the fix",
    "поднять выше в структуре": "move them up in the structure",
    "почти-дубли других страниц": "near-duplicates of other pages",
    "причина не установлена локально": "no cause could be established locally",
    "проверить в Search Console статус конкретных URL и время с публикации":
        "check the status of specific URLs in Search Console, and how long ago they "
        "were published",
    "сироты и недостижимые от главной":
        "orphaned, or unreachable from the home page",
    "слишком глубокая вложенность sitemap-индексов":
        "sitemap indexes nested too deeply",
    "страница есть на диске, но в sitemap не попала":
        "the page is on disk but never made it into the sitemap",
    "тонкие страницы": "thin pages",
    "файл {a0} не найден": "file {a0} not found",

    # ── aeo ───────────────────────────────────────────────────────────────────
    "Anthropic не будет использовать страницу":
        "Anthropic will not use the page",
    "Apple Intelligence не будет использовать страницу":
        "Apple Intelligence will not use the page",
    "Bing не проиндексирует страницу — а вместе с ним Copilot":
        "Bing will not index the page — and Copilot goes with it",
    "ChatGPT не покажет страницу в ответах своего поиска":
        "ChatGPT will not show the page in its search answers",
    "ChatGPT не сможет открыть страницу по прямой просьбе пользователя":
        "ChatGPT will not be able to open the page when a user asks it to",
    "Claude не покажет страницу в ответах с поиском":
        "Claude will not show the page in answers that use search",
    "Disallow: / для всех агентов — сайт закрыт от всех поисковиков целиком":
        "Disallow: / for every agent — the whole site is closed to every search engine",
    "Gemini не будет использовать страницу для обучения (на AI Overviews не влияет)":
        "Gemini will not use the page for training (this does not affect AI Overviews)",
    "OpenAI не будет использовать страницу для обучения (на показ в поиске это не влияет)":
        "OpenAI will not use the page for training (this does not affect appearing "
        "in search)",
    "Perplexity не проиндексирует страницу": "Perplexity will not index the page",
    "robots.txt не найден — это не ошибка, но и не контроль: передай путь через --robots, чтобы проверить":
        "robots.txt was not found — not an error, but not a check either: pass its "
        "path with --robots to have it checked",
    "robots.txt не прочитан: {a0}": "robots.txt was not read: {a0}",
    "{a0} абзац(ев) длиннее {a1} символов — такой блок трудно процитировать целиком":
        "{a0} paragraph(s) longer than {a1} characters — a block like that is hard "
        "to quote whole",
    "{a0} вопрос(ов) из FAQPage нет в видимом тексте — разметка, не совпадающая со страницей, это риск ручных санкций":
        "{a0} question(s) from FAQPage are missing from the visible text — markup "
        "that does not match the page risks a manual action",
    "{a0} закрыт: {a1}": "{a0} is blocked: {a1}",
    "{a0} изображени(й) без alt": "{a0} image(s) without alt text",
    "{a0} — это каталог, а нужен файл": "{a0} is a directory — a file is needed",
    "Проверено то, что не мешает машине взять ответ со страницы. Попадание в ответы ИИ-поиска определяется в основном вне сайта: упоминания и позиция в обычной выдаче. Пакет на это не влияет.":
        "What was checked is whether anything stops a machine from taking an answer "
        "off the page. Getting cited in AI search is decided mostly off-site: "
        "mentions elsewhere and your position in the classic results. This package "
        "does not affect that.",
    "блок JSON-LD не парсится ({a0}) — для поисковика его просто нет":
        "the JSON-LD block does not parse ({a0}) — for a search engine it simply "
        "is not there",
    "в robots.txt не указан Sitemap — строка `Sitemap: https://…/sitemap.xml` стоит копейки":
        "robots.txt names no Sitemap — the line `Sitemap: https://…/sitemap.xml` "
        "costs nothing",
    "в блоке JSON-LD нет @type": "the JSON-LD block has no @type",
    "в исходном HTML {a0} слов при {a1} скриптах — краулеры ИИ-поиска не исполняют JavaScript и увидят пустую страницу":
        "{a0} words in the source HTML against {a1} scripts — AI-search crawlers do "
        "not execute JavaScript and will see an empty page",
    "в тексте нет ни списков, ни таблиц — структурные элементы повышают шанс попасть в ответ":
        "the text has neither lists nor tables — structural elements raise the "
        "chance of being used in an answer",
    "вопросов среди подзаголовков {a0} из {a1} — формат «вопрос → ответ» цитируется заметно чаще":
        "{a0} of {a1} subheadings are questions — the “question → answer” shape is "
        "quoted noticeably more often",
    "не нашёл ни одного абзаца — цитировать нечего":
        "no paragraph found — there is nothing to quote",
    "не покажет": "will not show",
    "не проиндексирует": "will not index",
    "не указан автор или организация — сигнал E-E-A-T":
        "no author or organisation is given — an E-E-A-T signal",
    "нет машиночитаемой даты публикации или обновления":
        "no machine-readable published or updated date",
    "первый абзац {a0} символов — для цитирования лучше уложить ответ в {a1}":
        "the first paragraph is {a0} characters — to be quoted, an answer is better "
        "kept within {a1}",
    "первый абзац короче {a0} символов — на самостоятельный ответ не тянет":
        "the first paragraph is shorter than {a0} characters — not enough to stand "
        "as an answer",
    "первый абзац начинается с разгона «{a0}…» — ИИ-поиск цитирует ответ, а не вступление":
        "the first paragraph opens with a run-up, “{a0}…” — AI search quotes the "
        "answer, not the introduction",
    "файла {a0} нет": "there is no file {a0}",
}
