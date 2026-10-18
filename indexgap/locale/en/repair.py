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
    "Ссылки ведут на страницы, которых нет в сборке. Найди, откуда шаблон берёт эти адреса, и либо убери ссылку, либо сгенерируй страницу. Если сервер перенаправляет эти адреса — проверь, что перенаправление действительно есть.":
        "The links point at pages the build does not have. Find where the "
        "template takes these addresses from, and either remove the link or "
        "generate the page. If the server redirects these addresses, check that "
        "the redirect really exists.",
    "Найди, откуда приходит пустое значение: строка датасета без поля, опечатка в имени переменной шаблона или поле, которое генератор не подставляет. Почини данные или шаблон и пересобери — править готовую страницу бесполезно, следующая сборка вернёт шов.":
        "Find where the empty value comes from: a dataset row missing the field, a typo in a template variable, or a field the generator does not fill. Fix the data or the template and rebuild — editing the built page is useless, the next build brings the seam back.",
    "Перегенерируй или перепиши этот текст. В конвейере отбрасывай ответы модели с отказом или вступлением до того, как они попадут в шаблон.":
        "Regenerate or rewrite this text. In the pipeline, drop model replies that refuse or open with a preamble before they reach the template.",
    "Найди шаг конвейера, где UTF-8 читается как Latin-1 или cp1252 (обычно импорт CSV или ответ API), и укажи кодировку явно. Пересобери страницы.":
        "Find the pipeline step where UTF-8 is read as Latin-1 or cp1252 (usually a CSV import or an API response) and set the encoding explicitly. Rebuild the pages.",
    "Найди правило Disallow, которое закрывает этот раздел, и реши: если раздел должен быть в поиске — убери правило; если нет — убери страницы из sitemap и поставь на них noindex (его поисковик увидит, только если обход разрешён).":
        "Find the Disallow rule that closes this section and decide: if the section belongs in search, remove the rule; if not, take the pages out of the sitemap and put noindex on them (the engine sees it only if crawling is allowed).",
    "Хаб, листинг и главная ценны ссылками, а не словами: закрывать их нельзя. Страницу строки наполни фактами из её строки данных; если фактов нет — спроси, нужна ли эта страница. Порог — `checks.thin_words` в indexgap.json: понижай его, только если этот тип контента законно короткий, а не дописывай воду.":
        "A hub, a listing or the home page is valuable for its links, not its words: never close them. Fill a row's page with facts from its data row; if there are none, ask whether the page should exist. The threshold is `checks.thin_words` in indexgap.json: lower it only if this content type is legitimately short, and do not pad the text.",
    "Это собранный файл: правка в нём пропадёт при следующей сборке. Чини источник — шаблон, строку данных или генератор — и пересобери. Путь показывает, какой шаблон и какая строка дали эту страницу.":
        "This is a built file: an edit in it is lost on the next build. Fix the source — the template, the data row or the generator — and rebuild. The path shows which template and which row produced this page.",
    "Проверить результат (после пересборки, если страницы собираются):":
        "Check the result (after rebuilding, if the pages are built):",
    "страница не сопоставлена со строкой датасета — её числа НЕ проверялись. Если это страница строки, назови строку: `keyword:` во фронтматтере или <meta name=\"keyword\"> в шаблоне":
        "the page is not matched to a dataset row — its numbers were NOT checked. If it is a row's page, name the row: `keyword:` in the front matter or <meta name=\"keyword\"> in the template",
    "Что делать: страницы на разных языках совпадают текстом — перевод не сделан. Переведи каждую версию. Canonical на одну из них выбросит языковую версию из поиска.":
        "What to do: pages in different languages share their text — the translation was not done. Translate each version. A canonical to one of them would drop a language version from search.",
    "Что делать: страницы собраны из разных строк датасета — дублирует их шаблон, а не интент. Чини шаблон: больше данных своей строки, разделы, которые зависят от данных. Склеивать их canonical'ом нельзя — пропадут настоящие страницы.":
        "What to do: the pages are built from different dataset rows — the template duplicates them, not the intent. Fix the template: more of each row's own data, sections that depend on the data. Never merge them with a canonical — real pages would disappear.",
    "Что делать: выбери одну страницу как основную и разведи остальные по разным интентам — у каждой должен быть свой вопрос, на который она отвечает. Если развести нечем — это один интент: убери лишнюю строку из датасета (её покажет `indexgap plan`) или поставь с остальных страниц canonical на основную.":
        "What to do: choose one page as the main one and move the rest to different intents — each needs its own question to answer. If there is nothing to separate them with, it is one intent: remove the extra row from the dataset (`indexgap plan` shows it) or point the others' canonical at the main page.",
    "Обычные ссылки на соседние страницы и хабы оставь: ссылка не делает страницы разными, но и не вредит им.":
        "Keep the ordinary links to neighbouring pages and hubs: a link does not make pages different, but it does not hurt them either.",
    "Страницы группы (наибольшее совпадение с другой страницей группы):":
        "Pages of the group (the highest similarity to another page of the group):",
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

    # ── находки, у которых наряд раньше выходил пустым ────────────────────────
    "Реши, что делать с группой целиком: оставить одну страницу и увести остальные canonical'ом на неё — или развести их по разным интентам. Одну страницу из группы починить нельзя.":
        "Decide what to do with the whole group: keep one page and "
        "canonical the rest to it, or pull them apart by intent. A single "
        "page out of the group cannot be fixed alone.",
    "Проверь, не выросли ли эти страницы из двух ключей с одним интентом. Если да — объединяй; если нет, добавь каждой то, чего нет у соседней.":
        "Check whether these pages grew out of two keywords with one "
        "intent. If they did, merge them; if not, give each of them what "
        "the other one has not got.",
    "Реши, чем стала страница: архивом или невыполнимым обещанием. Архив пометь датой окончания прямо в тексте, обещание убери из индекса.":
        "Decide what the page has become: an archive or a promise it can no "
        "longer keep. Mark an archive with its end date in the text itself, "
        "and take the promise out of the index.",
    "Убери из кластера адреса, которых нет среди страниц сайта, или исправь их. Сейчас кластер ссылается в пустоту, и поисковик вправе не считать его вовсе.":
        "Remove the addresses that are not among the site's pages from the "
        "cluster, or correct them. Right now the cluster points at nothing, "
        "and a search engine is entitled to disregard it entirely.",
    "Приведи объявленный язык в соответствие с языком текста. Пока они расходятся, поисковик показывает страницу не тем читателям — и считает это правильным результатом.":
        "Bring the declared language in line with the language the text is "
        "written in. While they disagree, the engine shows the page to the "
        "wrong readers — and counts that as a correct result.",
    "Открой страницу-альтернативу для индексации или убери её из кластера: закрытая цель ослабляет весь кластер.":
        "Open the alternate page for indexing or drop it from the cluster: "
        "a blocked target weakens the whole cluster.",
    "Добавь `@type` в блок JSON-LD. Без него разметка разбирается, но не значит ничего.":
        "Add `@type` to the JSON-LD block. Without it the markup parses and "
        "means nothing.",
    "Начни страницу абзацем, который отвечает на её запрос. Сейчас на ней нет ничего, что можно процитировать как ответ.":
        "Open the page with a paragraph that answers its own query. As it "
        "stands there is nothing on it that can be quoted as an answer.",

    # ── главная-заглушка и запаркованные переводы ─────────────────────
    "Реши по каждому языку. Перевод готов — открой его: свой canonical и index. Не готов — держи закрытым, но убери hreflang и с него, и со ссылающихся на него страниц: сейчас сигналы спорят, и поисковик выбирает сам.":
        "Decide per language. If a translation is ready, open it: its own "
        "canonical and index. If it is not, keep it closed, but remove hreflang "
        "from it and from the pages that point at it: right now the signals "
        "contradict each other and the search engine picks for itself.",
}
