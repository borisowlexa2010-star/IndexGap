# -*- coding: utf-8 -*-
"""report — English. В основном это словарь кодов находок: он и есть язык,
на котором человек читает отчёт."""

MESSAGES = {
    # ── шаблоны страницы отчёта ───────────────────────────────────────────────
    '<!doctype html><!-- indexgap-report --><html lang="ru"><head><meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>{a0}{a1}</title>\n<style>{a2}</style></head><body><div class="wrap">\n<h1>{a3}</h1>\n<p class="sub">{a4} · {a5} страниц · {a6}</p>\n\n{a7}\n\n<div class="cards">\n  <div class="card"><div class="n">{a8}</div><div class="l">страниц разобрано</div></div>\n  <div class="card"><div class="n bad">{a9}</div><div class="l">критично</div></div>\n  <div class="card"><div class="n warn">{a10}</div><div class="l">внимание</div></div>\n  <div class="card"><div class="n bad">{a11}</div><div class="l">сирот без входящих ссылок</div></div>\n  <div class="card"><div class="n bad">{a12}</div><div class="l">пар похожих страниц</div></div>\n</div>\n\n{a13}\n\n{a14}\n{a15}\n{a16}\n\n<h2>Все находки по причинам</h2>\n{a17}\n\n<h2>Похожие страницы</h2>\n<div class="scroll"><table><thead><tr><th>страница</th><th>похожа на</th>\n<th class="n">совпадение</th></tr></thead><tbody>{a18}</tbody></table></div>\n{a19}\n<p class="note">Совпадение выше порога означает, что поисковик, скорее всего, оставит\nв индексе одну страницу из пары. На конвейере это происходит, когда шаблон\nдаёт больше текста, чем подставляемые данные.</p>\n</div></body></html>':
        '<!doctype html><!-- indexgap-report --><html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '<title>{a0}{a1}</title>\n<style>{a2}</style></head><body><div class="wrap">\n'
        '<h1>{a3}</h1>\n<p class="sub">{a4} · {a5} pages · {a6}</p>\n\n{a7}\n\n'
        '<div class="cards">\n'
        '  <div class="card"><div class="n">{a8}</div><div class="l">pages parsed</div></div>\n'
        '  <div class="card"><div class="n bad">{a9}</div><div class="l">critical</div></div>\n'
        '  <div class="card"><div class="n warn">{a10}</div><div class="l">warnings</div></div>\n'
        '  <div class="card"><div class="n bad">{a11}</div><div class="l">orphans with no inbound links</div></div>\n'
        '  <div class="card"><div class="n bad">{a12}</div><div class="l">pairs of similar pages</div></div>\n'
        '</div>\n\n{a13}\n\n{a14}\n{a15}\n{a16}\n\n<h2>Every finding by cause</h2>\n{a17}\n\n'
        '<h2>Similar pages</h2>\n'
        '<div class="scroll"><table><thead><tr><th>page</th><th>similar to</th>\n'
        '<th class="n">overlap</th></tr></thead><tbody>{a18}</tbody></table></div>\n{a19}\n'
        '<p class="note">An overlap above the threshold means the engine will most\n'
        'likely keep one page of the pair. In a generated pipeline this happens when\n'
        'the template contributes more text than the data does.</p>\n</div></body></html>',
    '<!doctype html><!-- indexgap-report --><html lang="ru"><head><meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Портфель — сводный отчёт</title>\n<style>{a0}{a1}</style></head><body><div class="wrap">\n<h1>Портфель</h1>\n<p class="sub">{a2} проектов · {a3} страниц · {a4} критичных\n· {a5}</p>\n\n{a6}\n{a7}\n{a8}\n{a9}\n{a10}\n{a11}\n</div></body></html>':
        '<!doctype html><!-- indexgap-report --><html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '<title>Portfolio — combined report</title>\n'
        '<style>{a0}{a1}</style></head><body><div class="wrap">\n<h1>Portfolio</h1>\n'
        '<p class="sub">{a2} projects · {a3} pages · {a4} critical\n· {a5}</p>\n\n'
        '{a6}\n{a7}\n{a8}\n{a9}\n{a10}\n{a11}\n</div></body></html>',
    '</tbody></table></div><p class="note">Пороги у профилей разные намеренно: 250 слов — норма для гайда и приговор для карточки события, а сверка фактов бессмысленна там, где датасета нет.</p>':
        '</tbody></table></div><p class="note">Profiles use different thresholds on '
        'purpose: 250 words is normal for a guide and absurd for an event card, and '
        'fact-checking is meaningless where there is no dataset.</p>',
    '</tbody></table></div><p class="note">Разбор адресный: конкретные URL по каждой причине лежат в JSON. Страница может попасть сразу в несколько причин — так и бывает.</p>':
        '</tbody></table></div><p class="note">The breakdown is addressable: the '
        'actual URLs behind each cause are in the JSON. A page can land in several '
        'causes at once — that is normal.</p>',
    '</tbody></table></div><p class="note">Страница, которой нет нигде, — почти всегда техническая проблема. Страница, которая есть в одном индексе и нет в другом, — уже вопрос оценки качества или скорости конкретного поисковика, и техническими правками обычно не лечится.</p>':
        '</tbody></table></div><p class="note">A page missing everywhere is almost '
        'always a technical problem. A page present in one index and absent from '
        'another is a question of that engine\'s quality judgement or speed, and '
        'technical fixes rarely help.</p>',
    '<br><span style="color:var(--warn)">Срабатывает почти на всех страницах всех проектов — это вопрос к порогу, а не к страницам.</span>':
        '<br><span style="color:var(--warn)">Fires on nearly every page of every '
        'project — that is a question about the threshold, not about the pages.</span>',
    '<div class="empty">Ничего не найдено.</div>': '<div class="empty">Nothing found.</div>',
    '<div class="first"><strong>Критичных находок нет.</strong> Дальше смотри в Search Console и Вебмастере: локальные проверки своё сказали.</div>':
        '<div class="first"><strong>No critical findings.</strong> From here look in '
        'Search Console and the other webmaster panels: the local checks have said '
        'what they can.</div>',
    '<div class="first"><strong>Начни с этого</strong><ol>':
        '<div class="first"><strong>Start here</strong><ol>',
    '<div class="pcard err"><div class="nm">{a0}</div><div class="pr">не проверен</div><div class="row" style="display:block">{a1}</div></div>':
        '<div class="pcard err"><div class="nm">{a0}</div><div class="pr">not '
        'checked</div><div class="row" style="display:block">{a1}</div></div>',
    '<div class="scroll"><table><thead><tr><th></th><th>код</th><th>что это</th>':
        '<div class="scroll"><table><thead><tr><th></th><th>code</th><th>what it means</th>',
    '<h2>Воронка конвейера</h2>': '<h2>The pipeline funnel</h2>',
    '<h2>Личное у каждого</h2><p class="note">Эти находки встретились ровно в одном проекте. Их чинят по месту, в отличие от общих граблей выше.</p><div class="grp-body"><ul>':
        '<h2>Specific to one project</h2><p class="note">These findings appeared in '
        'exactly one project. They are fixed locally, unlike the shared problems '
        'above.</p><div class="grp-body"><ul>',
    '<h2>Не проверены</h2><div class="grp-body"><ul>':
        '<h2>Not checked</h2><div class="grp-body"><ul>',
    '<h2>Общее в настройке сайтов</h2><p class="note">Это свойства сайта целиком, а не страниц: robots.txt, разметка, доступность краулерам. Доля страниц здесь бессмысленна, поэтому просто «есть».</p>':
        '<h2>Shared in how the sites are set up</h2><p class="note">These are '
        'properties of a whole site rather than of pages: robots.txt, markup, '
        'crawler access. A share of pages would be meaningless here, so it is just '
        '“present”.</p>',
    '<h2>Общие грабли на страницах</h2><div class="empty">Ни одна страничная находка не повторилась в двух проектах — либо проектов мало, либо они действительно разные.</div>':
        '<h2>Problems shared across pages</h2><div class="empty">No page-level '
        'finding repeated across two projects — either there are too few projects, '
        'or they really are that different.</div>',
    '<h2>Общие грабли на страницах</h2><p class="note">Находки, встретившиеся минимум в двух проектах. В ячейках — доля затронутых страниц проекта: сто находок на трёх тысячах страниц и десять на двадцати — одна болезнь разной громкости. Это уже не баг конкретного сайта, а свойство того, как эти сайты собираются: чинить надо привычку.</p>':
        '<h2>Problems shared across pages</h2><p class="note">Findings that appeared '
        'in at least two projects. Each cell shows the share of that project\'s '
        'pages: a hundred findings across three thousand pages and ten across '
        'twenty are the same disease at different volumes. This is no longer a bug '
        'in one site but a property of how these sites get built — the habit is what '
        'needs fixing.</p>',
    '<h2>Профили, по которым считали</h2><div class="scroll"><table><thead><tr><th>профиль</th><th>тип контента</th><th>что важно помнить</th></tr></thead><tbody>':
        '<h2>Profiles the numbers were computed with</h2><div class="scroll"><table>'
        '<thead><tr><th>profile</th><th>content type</th><th>worth remembering</th>'
        '</tr></thead><tbody>',
    '<h2>Сравнение поисковиков</h2><div class="scroll"><table><thead><tr><th>где страница</th><th class="n">страниц</th><th>что это значит</th></tr></thead><tbody>':
        '<h2>Engine by engine</h2><div class="scroll"><table><thead><tr><th>where the '
        'page is</th><th class="n">pages</th><th>what that means</th></tr></thead><tbody>',
    '<h2>Что пакет сказал о самих проектах</h2><div class="grp-body"><ul>':
        '<h2>What the tool said about the projects themselves</h2><div class="grp-body"><ul>',
    '<li><strong>{a0}</strong> — {a1} стр.: {a2}</li>':
        '<li><strong>{a0}</strong> — {a1} pages: {a2}</li>',
    '<p class="note">Каждый переход теряет страницы. Потери на разных переходах лечатся по-разному, поэтому важно видеть, где именно они происходят. Учти: экспорт «Страницы» из Search Console — это отчёт о показах, и страница в индексе без показов в него не попадает.</p>':
        '<p class="note">Every step loses pages, and losses at different steps are '
        'cured differently — which is why it matters where exactly they happen. Note '
        'that the Search Console “Pages” export is an impressions report: a page that '
        'is indexed but had no impressions will not appear in it.</p>',
    '<p class="note">Показано 60 пар из {a0}. Остальные — в JSON.</p>':
        '<p class="note">Showing 60 pairs of {a0}. The rest are in the JSON.</p>',
    '<p class="note">Показано {a0} из {a1}. Полный список — в JSON рядом с отчётом.</p>':
        '<p class="note">Showing {a0} of {a1}. The full list is in the JSON next to '
        'the report.</p>',
    '<td class="n share">есть</td>': '<td class="n share">yes</td>',
    '<tr><td colspan="3" style="color:var(--fg3)">Похожих страниц не найдено.</td></tr>':
        '<tr><td colspan="3" style="color:var(--fg3)">No similar pages found.</td></tr>',

    # ── словарь кодов находок ─────────────────────────────────────────────────
    "Canonical ведёт на другую страницу — эта отдаёт ей вес и сама из индекса выпадает.":
        "The canonical points at another page — this one hands over its weight and "
        "drops out of the index.",
    "H1 больше одного.": "More than one H1.",
    "Title короче рекомендованного.": "Title shorter than recommended.",
    "Title обрежется в выдаче.": "Title will be cut off in the results.",
    "robots.txt закрывает сайт целиком.": "robots.txt blocks the whole site.",
    "robots.txt не проверялся.": "robots.txt was not checked.",
    "robots.txt не прочитался — проверь путь в --robots.":
        "robots.txt could not be read — check the path in --robots.",
    "Анкоры вида «здесь» и «подробнее» не передают смысл.":
        "Anchors like “here” and “read more” carry no meaning.",
    "Блок JSON-LD не парсится — для поисковика его нет.":
        "The JSON-LD block does not parse — for a search engine it does not exist.",
    "В robots.txt закрыт краулер ИИ-поисковика.":
        "robots.txt blocks an AI-search crawler.",
    "В robots.txt нет строки Sitemap.": "robots.txt has no Sitemap line.",
    "В блоке JSON-LD нет @type.": "The JSON-LD block has no @type.",
    "В исходном HTML почти нет текста. Краулеры ИИ-поиска не исполняют JavaScript и увидят пустую страницу.":
        "There is almost no text in the source HTML. AI-search crawlers do not "
        "execute JavaScript and will see an empty page.",
    "В разметке FAQ есть вопросы, которых нет на странице. Это риск ручных санкций.":
        "The FAQ markup contains questions that are not on the page. That risks a "
        "manual action.",
    "В файле остался блок брифа или TODO — он уедет в текст страницы.":
        "A brief or TODO block is still in the file — it will ship inside the page "
        "text.",
    "В фронтматтере `status: draft`. Страница попадёт в сборку недописанной — допиши или исключи из публикации.":
        "The frontmatter says `status: draft`. The page will ship unfinished — "
        "finish it or exclude it from publication.",
    "Дата на странице прошла, а страница открыта для индексации. Поисковик показывает людям то, чего уже нет: закрой noindex, поставь редирект на актуальное или перепиши в отчёт о прошедшем.":
        "The date on the page has passed while the page stays open to indexing. The "
        "engine is showing people something that no longer exists: close it with "
        "noindex, redirect to the current one, or rewrite it as a report on what "
        "happened.",
    "Дата прошла, и страница уже закрыта от индексации — так и надо. Строка справочная.":
        "The date has passed and the page is already closed to indexing — as it "
        "should be. This line is informational.",
    "Длина description вне рекомендованного диапазона.":
        "Description length is outside the recommended range.",
    "Замечание к самому файлу: кодировка, фронтматтер, разметка.":
        "A note about the file itself: encoding, frontmatter, markup.",
    "Запрещён сниппет. Страница может быть в индексе, но не появится ни в расширенной выдаче, ни в ответах ИИ-поиска.":
        "Snippets are forbidden. The page may be indexed, but it will appear "
        "neither in rich results nor in AI-search answers.",
    "Изображения без alt.": "Images without alt text.",
    "На странице нет заголовков — структуры нет.":
        "The page has no headings — there is no structure.",
    "Ссылка ведёт на страницу, которой в сборке нет: на живом сайте это 404. Чаще всего шаблон ссылается на строку данных, которую фильтр не пропустил в генерацию. Убери ссылку из шаблона или верни страницу.":
        "The link points at a page the build does not have: a 404 on the live "
        "site. Most often the template links to a data row that a filter kept out "
        "of generation. Remove the link from the template or bring the page back.",
    "На странице осталось незаполненное место шаблона — `{{city}}`, `%CITY%`, `undefined`, `NaN`, пустое место в заголовке или lorem ipsum. Читатель и поисковик видят шов генератора. Чинится в данных или в шаблоне, а не на странице.":
        "A template slot was left unfilled — `{{city}}`, `%CITY%`, `undefined`, `NaN`, an empty place in the title, or lorem ipsum. Readers and search engines see the generator's seam. It is fixed in the data or the template, not on the page.",
    "В тексте остался ответ модели вместо текста страницы: «As an AI language model…», «Certainly! Here is…». Такую страницу видно сразу, и её нельзя публиковать.":
        "The model's reply was left in place of the page text: “As an AI language model…”, “Certainly! Here is…”. Such a page is obvious at a glance and must not be published.",
    "Часть текста прочитана не в той кодировке: «CafÃ©», «â€™». Обычно это данные, сохранённые в UTF-8 и прочитанные как Latin-1 где-то в конвейере.":
        "Part of the text was read in the wrong encoding: “CafÃ©”, “â€™”. Usually it is data saved as UTF-8 and read as Latin-1 somewhere in the pipeline.",
    "robots.txt не пускает поисковик на эту страницу: она есть в сборке и, скорее всего, в sitemap, но текст её прочитан не будет.":
        "robots.txt does not let the search engine into this page: it is in the build and most likely in the sitemap, but its text will not be read.",
    "Разметка называет цену, рейтинг или число отзывов, которых нет в видимом тексте. Google требует, чтобы структурированные данные повторяли страницу.":
        "The markup names a price, a rating or a review count the visible text does not show. Google requires structured data to repeat the page.",
    "Страница раздела не ссылается на часть своих страниц: до них доходят только через sitemap, и вес раздела до них не доходит.":
        "The section page does not link to some of its pages: they are reached only through the sitemap, and the section's weight does not reach them.",
    "В заголовке прошлый год: страница обещает свежесть, а выглядит заброшенной.":
        "A past year in the heading: the page promises freshness and looks abandoned.",
    "title и H1 говорят о разном — поисковик может переписать заголовок в выдаче.":
        "The title and the H1 talk about different things — the search engine may rewrite the title in results.",
    "Нет og:title или og:image — ссылка на страницу в соцсетях и мессенджерах выходит без превью.":
        "No og:title or og:image — a link to the page in social networks and messengers shows without a preview.",
    "Нет meta viewport — на телефоне страница не адаптирована, а Google индексирует мобильную версию.":
        "No meta viewport — the page is not adapted to phones, and Google indexes the mobile version.",
    "HTML тяжелее 2 МБ: Googlebot читает первые 2 МБ, хвост страницы в индекс не попадает.":
        "HTML heavier than 2 MB: Googlebot reads the first 2 MB, the tail of the page does not reach the index.",
    "Картинки тяжелее 1 МБ замедляют загрузку на телефоне.":
        "Images heavier than 1 MB slow loading down on a phone.",
    "Сверка с датасетом покрыла меньше половины страниц: числа остальных не проверены, и «критичных 0» ничего о них не говорит.":
        "The dataset check covered less than half of the pages: the numbers of the rest were not checked, and \"0 critical\" says nothing about them.",
    "На страницу не ведёт ни одна внутренняя ссылка. В sitemap она есть, но краулер до неё не дойдёт. Поставь ссылки с хабовых страниц раздела.":
        "No internal link points at this page. It is in the sitemap, but the "
        "crawler will not get there. Link to it from the section's hub pages.",
    "Не нашлось ни одного абзаца.": "No paragraph was found.",
    "Не указан автор или организация.": "No author or organisation is given.",
    "Нет H1 — поисковику нечем определить тему страницы.":
        "No H1 — the engine has nothing to determine the page's topic from.",
    "Нет meta description — поисковик соберёт сниппет сам.":
        "No meta description — the engine will assemble a snippet itself.",
    "Нет title.": "No title.",
    "Нет машиночитаемой даты.": "No machine-readable date.",
    "Нет ни списков, ни таблиц.": "Neither lists nor tables.",
    "Ни один подзаголовок не сформулирован как вопрос. Это эвристика из корреляционных исследований, а не требование поисковика: вопросы в подзаголовках упрощают цитирование, но переписывать под них живой текст не обязательно.":
        "Not a single subheading is phrased as a question. This is a heuristic from "
        "correlation studies, not a search engine requirement: question subheadings "
        "make a page easier to quote, but there is no need to rewrite good text "
        "around them.",
    "Одинаковое начало текста на многих страницах.":
        "Many pages open with the same sentence.",
    "Одинаковый description у нескольких страниц.":
        "Several pages share the same description.",
    "Одинаковый title у нескольких страниц — склейка в выдаче.":
        "Several pages share the same title — they will be collapsed in the results.",
    "Одинаковый скелет заголовков на многих страницах — для поисковика это признак штамповки.":
        "The same heading skeleton across many pages — to a search engine that reads "
        "as stamping.",
    "От главной до страницы нельзя дойти по ссылкам.":
        "The page cannot be reached from the home page by following links.",
    "Отчёт конвейера": "Pipeline report",
    "Очень длинные абзацы плохо извлекаются.":
        "Very long paragraphs extract badly.",
    "Первый абзац длинноват для цитирования. Это эвристика, а не правило поисковика: ИИ-ответы чаще берут короткий самостоятельный ответ, но длинный абзац их не запрещает.":
        "The first paragraph is a bit long to quote. This is a heuristic, not a "
        "search engine rule: AI answers more often lift a short self-contained "
        "answer, but a long paragraph does not rule a page out.",
    "Первый абзац слишком короткий для самостоятельного ответа.":
        "The first paragraph is too short to stand as an answer.",
    "Первый абзац — разгон, а не ответ. Именно первый абзац цитируют ИИ-поиск и блок быстрых ответов.":
        "The first paragraph is a run-up, not an answer. The first paragraph is "
        "exactly what AI search and the featured-answer block quote.",
    "Похожа на другую страницу, но ниже порога дубля. Повод посмотреть.":
        "Similar to another page but below the duplicate threshold. Worth a look.",
    "Почти совпадает с другой страницей. Поисковик оставит одну. Если у страниц разные запросы (город, модель, услуга), дай каждой свои данные — canonical здесь спрячет страницы, ради которых их делали. Если запрос один — оставь одну страницу и уведи остальные на неё.":
        "Nearly identical to another page. The engine will keep one. If the pages "
        "target different queries (city, model, service), give each its own data — "
        "a canonical here would hide the very pages they were built for. If the "
        "query is the same, keep one page and send the rest to it.",
    "Слишком много кликов от главной.": "Too many clicks from the home page.",
    "Страница закрыта от индексации. Если это ошибка шаблона — убери мета-тег robots.":
        "The page is closed to indexing. If that is a template mistake, remove the "
        "robots meta tag.",
    "Текста меньше порога. Порог правится в indexgap.json — для карточки товара 250 слов абсурдны, для гайда нормальны.":
        "Less text than the threshold. The threshold lives in indexgap.json — 250 "
        "words is absurd for a product card and normal for a guide.",
    "Числа со словами, которых нет в данных. Часть таких — обычная речь («3 шага», «5 звёзд»), часть — выдумка агента. Список для просмотра глазами, а не приговор.":
        "Numbers with words that do not appear in your data. Some of these are "
        "ordinary phrasing (“3 steps”, “5 stars”), some are invented by the model. "
        "A list to read with your own eyes, not a verdict.",
    "Число в тексте, которого нет в данных. Проверь по строке датасета и либо исправь, либо убери утверждение.":
        "A number in the text that is not in your data. Check it against the "
        "dataset row and either correct it or drop the claim.",
    "Шаблон вытеснил содержание: уникального текста меньше четверти.":
        "The template has crowded out the content: less than a quarter of the text "
        "is unique.",
    "внимание": "warning",
    "критично": "critical",
    "мелочь": "minor",
    "похожих пар": "similar pairs",
    "сирот": "orphans",
    "страниц": "pages",

    # ── главная-заглушка и запаркованные переводы ─────────────────────
    "Переводы закрыты от индекса и отдают canonical оригиналу — правилом шаблона, а не постранично.":
        "Translations are closed from the index and hand their canonical to the "
        "original — by a template rule, not page by page.",

    # ── заголовок причин зависит от того, что доказывает выгрузка ──────
    "<h2>Почему страницы не в индексе</h2>":
        "<h2>Why pages are not indexed</h2>",
    "<div class=\"scroll\"><table><thead><tr><th>причина</th><th class=\"n\">страниц</th><th>что делать</th></tr></thead><tbody>":
        "<div class=\"scroll\"><table><thead><tr><th>cause</th><th class=\"n\">pages</th><th>what to do</th></tr></thead><tbody>",
    "<h2>Почему у страниц нет показов</h2>":
        "<h2>Why pages have no impressions</h2>",
    "\nПочему у страниц нет показов:":
        "\nWhy pages have no impressions:",

    # ── риск по шаблонам ──────────────────────────────────────────────────────
    '<h2>Риск по шаблонам</h2><div class="scroll"><table><thead><tr><th>шаблон</th><th class="n">страниц</th><th class="n">критично</th><th class="n">внимание</th><th>частые коды</th><th class="n">риск</th></tr></thead><tbody>':
        '<h2>Risk by template</h2><div class="scroll"><table><thead><tr><th>template</th>'
        '<th class="n">pages</th><th class="n">critical</th><th class="n">warnings</th>'
        '<th>frequent codes</th><th class="n">risk</th></tr></thead><tbody>',
    '</tbody></table></div><p class="note">Риск 0–100 — средняя по страницам шаблона тяжесть самой тяжёлой находки: критичная весит от 0,5 до 1 в зависимости от кода, внимание — от 0,15 до 0,3. В «other» сложены шаблоны меньше десяти страниц.</p>':
        '</tbody></table></div><p class="note">Risk 0–100 is the average, over the '
        'template\'s pages, of the severity of each page\'s worst finding: a critical '
        'one weighs 0.5 to 1 depending on the code, a warning 0.15 to 0.3. Templates '
        'under ten pages are folded into “other”.</p>',

    # ── diff ──────────────────────────────────────────────────────────────────
    "Страница была в старой сборке и пропала из новой. Если она была открыта для индекса и редиректа на неё нет — на живом сайте по адресу с показами будет 404. Верни страницу или поставь 301 на ближайшую замену.":
        "The page was in the old build and is missing from the new one. If it was open "
        "to indexing and nothing redirects it, the live site will answer 404 at an "
        "address that had impressions. Bring the page back or add a 301 to the closest "
        "replacement.",
    "Страница пропала или стала заглушкой, но адрес переведён редиректом — посетители и вес уйдут по нему. Проверь, что цель редиректа существует.":
        "The page is gone or became a stub, but the address is redirected — visitors "
        "and link equity follow it. Make sure the redirect target exists.",
    "Страница была открыта для индекса и закрылась: появился noindex, canonical стал вести на другую страницу или она стала черновиком. Если это сделал шаблон — закроется весь раздел.":
        "The page was open to indexing and is now closed: noindex appeared, the "
        "canonical points to another page, or it became a draft. If the template did "
        "this, the whole section closes.",
    "Появился запрет сниппета: страница останется в индексе, но пропадёт из ответов ИИ-поиска и расширенной выдачи.":
        "A snippet ban appeared: the page stays indexed but disappears from AI-search "
        "answers and rich results.",
    "Текст сократился больше чем вдвое. Обычно это поломка генератора или данных, а не правка редактора.":
        "The text shrank by more than half. Usually that is a broken generator or "
        "dataset, not an editor's change.",
    "title, H1 или description поменялись у многих страниц одного шаблона сразу — это правка шаблона. Убедись, что она намеренная: поисковик переоценит все эти страницы.":
        "title, H1 or description changed on many pages of one template at once — a "
        "template change. Make sure it is intended: the engine will re-evaluate all "
        "these pages.",
    "Критичная находка `check`, которой в старой сборке не было.":
        "A critical `check` finding that the old build did not have.",
    "Страница была закрыта от индекса и открылась.":
        "The page was closed to indexing and is now open.",
    "Новые страницы по шаблонам адресов.": "New pages by URL template.",
    '<!doctype html><!-- indexgap-report --><html lang="ru"><head><meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Что сломает деплой{a0}</title>\n<style>{a1}</style></head><body><div class="wrap">\n<h1>Что сломает деплой</h1>\n<p class="sub">{a2} · было {a3} → стало {a4} · {a5}</p>\n<div class="cards">\n  <div class="card"><div class="n">{a6}</div><div class="l">страниц было</div></div>\n  <div class="card"><div class="n">{a7}</div><div class="l">страниц стало</div></div>\n  <div class="card"><div class="n bad">{a8}</div><div class="l">критично</div></div>\n  <div class="card"><div class="n warn">{a9}</div><div class="l">внимание</div></div>\n  <div class="card"><div class="n">{a10}</div><div class="l">исчезло страниц</div></div>\n  <div class="card"><div class="n">{a11}</div><div class="l">новых страниц</div></div>\n</div>\n<p class="note">{a12}</p>\n{a13}\n<h2>Изменения по видам</h2>\n{a14}\n{a15}\n</div></body></html>':
        '<!doctype html><!-- indexgap-report --><html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '<title>What the deploy breaks{a0}</title>\n<style>{a1}</style></head><body><div class="wrap">\n'
        '<h1>What the deploy breaks</h1>\n<p class="sub">{a2} · before {a3} → after {a4} · {a5}</p>\n'
        '<div class="cards">\n'
        '  <div class="card"><div class="n">{a6}</div><div class="l">pages before</div></div>\n'
        '  <div class="card"><div class="n">{a7}</div><div class="l">pages after</div></div>\n'
        '  <div class="card"><div class="n bad">{a8}</div><div class="l">critical</div></div>\n'
        '  <div class="card"><div class="n warn">{a9}</div><div class="l">warnings</div></div>\n'
        '  <div class="card"><div class="n">{a10}</div><div class="l">pages gone</div></div>\n'
        '  <div class="card"><div class="n">{a11}</div><div class="l">new pages</div></div>\n'
        '</div>\n<p class="note">{a12}</p>\n{a13}\n<h2>Changes by kind</h2>\n{a14}\n{a15}\n'
        '</div></body></html>',
    '<p class="note">Проверки check по обеим сборкам: новых критичных {a0}, новых «внимание» {a1}, исчезло критичных {a2}. Полные списки — в JSON.</p>':
        '<p class="note">check findings on both builds: {a0} new critical, {a1} new '
        'warnings, {a2} critical gone. The full lists are in the JSON.</p>',
    "Редиректы учтены: {a0}.": "Redirects taken into account: {a0}.",
    "Файлов редиректов рядом с новой сборкой нет: исчезнувшая страница считается 404.":
        "No redirect files next to the new build: a page that disappears counts as a 404.",
    '<h2>Правки шаблонов</h2><div class="scroll"><table><thead><tr><th>шаблон</th><th>поле</th><th class="n">страниц</th><th>например</th></tr></thead><tbody>':
        '<h2>Template changes</h2><div class="scroll"><table><thead><tr><th>template</th>'
        '<th>field</th><th class="n">pages</th><th>for example</th></tr></thead><tbody>',
    '<div class="empty">Сборки не различаются ничем, что видит поисковик.</div>':
        '<div class="empty">The builds differ in nothing a search engine sees.</div>',
}
