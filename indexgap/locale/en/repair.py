# -*- coding: utf-8 -*-
"""repair — наряды на починку, English.

Императив здесь важнее гладкости: это задание, которое человек или агент
берёт в работу. «Consider revising» — не задание.
"""

MESSAGES = {
    # ── что делать: сверка с датасетом ────────────────────────────────────────
    "Найди это число в строке датасета. Если его там нет — убери утверждение целиком или замени на то, что есть в данных. Не подбирай похожее число: страница про визы с выдуманным сроком — это вред человеку, а не недобор трафика.":
        "Find this number in the dataset row. If it is not there, drop the claim "
        "entirely or replace it with something the data does contain. Do not pick "
        "a similar-looking number: a visa page with an invented processing time "
        "harms the reader, it is not merely lost traffic.",
    "Просмотри эти числа глазами. Часть — обычная речь, часть — выдумка. Оставь только то, что можешь подтвердить.":
        "Read these numbers with your own eyes. Some are ordinary turns of "
        "phrase, some are invented. Keep only what you can confirm.",
    "Удали блок брифа или TODO из файла.":
        "Delete the brief block or the TODO from the file.",
    "Допиши страницу и убери `status: draft` из фронтматтера. Пока метка стоит, страница не попадёт ни в sitemap, ни в IndexNow.":
        "Finish the page and remove `status: draft` from the front matter. While "
        "the mark is there, the page goes into neither the sitemap nor IndexNow.",

    # ── что делать: индексация ────────────────────────────────────────────────
    "Убери мета-тег robots, если закрытие от индексации не было задумано. Если было — оставь и не трогай эту находку.":
        "Remove the robots meta tag if closing this page off was not intended. If "
        "it was, leave it and ignore this finding.",
    "Убери `nosnippet` или `max-snippet:0`: без права на сниппет страница не попадёт ни в расширенную выдачу, ни в ответы ИИ-поиска.":
        "Remove `nosnippet` or `max-snippet:0`: without the right to a snippet the "
        "page reaches neither rich results nor AI answers.",
    "Проверь шаблон: canonical должен указывать на саму страницу. Сейчас она отдаёт вес другой и выпадает из индекса.":
        "Check the template: the canonical must point at the page itself. Right "
        "now it hands its weight to another page and drops out of the index.",
    "Поставь ссылки на эту страницу с хабовых страниц раздела. Анкор — описательный, не «подробнее».":
        "Link to this page from the section's hub pages. Make the anchor "
        "descriptive, not “read more”.",
    "Добавь путь от главной: страница есть в sitemap, но краулер до неё не доходит.":
        "Add a path from the home page: the page is in the sitemap, but a crawler "
        "never reaches it.",
    "Подними страницу выше в структуре или дай на неё ссылку с более близкой к главной.":
        "Move the page higher in the structure, or link to it from a page closer "
        "to the home page.",

    # ── что делать: текст ─────────────────────────────────────────────────────
    "Добавь то, что отличает эту страницу от соседних: конкретику из её строки данных. Шаблонного текста должно стать меньше, чем своего.":
        "Add what makes this page different from its neighbours: the specifics "
        "from its own data row. There should end up being less boilerplate than "
        "text of its own.",
    "Наполни страницу или убери из индекса. Если порог не подходит этому типу контента — поправь его в indexgap.json, а не дописывай воду.":
        "Fill the page out or take it out of the index. If the threshold does not "
        "suit this kind of content, change it in indexgap.json rather than padding "
        "the text.",
    "Поменяй структуру заголовков под данные этой строки. Одинаковый скелет на всех страницах читается как штамповка.":
        "Change the heading structure to follow this row's data. The same skeleton "
        "on every page reads as stamped out.",
    "Перепиши первый абзац так, чтобы он отвечал на запрос именно этой страницы.":
        "Rewrite the opening paragraph so that it answers this page's query in "
        "particular.",
    "Добавь title.": "Add a title.",
    "Удлини title до рекомендованного диапазона.":
        "Lengthen the title into the recommended range.",
    "Сократи title: в выдаче он обрежется.":
        "Shorten the title: it will be truncated in the results.",
    "Добавь meta description.": "Add a meta description.",
    "Приведи description к рекомендованной длине.":
        "Bring the description to the recommended length.",
    "Добавь H1 — по нему поисковик определяет тему страницы.":
        "Add an H1 — it is what tells a search engine the page's topic.",
    "Оставь один H1, остальные понизь до H2.":
        "Keep one H1 and demote the rest to H2.",
    "Добавь структуру заголовков.": "Add a heading structure.",
    "Сделай title уникальным: сейчас он совпадает с другими страницами, и в выдаче они склеятся.":
        "Make the title unique: right now it matches other pages, and the results "
        "will collapse them together.",
    "Сделай description уникальным.": "Make the description unique.",
    "Замени анкоры на описательные: из ссылки должно быть понятно, куда она ведёт.":
        "Replace the anchors with descriptive ones: the link should say where it "
        "leads.",
    "Почини сам файл — кодировку или фронтматтер. Пока он читается неверно, остальные находки на нём недостоверны.":
        "Fix the file itself — its encoding or its front matter. While it is read "
        "wrongly, every other finding on it is unreliable.",
    "Событие прошло, а страница открыта для индексации. Закрой noindex, поставь редирект на актуальное или перепиши в отчёт о прошедшем.":
        "The event is over and the page is still open to indexing. Close it with "
        "noindex, redirect to the current one, or rewrite it as a report on what "
        "happened.",
    "Нужен серверный рендеринг или пререндер: краулеры ИИ-поиска не исполняют JavaScript. Это правится в сборке сайта, а не в тексте страницы.":
        "This needs server-side rendering or prerendering: AI-search crawlers do "
        "not execute JavaScript. It is fixed in the site's build, not in the "
        "page's text.",

    # ── что делать: попасть в ответ ───────────────────────────────────────────
    "Убери разгон из первого абзаца: он должен быть прямым ответом на запрос. Именно его цитируют.":
        "Cut the run-up from the opening paragraph: it should be a direct answer "
        "to the query. That paragraph is the one that gets quoted.",
    "Расширь первый абзац до самостоятельного ответа.":
        "Expand the opening paragraph into an answer that stands on its own.",
    "Сократи первый абзац: длинный блок не цитируют целиком.":
        "Shorten the opening paragraph: a long block does not get quoted whole.",
    "Переформулируй часть подзаголовков как вопросы: формат «вопрос → ответ» цитируется заметно чаще.":
        "Reword some of the subheadings as questions: the question → answer shape "
        "is quoted noticeably more often.",
    "Разбей длинные абзацы подзаголовками.":
        "Break the long paragraphs up with subheadings.",
    "Добавь списки или таблицы: структурные элементы повышают шанс попасть в ответ.":
        "Add lists or tables: structural elements raise the chance of making it "
        "into an answer.",
    "Добавь машиночитаемую дату — в JSON-LD или фронтматтер.":
        "Add a machine-readable date — in JSON-LD or in the front matter.",
    "Укажи автора или организацию.": "Name an author or an organisation.",
    "Почини JSON-LD: сейчас он не парсится, и для поисковика его нет.":
        "Fix the JSON-LD: it does not parse, so as far as a search engine is "
        "concerned it is not there.",
    "Убери из разметки FAQ вопросы, которых нет на странице, или добавь их в текст. Разметка, не совпадающая со страницей, — риск санкций.":
        "Remove from the FAQ markup any question that is not on the page, or add "
        "it to the text. Markup that does not match the page risks a penalty.",
    "Добавь alt изображениям.": "Add alt text to the images.",

    # ── что делать: языковые версии ───────────────────────────────────────────
    "Добавь в кластер ссылку на саму страницу: без self-ссылки кластер невалиден целиком.":
        "Add a link to the page itself into the cluster: without a self-reference "
        "the whole cluster is invalid.",
    "Сделай связь взаимной: односторонняя отбрасывается целиком, а не учитывается частично.":
        "Make the link reciprocal: a one-way link is discarded entirely, not "
        "counted in part.",
    "Шаблон печатает кластер главной на каждой странице. Кластер должен собираться из переводов ЭТОЙ страницы.":
        "The template prints the home page's cluster on every page. The cluster "
        "has to be built from the translations of THIS page.",
    "Верни canonical на саму страницу: сейчас он уводит на другой язык и отменяет hreflang.":
        "Point the canonical back at the page itself: right now it leads to "
        "another language and cancels hreflang.",
    "Добавь альтернативы для языковых версий этой страницы.":
        "Declare alternates for this page's language versions.",
    "Поправь код языка: чаще всего вместо языка написана страна.":
        "Fix the language code: usually a country has been written where a "
        "language belongs.",

    # ── что делать: сайт целиком ──────────────────────────────────────────────
    "Убери `Disallow: /` — сейчас сайт закрыт от всех поисковиков.":
        "Remove `Disallow: /` — right now the site is closed to every search "
        "engine.",
    "Реши сознательно, нужен ли этот краулер, и открой его в robots.txt, если нужен.":
        "Decide deliberately whether you want this crawler, and open it up in "
        "robots.txt if you do.",
    "Добавь строку `Sitemap:` в robots.txt.":
        "Add a `Sitemap:` line to robots.txt.",
    "Положи robots.txt в корень сайта или укажи путь к нему через --robots. Пока файла нет, проверки доступа краулеров не сделаны — это не значит, что доступ открыт.":
        "Put robots.txt in the site root, or pass its path with --robots. While "
        "the file is missing, the crawler-access checks have not run — which does "
        "not mean access is open.",
    "Создай robots.txt: без него нельзя ни закрыть лишнее, ни указать sitemap.":
        "Create a robots.txt: without one you can neither close anything off nor "
        "point at a sitemap.",

    # ── тело наряда ───────────────────────────────────────────────────────────
    "Починка шаблона": "Fixing the template",
    "Починка на уровне сайта": "Fixing the site as a whole",
    "Группа почти-дублей №{a0}": "Near-duplicate group no. {a0}",
    "Починка страницы": "Fixing one page",
    "Что делать:": "What to do:",
    "Эти находки срабатывают почти на всех страницах. Это свойство шаблона, а не список страниц: правится один раз в шаблоне и исчезает везде.":
        "These findings fire on nearly every page. That is a property of the "
        "template, not a list of pages: fix it once in the template and it "
        "disappears everywhere.",
    "Свойства сайта, а не отдельных страниц: robots.txt, разметка, связи языковых версий.":
        "Properties of the site rather than of any one page: robots.txt, markup, "
        "the links between language versions.",
    "{a0} страниц почти совпадают друг с другом. Поисковик оставит в индексе одну.":
        "{a0} pages nearly coincide with one another. A search engine will keep "
        "one of them in the index.",
    "Что делать: выбери одну страницу как основную и разведи остальные по разным интентам — у каждой должен быть свой вопрос, на который она отвечает. Если развести нечем, оставь одну, а с остальных поставь canonical на неё. Связывать их ссылками между собой нельзя.":
        "What to do: pick one page as the main one and pull the rest apart by "
        "intent — each should have its own question that it answers. If there is "
        "nothing to pull them apart with, keep one and point the others' canonical "
        "at it. Do not link them to one another.",
    "Страницы группы:": "Pages in the group:",
    "Файл: `{a0}`": "File: `{a0}`",
    "Адрес: {a0}": "Address: {a0}",
    "Что не так:": "What is wrong:",
    "Данные строки датасета — единственный источник чисел для этой страницы:":
        "The dataset row — the only source of numbers for this page:",
    "Чему страница должна удовлетворять после починки:":
        "What the page has to satisfy once fixed:",
    "профиль: {a0}": "profile: {a0}",
    "объём основного текста: не меньше {a0} слов":
        "body text: at least {a0} words",
    "title {a0}–{a1} знаков ширины, description {a2}–{a3}":
        "title {a0}–{a1} display columns, description {a2}–{a3}",
    "похожесть с соседними страницами ниже {a0:.2f}":
        "similarity to neighbouring pages below {a0:.2f}",
    "ни одного числа, которого нет в строке датасета":
        "not a single number that is absent from the dataset row",
    "Ничего не выдумывать. Если данных нет, раздел не пишем.":
        "Invent nothing. If the data is not there, the section is not written.",
    "Проверить результат:": "Check the result:",
    "не указан каталог для нарядов": "no directory given for the briefs",

    # ── вывод команды ─────────────────────────────────────────────────────────
    "наряды на починку: находки проверки — заданиями рядом со страницами":
        "repair briefs: the check's findings as work orders beside the pages",
    "куда класть наряды": "where to put the briefs",
    "сколько нарядов на страницы выписать: сначала самые тяжёлые. 0 — все":
        "how many page briefs to write: the heaviest first. 0 means all of them",
    "семантика (CSV или XLSX): её строки попадают в наряд как единственный источник чисел":
        "the keyword set (CSV or XLSX): its rows go into the brief as the only "
        "source of numbers",
    "действительно создать файлы; без него — пробный прогон":
        "actually create the files; without it this is a dry run",
    "\nНарядов: {a0}": "\nBriefs: {a0}",
    "  шаблон — 1 наряд вместо находок почти на всех страницах":
        "  the template — 1 brief instead of findings on nearly every page",
    "  сайт целиком — 1 наряд: robots.txt, разметка, языковые версии":
        "  the site as a whole — 1 brief: robots.txt, markup, language versions",
    "  групп почти-дублей — {a0}: чинятся группой, поштучно нельзя":
        "  near-duplicate groups — {a0}: fixed as a group, never one at a time",
    "  страниц — {a0}": "  pages — {a0}",
    " (запишем {a0} самых тяжёлых)": " (writing the {a0} heaviest)",
    "\nЧинить нечего: ни одной находки, на которую выписывается наряд.":
        "\nNothing to fix: not one finding that a brief is written for.",
    "\nЭто пробный прогон: ни одного файла не создано. Чтобы разложить наряды — добавь --write.":
        "\nThis was a dry run: not one file was created. To lay the briefs out, "
        "add --write.",
    "\nЗаписано в {a0}: {a1} файл(ов)": "\nWritten to {a0}: {a1} file(s)",
    "  не выписано на {a0} страниц(ы): предел --limit. Почини эти и прогони ещё раз — часть остальных уйдёт вместе с шаблоном.":
        "  {a0} page(s) got no brief: the --limit cap. Fix these, run again, and "
        "some of the rest will go away with the template.",
    "Наряды перезаписываются при каждом прогоне: это отчёт, а не исходник. Свои правки держи в страницах, а не в них.":
        "The briefs are overwritten on every run: they are a report, not a source "
        "file. Keep your own edits in the pages, not in them.",
}
