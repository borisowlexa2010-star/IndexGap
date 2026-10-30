# -*- coding: utf-8 -*-
"""fetch — English."""

MESSAGES = {
    "  без ответа (таймаут, обрыв): {a0}": "  no response (timeout, dropped connection): {a0}",
    "  больше 2 МБ: {a0} — Googlebot читает только первые 2 МБ HTML":
        "  over 2 MB: {a0} — Googlebot reads only the first 2 MB of HTML",
    "  другой хост: {a0} — не скачивались": "  another host: {a0} — not fetched",
    "  закрыто robots.txt: {a0} — не скачивались": "  disallowed by robots.txt: {a0} — not fetched",
    "  не HTML — записаны в fetch.json, страницами не сохранены: {a0}":
        "  not HTML — recorded in fetch.json, not saved as pages: {a0}",
    "  ответ 200, но не сохранены: {a0}": "  answered 200 but not saved: {a0}",
    "  ответы с ошибкой: {a0}": "  error responses: {a0}",
    "  сверх --limit {a0}: {a1} — не скачивались (поднять: --limit N или --limit 0 --all)":
        "  over --limit {a0}: {a1} — not fetched (raise it: --limit N or --limit 0 --all)",
    "--all и --limit {a0} противоречат друг другу: либо потолок, либо все страницы":
        "--all and --limit {a0} contradict each other: either a cap or every page",
    "--delay не может быть отрицательным": "--delay cannot be negative",
    "--jobs от 1 до {a0}": "--jobs must be 1 to {a0}",
    "--limit 0 значит «без потолка» — это только вместе с --all":
        "--limit 0 means “no cap” — only together with --all",
    "--limit не может быть отрицательным": "--limit cannot be negative",
    "--out-dir {a0} не пуст. Скачанное смешалось бы с тем, что там лежит, — укажи новый каталог или очисти этот":
        "--out-dir {a0} is not empty. The download would mix with what is already "
        "there — give a new directory or empty this one",
    "--out-dir {a0} — это файл, а нужен каталог": "--out-dir {a0} is a file; a directory is needed",
    "--sitemap {a0}: другой хост, чем {a1} — туда fetch не ходит":
        "--sitemap {a0}: a different host from {a1} — fetch does not go there",
    "--sitemap {a0}: нужен адрес на сайте; файл с диска передай сразу в check":
        "--sitemap {a0}: an address on the site is needed; pass a file on disk "
        "straight to check",
    "robots.txt объявляет sitemap на другом хосте — не скачивался: {a0}":
        "robots.txt declares a sitemap on another host — not fetched: {a0}",
    "sitemap прочитан не целиком: {a0}": "the sitemap was not read in full: {a0}",
    "{a0} ведёт редиректом на другой хост: {a1}": "{a0} redirects to another host: {a1}",
    "{a0} не читается: {a1} — обход не начат":
        "{a0} cannot be read: {a1} — the crawl did not start",
    "{a0} отдал {a1}: по правилам robots.txt это «не обходить» — обход не начат. Повтори позже":
        "{a0} returned {a1}: under the robots.txt rules that means “do not crawl” — "
        "the crawl did not start. Try again later",
    "{a0} — так не годится: нужен полный адрес со схемой. Попробуй: indexgap fetch https://{a1}":
        "{a0} will not do: the full address with the scheme is needed. Try: "
        "indexgap fetch https://{a1}",
    "{a0}: check считает такой файл страницей ошибки":
        "{a0}: check treats such a file as an error page",
    "{a0}: sitemap на другом хосте — не скачивается":
        "{a0}: a sitemap on another host — not fetched",
    "Адресов в sitemap: {a0} (sitemap-файлов: {a1})":
        "Addresses in the sitemap: {a0} (sitemap files: {a1})",
    "Дальше:": "Next:",
    "Записано: {a0}": "Written: {a0}",
    "Запрошено: {a0}   Сохранено страниц: {a1}   С редиректом: {a2}":
        "Requested: {a0}   Pages saved: {a1}   Redirected: {a2}",
    "Ни одной страницы не сохранено — проверять нечего.":
        "Not a single page was saved — nothing to check.",
    "адрес с параметрами (?…) файлом не записать": "an address with parameters (?…) cannot be a file",
    "больше {a0} МБ — не сохранялась": "over {a0} MB — not saved",
    "больше {a0} редиректов подряд": "more than {a0} redirects in a row",
    "в сегменте пути закодирован / , \\ или NUL": "a path segment encodes /, \\ or NUL",
    "каталог {a0} check не читает": "check does not read the directory {a0}",
    "пустой сегмент пути (//)": "an empty path segment (//)",
    "путь {a0} выходит за каталог": "the path {a0} leaves the directory",
    "редирект на адрес, закрытый robots.txt, — не скачивался":
        "redirects to an address disallowed by robots.txt — not fetched",
    "редирект на другой хост — не скачивался": "redirects to another host — not fetched",
    "сегмент пути . или .. — файлом не записать": "a path segment . or .. cannot be a file",
    "сегмент пути длиннее 200 байт": "a path segment longer than 200 bytes",
    "файл {a0} check не читает": "check does not read the file {a0}",
    "файл {a0} уже занят адресом {a1}": "the file {a0} is already taken by {a1}",
    "<каталог>": "<directory>",
    "--browser {a0}: такого исполняемого файла нет": "--browser {a0}: no such executable",
    "--render нужен браузер семейства Chromium, а его нет: ни {a0} в PATH, ни Google Chrome "
    "или Chromium на обычном месте. Поставь Google Chrome или Chromium либо укажи путь: "
    "--browser /путь/к/chrome":
        "--render needs a Chromium-family browser and there is none: no {a0} on PATH, "
        "no Google Chrome or Chromium in the usual place. Install Google Chrome or "
        "Chromium, or give the path: --browser /path/to/chrome",
    "--browser задаёт браузер для --render — без --render он не нужен":
        "--browser sets the browser for --render — without --render it is not needed",
    "адрес не http(s) на сайте {a0} или с пробелом — браузеру не передаётся":
        "the address is not http(s) on the site {a0} or has a space — not passed to the browser",
    "браузер не запустился: {a0}": "the browser did not start: {a0}",
    "браузер не уложился в {a0} с — остановлен": "the browser took over {a0} s — stopped",
    "браузер завершился с кодом {a0}": "the browser exited with code {a0}",
    "отрисованный DOM больше {a0} МБ": "the rendered DOM is over {a0} MB",
    "браузер вернул не HTML": "the browser returned something that is not HTML",
    "sitemap не прочитан: {a0} — обход только по ссылкам от главной":
        "the sitemap was not read: {a0} — crawling only by links from the home page",
    "  найдены только по ссылкам: {a0} — их нет в sitemap":
        "  found only by links: {a0} — they are missing from the sitemap",
    "  в sitemap, но на них не ведёт ни одной ссылки: {a0} — кандидаты в сироты":
        "  in the sitemap, but not a single link leads to them: {a0} — orphan candidates",
    " (обход неполный — часть ссылок не прочитана)":
        " (the crawl is incomplete — some links were not read)",
    "  битые ссылки: {a0} — адрес по ссылке отвечает ошибкой":
        "  broken links: {a0} — the linked address answers with an error",
    "  ссылки с параметрами (?…) не обходились: {a0}":
        "  links with parameters (?…) were not followed: {a0}",
    "Отрисовано браузером: {a0} из {a1}": "Rendered by the browser: {a0} of {a1}",
    "  не отрисованы — сохранён исходный HTML: {a0}":
        "  not rendered — the raw HTML was saved: {a0}",
    "{a0} страниц(ы) похожи на пустой JS-каркас: текст рисует JavaScript, и check его не "
    "увидит. Повтори с --render":
        "{a0} page(s) look like empty JS shells: JavaScript draws the text, and check will "
        "not see it. Rerun with --render",
    "--browser-no-sandbox относится к --render — без него не нужен":
        "--browser-no-sandbox belongs to --render — it is not needed without it",
    "под root на Linux Chromium без песочницы не запускается, а песочница — главная защита от чужого JavaScript. Запусти fetch не под root или, если понимаешь риск (контейнер, который выбрасывается после прогона), добавь --browser-no-sandbox":
        "as root on Linux Chromium does not start with its sandbox, and the sandbox is "
        "the main protection against someone else's JavaScript. Run fetch as another "
        "user or, if you accept the risk (a container thrown away after the run), add "
        "--browser-no-sandbox",
    "--browser {a0}: пакетный файл .bat/.cmd браузером быть не может — cmd заново разбирает его аргументы. Укажи .exe браузера":
        "--browser {a0}: a .bat/.cmd batch file cannot be the browser — cmd re-parses "
        "its arguments. Give the browser's .exe",
    "пакетный файл .bat/.cmd браузером быть не может":
        "a .bat/.cmd batch file cannot be the browser",
}
