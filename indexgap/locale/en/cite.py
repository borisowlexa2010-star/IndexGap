# -*- coding: utf-8 -*-
"""cite — замер цитируемости в ИИ-поиске, English."""

MESSAGES = {
    # ── ход выполнения ────────────────────────────────────────────────────────
    "Домен: {a0}": "Domain: {a0}",
    "Спросим: {a0}": "Will ask: {a0}",
    "Вопросов: {a0}   Прогонов на вопрос: {a1}   Всего вызовов: {a2}":
        "Questions: {a0}   Runs per question: {a1}   Calls in total: {a2}",
    "Вопросы взяты из семантики: {a0} шт.":
        "Questions taken from the keyword set: {a0}",
    "\nЭто пробный прогон: ничего не отправлено. Чтобы спросить по-настоящему — добавь --send. Вызовы платные, счёт придёт на твои ключи.":
        "\nThis was a dry run: nothing was sent. To ask for real, add --send. The "
        "calls cost money, and the bill lands on your keys.",
    "  … и ещё {a0}": "  … and {a0} more",
    "\nДоля прогонов, где домен попал в источники:":
        "\nShare of runs where the domain appeared in the sources:",
    "\nВопросы, где не процитировали ни разу: {a0} из {a1}":
        "\nQuestions with no citation at all: {a0} of {a1}",
    "      вместо вас: {a0}": "      cited instead: {a0}",
    "\nДанные: {a0}": "\nData: {a0}",

    # ── чего не хватает ───────────────────────────────────────────────────────
    "Ни одного ключа не найдено. Нужен хотя бы один:":
        "No key was found. At least one is needed:",
    "\n  Это единственная часть пакета, которой нужны ключи и деньги. Всё остальное работает без них.":
        "\n  This is the only part of the package that needs keys and money. "
        "Everything else works without them.",
    "ни одного ключа не найдено. Замер цитируемости — единственная часть пакета, которой нужны ключи и деньги; всё остальное работает без них.\n    Нужен хотя бы один:\n      {a0}":
        "no key was found. Measuring citations is the only part of this package "
        "that needs keys and money; everything else works without them.\n"
        "    At least one is needed:\n      {a0}",
    "нет ключа для {a0}: задай {a1}": "no key for {a0}: set {a1}",
    "Не указан домен, по которому считать цитируемость.\n    --domain example.com, либо `site` в indexgap.json.":
        "No domain given to look for in the sources.\n"
        "    --domain example.com, or `site` in indexgap.json.",
    "не указан домен: --domain example.com": "no domain given: --domain example.com",
    "Не заданы вопросы. Цитируют в ответе на вопрос пользователя, а не на запрос о компании, поэтому вопросы нужны настоящие.\n    --prompts questions.txt, или --prompt \"…\" несколько раз,\n    или --dataset keywords.csv, чтобы взять их из семантики.":
        "No questions given. Citations happen in answers to a user's question, "
        "not to a query about your company, so the questions have to be real "
        "ones.\n    --prompts questions.txt, or --prompt \"…\" repeated,\n"
        "    or --dataset keywords.csv to take them from your keyword set.",
    "Файл с вопросами {a0} не найден.": "Questions file {a0} not found.",
    "{a0}: ни одного вопроса.": "{a0}: not a single question.",
    "Неизвестный провайдер: {a0}. Доступны: {a1}":
        "Unknown provider: {a0}. Available: {a1}",
    "неизвестный провайдер: {a0}": "unknown provider: {a0}",
    "{a0} ответил {a1}. {a2}\n    Чаще всего это чужое имя модели или ключ без доступа к поиску. Имя модели задаётся в indexgap.json, раздел `cite`.":
        "{a0} answered {a1}. {a2}\n    Usually that is a model name it does not "
        "know, or a key without access to search. The model name goes in "
        "indexgap.json, section `cite`.",
    "{a0} недоступен: {a1}": "{a0} is unreachable: {a1}",
    "{a0} вернул не JSON": "{a0} did not return JSON",

    # ── оговорки, без которых цифру нельзя показывать ─────────────────────────
    "Замерен API, а не приложение. Совпадение с тем, что видит человек в ChatGPT или Gemini, есть, равенства нет — и в первую очередь потому, что в приложении поиск включается иначе.":
        "What was measured is the API, not the app. It overlaps with what a "
        "person sees in ChatGPT or Gemini, but it is not the same thing — first "
        "of all because search is triggered differently in the app.",
    "Ответ недетерминирован: тот же вопрос дважды даёт разные источники. Поэтому в таблице доля прогонов, а не «да/нет». Одного прогона не хватает ни на какой вывод.":
        "The answer is not deterministic: the same question twice returns "
        "different sources. That is why the table shows a share of runs, not "
        "yes/no. One run is not enough for any conclusion.",
    "Цитируемость почти не зависит от того, что можно поправить в файлах проекта. По данным Ahrefs на 75 000 брендов она сильнее всего связана с упоминаниями вне сайта (0,66–0,74), а с числом страниц — 0,19. Этот замер — термометр, а не лечение.":
        "Being cited depends very little on anything you can fix in the project's "
        "files. Across 75,000 brands Ahrefs found it correlates most with "
        "mentions off your site (0.66–0.74) and with page count at 0.19. This "
        "measurement is a thermometer, not a cure.",
    "Единственный из четырёх, кто по замыслу отвечает с источниками. Ближе всех к тому, что видит человек в самом сервисе.":
        "The only one of the four designed to answer with sources. The closest to "
        "what a person sees in the service itself.",
    "Поиск включается инструментом, и модель сама решает, искать ли. В самом ChatGPT это работает иначе — цифры близки, но не равны.":
        "Search is switched on by a tool, and the model decides whether to search "
        "at all. In ChatGPT itself this works differently — the numbers are close, "
        "not equal.",
    "Grounding через API — не то же самое, что AI Overviews в обычной выдаче Google. Считать одним нельзя.":
        "Grounding through the API is not the same as AI Overviews in Google's "
        "ordinary results. They cannot be counted as one thing.",
    "Ищет и по вебу, и по X. Доля источников из X в ответах заметна — это особенность сервиса, а не вашего сайта.":
        "It searches both the web and X. The share of X sources in the answers is "
        "noticeable — that is a property of the service, not of your site.",

    # ── справка по аргументам ─────────────────────────────────────────────────
    "замер цитируемости в ИИ-поиске (нужны свои ключи)":
        "measure citations in AI search (needs your own keys)",
    "домен, который ищем в источниках": "the domain to look for in the sources",
    "название бренда — ищется в тексте ответа":
        "the brand name — looked for in the answer text",
    "файл с вопросами, по одному в строке": "file of questions, one per line",
    "вопрос; можно повторять": "a question; repeatable",
    "взять вопросы из семантики": "take the questions from the keyword set",
    "сколько вопросов взять из семантики":
        "how many questions to take from the keyword set",
    "кого спрашивать; по умолчанию всех, чей ключ найден":
        "who to ask; by default everyone whose key was found",
    "прогонов на вопрос: ответ недетерминирован, одного мало":
        "runs per question: the answer is not deterministic, one is not enough",
    "действительно спросить; без него — пробный прогон":
        "actually ask; without it this is a dry run",
}
