# -*- coding: utf-8 -*-
"""
Наряды на починку: находки проверки → задания, по которым работает агент.

Симметрия с `plan`. Там бриф пишется ДО генерации и говорит, какой должна
быть новая страница. Здесь бриф пишется ПОСЛЕ проверки и говорит, что именно
на существующей странице не так и чем это чинится.

**Пакет по-прежнему ничего не пишет и не переписывает.** Он формулирует
задачу; текст пишет человек или агент. Это не осторожность, а условие, при
котором проверки вообще имеют смысл: главная находка пакета сверяет числа
на странице со строкой датасета, и если бы те же числа подставил сам пакет,
проверка проверяла бы себя и всегда была бы зелёной.

Три правила раскладки, без которых наряды превратились бы в тот же шум,
что и отчёт из трёх тысяч строк:

  * **Свойство шаблона — один наряд, а не три тысячи.** Код, срабатывающий
    почти на всех страницах (или почти на всех страницах одного языка),
    чинится один раз в шаблоне. Такие находки уходят в `_template.md`.
  * **Дубли чинятся группами.** 588 почти-дублей на живом каталоге — это
    72 группы. Наряд выписывается на группу: одна страница остаётся, остальные
    разводятся по интентам. Наряд на страницу тут бесполезен: в одиночку
    её не починить.
  * **Свойства сайта — отдельно.** robots.txt, hreflang-кластер, разметка
    относятся к сайту, а не к странице, и живут в `_site.md`.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict

from .core import SourceError
from .i18n import N_, tr

# Что делать — императивом. Описание кода объясняет, что случилось;
# здесь сказано, что с этим делать руками.
FIX = {
    "unsupported-number": N_("Найди это число в строке датасета. Если его там нет — "
                             "убери утверждение целиком или замени на то, что есть "
                             "в данных. Не подбирай похожее число: страница про "
                             "визы с выдуманным сроком — это вред человеку, "
                             "а не недобор трафика."),
    "check-by-eye": N_("Просмотри эти числа глазами. Часть — обычная речь, часть — "
                       "выдумка. Оставь только то, что можешь подтвердить."),
    "unfilled-slot": N_("Найди, откуда приходит пустое значение: строка датасета без поля, опечатка в имени переменной шаблона или поле, которое генератор не подставляет. Почини данные или шаблон и пересобери — править готовую страницу бесполезно, следующая сборка вернёт шов."),
    "llm-leftover": N_("Перегенерируй или перепиши этот текст. В конвейере отбрасывай ответы модели с отказом или вступлением до того, как они попадут в шаблон."),
    "mojibake": N_("Найди шаг конвейера, где UTF-8 читается как Latin-1 или cp1252 (обычно импорт CSV или ответ API), и укажи кодировку явно. Пересобери страницы."),
    "brief-left": N_("Удали блок брифа или TODO из файла."),
    "still-draft": N_("Допиши страницу и убери `status: draft` из фронтматтера. "
                      "Пока метка стоит, страница не попадёт ни в sitemap, "
                      "ни в IndexNow."),
    "noindex": N_("Убери мета-тег robots, если закрытие от индексации не было "
                  "задумано. Если было — оставь и не трогай эту находку."),
    "nosnippet": N_("Убери `nosnippet` или `max-snippet:0`: без права на сниппет "
                    "страница не попадёт ни в расширенную выдачу, ни в ответы "
                    "ИИ-поиска."),
    "canonical-elsewhere": N_("Проверь шаблон: canonical должен указывать на саму "
                              "страницу. Сейчас она отдаёт вес другой и выпадает "
                              "из индекса."),
    "jsonld-mismatch": N_("Бери числа разметки из того же поля строки данных, что и текст страницы. Если на странице цены нет — убери её и из разметки, а не наоборот."),
    "hub-missing-links": N_("Пусть шаблон раздела выводит ссылки на все страницы раздела — списком, по алфавиту или с пагинацией. Ссылки только из sitemap и случайных блоков «похожие» не в счёт."),
    "stale-year": N_("Убери год из шаблона заголовка или подставляй текущий из данных сборки. Если страница — история того года, поставь ей дату публикации."),
    "title-h1-mismatch": N_("Своди title и H1 к одному обещанию: пусть оба берут главный запрос строки, а бренд остаётся в хвосте title."),
    "no-og": N_("Добавь в шаблон og:title и og:image — картинку страницы или раздела, не логотип на все страницы."),
    "no-viewport": N_("Добавь в шаблон <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">."),
    "heavy-html": N_("Найди, что раздувает HTML: встроенные данные для гидратации, inline-SVG, огромные таблицы. Вынеси их в отдельные файлы или разбей страницу."),
    "heavy-images": N_("Сожми картинки и отдай WebP или AVIF; для превью — отдельные уменьшенные копии."),
    "dataset-unbound": N_("Свяжи страницы со строками: добавь в датасет колонку slug или url с адресом страницы, или пиши ключ строки в `keyword:` во фронтматтере, или <meta name=\"keyword\"> в шаблоне."),
    "broken-link": N_("Ссылки ведут на страницы, которых нет в сборке. Найди, откуда шаблон берёт "
                      "эти адреса, и либо убери ссылку, либо сгенерируй страницу. Если сервер "
                      "перенаправляет эти адреса — проверь, что перенаправление действительно есть."),
    "wrong-link-form": N_("Пиши ссылку в той форме, в какой страница лежит в сборке: тот же регистр букв, /about/ для about/index.html, /faq.html или /faq для faq.html. Если хостинг сам перенаправляет эту форму — добавь правило в _redirects, netlify.toml или vercel.json, и находка уйдёт."),
    "orphan": N_("Поставь ссылки на эту страницу с хабовых страниц раздела. "
                 "Анкор — описательный, не «подробнее»."),
    "unreachable": N_("Добавь путь от главной: страница есть в sitemap, но "
                      "краулер до неё не доходит."),
    "deep": N_("Подними страницу выше в структуре или дай на неё ссылку "
               "с более близкой к главной."),
    "low-uniqueness": N_("Добавь то, что отличает эту страницу от соседних: "
                         "конкретику из её строки данных. Шаблонного текста "
                         "должно стать меньше, чем своего."),
    "thin": N_("Хаб, листинг и главная ценны ссылками, а не словами: закрывать их "
               "нельзя. Страницу строки наполни фактами из её строки данных; если "
               "фактов нет — спроси, нужна ли эта страница. Порог — `checks.thin_words` "
               "в indexgap.json: понижай его, только если этот тип контента законно "
               "короткий, а не дописывай воду."),
    "template-skeleton": N_("Поменяй структуру заголовков под данные этой строки. "
                            "Одинаковый скелет на всех страницах читается "
                            "как штамповка."),
    "same-opening": N_("Перепиши первый абзац так, чтобы он отвечал на запрос "
                       "именно этой страницы."),
    "no-title": N_("Добавь title."),
    "title-short": N_("Удлини title до рекомендованного диапазона."),
    "title-long": N_("Сократи title: в выдаче он обрежется."),
    "no-description": N_("Добавь meta description."),
    "description-length": N_("Приведи description к рекомендованной длине."),
    "no-h1": N_("Добавь H1 — по нему поисковик определяет тему страницы."),
    "many-h1": N_("Оставь один H1, остальные понизь до H2."),
    "no-headings": N_("Добавь структуру заголовков."),
    "duplicate-title": N_("Сделай title уникальным: сейчас он совпадает "
                          "с другими страницами, и в выдаче они склеятся."),
    "duplicate-description": N_("Сделай description уникальным."),
    "vague-anchor": N_("Замени анкоры на описательные: из ссылки должно быть "
                       "понятно, куда она ведёт."),
    "source-note": N_("Почини сам файл — кодировку или фронтматтер. Пока он "
                      "читается неверно, остальные находки на нём недостоверны."),
    "stale-event": N_("Событие прошло, а страница открыта для индексации. Закрой "
                      "noindex, поставь редирект на актуальное или перепиши "
                      "в отчёт о прошедшем."),
    "js-shell": N_("Нужен серверный рендеринг или пререндер: краулеры ИИ-поиска "
                   "не исполняют JavaScript. Это правится в сборке сайта, "
                   "а не в тексте страницы."),
    "answer-preamble": N_("Убери разгон из первого абзаца: он должен быть прямым "
                          "ответом на запрос. Именно его цитируют."),
    "answer-short": N_("Расширь первый абзац до самостоятельного ответа."),
    "answer-long": N_("Сократи первый абзац: длинный блок не цитируют целиком."),
    "no-question-headings": N_("Переформулируй часть подзаголовков как вопросы: "
                               "формат «вопрос → ответ» цитируется заметно чаще."),
    "long-paragraph": N_("Разбей длинные абзацы подзаголовками."),
    "no-structure": N_("Добавь списки или таблицы: структурные элементы повышают "
                       "шанс попасть в ответ."),
    "no-date": N_("Добавь машиночитаемую дату — в JSON-LD или фронтматтер."),
    "no-author": N_("Укажи автора или организацию."),
    "jsonld-broken": N_("Почини JSON-LD: сейчас он не парсится, и для поисковика "
                        "его нет."),
    "jsonld-faq-invisible": N_("Убери из разметки FAQ вопросы, которых нет "
                               "на странице, или добавь их в текст. Разметка, "
                               "не совпадающая со страницей, — риск санкций."),
    "img-no-alt": N_("Добавь alt изображениям."),
    "hreflang-no-self": N_("Добавь в кластер ссылку на саму страницу: без "
                           "self-ссылки кластер невалиден целиком."),
    "hreflang-no-return": N_("Сделай связь взаимной: односторонняя отбрасывается "
                             "целиком, а не учитывается частично."),
    "translations-parked": N_("Реши по каждому языку. Перевод готов — открой его: "
                              "свой canonical и index. Не готов — держи закрытым, "
                              "но убери hreflang и с него, и со ссылающихся на "
                              "него страниц: сейчас сигналы спорят, и поисковик "
                              "выбирает сам."),
    "hreflang-static-cluster": N_("Шаблон печатает кластер главной на каждой "
                                  "странице. Кластер должен собираться "
                                  "из переводов ЭТОЙ страницы."),
    "hreflang-canonical-conflict": N_("Верни canonical на саму страницу: сейчас "
                                      "он уводит на другой язык и отменяет "
                                      "hreflang."),
    "hreflang-missing": N_("Добавь альтернативы для языковых версий этой страницы."),
    "hreflang-bad-code": N_("Поправь код языка: чаще всего вместо языка написана "
                            "страна."),
    "robots-blocks-page": N_("Найди правило Disallow, которое закрывает этот раздел, и реши: если раздел должен быть в поиске — убери правило; если нет — убери страницы из sitemap и поставь на них noindex (его поисковик увидит, только если обход разрешён)."),
    "robots-blocks-all": N_("Убери `Disallow: /` — сейчас сайт закрыт от всех "
                            "поисковиков."),
    "ai-crawler-blocked": N_("Реши сознательно, нужен ли этот краулер, и открой "
                             "его в robots.txt, если нужен."),
    "robots-no-sitemap": N_("Добавь строку `Sitemap:` в robots.txt."),
    "robots-unreadable": N_("Положи robots.txt в корень сайта или укажи путь "
                            "к нему через --robots. Пока файла нет, проверки "
                            "доступа краулеров не сделаны — это не значит, "
                            "что доступ открыт."),
    "no-robots": N_("Создай robots.txt: без него нельзя ни закрыть лишнее, "
                    "ни указать sitemap."),

    # ── находки, у которых наряд раньше выходил пустым ──────────────────────
    "near-duplicate": N_("Реши, что делать с группой целиком. Разные запросы (города, "
                         "модели) — дай каждой странице свои данные из датасета: цены, "
                         "адреса, отзывы, а не другое имя в том же тексте. Один запрос — "
                         "оставь одну страницу и уведи остальные на неё редиректом. "
                         "Одну страницу из группы починить нельзя."),
    "similar": N_("Проверь, не выросли ли эти страницы из двух ключей с одним "
                  "интентом. Если да — объединяй; если нет, добавь каждой то, чего "
                  "нет у соседней."),
    "stale-closed": N_("Реши, чем стала страница: архивом или невыполнимым обещанием. "
                       "Архив пометь датой окончания прямо в тексте, обещание убери из "
                       "индекса."),
    "hreflang-unknown-target": N_("Убери из кластера адреса, которых нет среди страниц сайта, или "
                                  "исправь их. Сейчас кластер ссылается в пустоту, и поисковик вправе "
                                  "не считать его вовсе."),
    "hreflang-lang-mismatch": N_("Приведи объявленный язык в соответствие с языком текста. Пока они "
                                 "расходятся, поисковик показывает страницу не тем читателям — и "
                                 "считает это правильным результатом."),
    "lang-script-mismatch": N_("Поставь в шаблоне <html lang> по языку текста. На многоязычном "
                               "сайте бери его из данных страницы, а не из общего шаблона."),
    "hreflang-target-blocked": N_("Открой страницу-альтернативу для индексации или убери её из "
                                  "кластера: закрытая цель ослабляет весь кластер."),
    "jsonld-no-type": N_("Добавь `@type` в блок JSON-LD. Без него разметка разбирается, но "
                         "не значит ничего."),
    "no-answer": N_("Начни страницу абзацем, который отвечает на её запрос. Сейчас на "
                    "ней нет ничего, что можно процитировать как ответ."),
}

# Находки, которые чинятся один раз в шаблоне, а не постранично.
GROUPED = {"near-duplicate", "similar"}
SITE_LEVEL = {"robots-blocks-all", "ai-crawler-blocked", "robots-no-sitemap",
              "robots-unreadable", "no-robots", "hreflang-static-cluster",
              "translations-parked", "heavy-images", "dataset-unbound"}

HEADER = "<!-- indexgap-brief -->"


def _slug(url: str) -> str:
    path = re.sub(r"^https?://[^/]+", "", url or "").strip("/")
    path = re.sub(r"[^\w\-/]+", "-", path, flags=re.UNICODE).strip("-/")
    return path or "index"


def _fix(code: str) -> str:
    found = FIX.get(code)
    return tr(found) if found else ""


def _where(page, root: str) -> str:
    """
    Путь к файлу — от корня проекта, то есть от текущего каталога. Путь от
    каталога страниц (`plumbing/dallas/index.html` вместо
    `out/plumbing/dallas/index.html`) из корня проекта не существует.
    Если страницы лежат вне текущего каталога — от каталога страниц.
    """
    path = getattr(page, "path", "") or ""
    if not path:
        return path
    # Прямые слэши на любой системе: наряд читают и люди, и агенты, и путь в
    # нём должен совпадать с тем, что лежит в репозитории.
    for base in (os.getcwd(), root):
        if not base:
            continue
        try:
            # realpath с обеих сторон: на macOS /var — это /private/var.
            rel = os.path.relpath(os.path.realpath(path), os.path.realpath(base))
        except ValueError:                     # разные диски в Windows
            continue
        if not rel.startswith(".."):
            return rel.replace(os.sep, "/")
    return path.replace(os.sep, "/")


def _is_built(page) -> bool:
    """HTML — результат сборки; Markdown — исходник, его и правят."""
    return (getattr(page, "path", "") or "").lower().endswith((".html", ".htm"))


def _built_note() -> str:
    return tr("Это собранный файл: правка в нём пропадёт при следующей сборке. Чини "
              "источник — шаблон, строку данных или генератор — и пересобери. Путь "
              "показывает, какой шаблон и какая строка дали эту страницу.")


def _verify(verify: str, site: str) -> list:
    command = verify or f"indexgap check{' --site ' + site if site else ''}"
    return ["", tr("Проверить результат (после пересборки, если страницы собираются):"),
            "", "```bash", command, "```"]


def _requirements(cfg: dict, profile_title: str = "", has_rows: bool = True,
                  unmatched: bool = False) -> list:
    """Чему страница обязана удовлетворять после починки — из настроек проекта."""
    out = []
    if profile_title:
        out.append(tr("профиль: {a0}", a0=tr(profile_title)))
    out.append(tr("объём основного текста: не меньше {a0} слов", a0=cfg.get("thin_words", 250)))
    out.append(tr("title {a0}–{a1} знаков ширины, description {a2}–{a3}",
                  a0=cfg.get("title_min", 20), a1=cfg.get("title_max", 65),
                  a2=cfg.get("description_min", 70), a3=cfg.get("description_max", 165)))
    out.append(tr("похожесть с соседними страницами ниже {a0:.2f}",
                  a0=cfg.get("near_duplicate", 0.8)))
    # Требовать сверки чисел с датасетом там, где датасета нет, — значит
    # выдать заведомо непроверяемое требование.
    if has_rows and not unmatched:
        out.append(tr("ни одного числа, которого нет в строке датасета"))
    elif unmatched:
        out.append(tr("страница не сопоставлена со строкой датасета — её числа НЕ "
                      "проверялись. Если это страница строки, назови строку: `keyword:` "
                      "во фронтматтере или <meta name=\"keyword\"> в шаблоне"))
    return out


def build(pages: list, analysis: dict, cfg: dict = None,
          template_notes: list = None, rows_by_key: dict = None,
          profile_title: str = "", site: str = "", root: str = "",
          verify: str = "") -> list:
    """
    Собирает наряды. Возвращает список словарей: имя файла, заголовок, тело.

    Ничего не пишет на диск — это делает `write`.
    """
    from .checks import CONFIG as CHECK_DEFAULTS

    # Пороги в требованиях наряда должны быть теми же, по которым выписана
    # находка. Свои значения по умолчанию здесь означали бы «почини до 250
    # слов» там, где проверка требует 400.
    cfg = {**CHECK_DEFAULTS, **(cfg or {})}
    by_page = defaultdict(list)
    site_issues, grouped_issues = [], []
    # Код шаблона → адреса, которые забирает его наряд. Заметка без адресов
    # (простая строка) забирает код со всего сайта.
    template_codes = {}
    for note in template_notes or ():
        match = re.search(r"`([a-z\-]+)`", note)
        if match:
            scope = getattr(note, "urls", None) or None
            have = template_codes.get(match.group(1), set())
            template_codes[match.group(1)] = (None if scope is None or have is None
                                              else have | scope)

    for level, url, code, message in analysis.get("issues", ()):
        if code in SITE_LEVEL or not url or url == "robots.txt":
            site_issues.append((level, url, code, message))
        elif code in GROUPED:
            grouped_issues.append((level, url, code, message))
        elif code in template_codes and (template_codes[code] is None
                                         or url in template_codes[code]):
            continue                      # уйдёт в наряд на шаблон
        else:
            by_page[url].append((level, code, message))

    briefs = []
    known = {p.url: p for p in pages}
    requirements = _requirements(cfg, profile_title, bool(rows_by_key))

    # ── шаблон ────────────────────────────────────────────────────────────────
    if template_notes:
        body = [tr("Эти находки срабатывают почти на всех страницах. Это свойство "
                   "шаблона, а не список страниц: правится один раз в шаблоне "
                   "и исчезает везде."), ""]
        for note in template_notes:
            body.append(f"- {note}")
            match = re.search(r"`([a-z\-]+)`", note)
            fix = _fix(match.group(1)) if match else ""
            if fix:
                body.append(f"  {tr('Что делать:')} {fix}")
        body += _verify(verify, site)
        briefs.append({"name": "_template.md", "kind": "template",
                       "title": tr("Починка шаблона"), "body": "\n".join(body),
                       "count": len(template_notes)})

    # ── сайт целиком ──────────────────────────────────────────────────────────
    if site_issues:
        body = [tr("Свойства сайта, а не отдельных страниц: robots.txt, разметка, "
                   "связи языковых версий."), ""]
        for _level, _url, code, message in site_issues:
            body.append(f"- `{code}` — {message}")
            fix = _fix(code)
            if fix:
                body.append(f"  {tr('Что делать:')} {fix}")
        body += _verify(verify, site)
        briefs.append({"name": "_site.md", "kind": "site",
                       "title": tr("Починка на уровне сайта"),
                       "body": "\n".join(body), "count": len(site_issues)})

    # ── группы дублей ─────────────────────────────────────────────────────────
    from .checks import _clusters

    pairs = [(a.url, b.url, j) for a, b, j in analysis.get("duplicates", ())
             if j >= cfg.get("near_duplicate", 0.8)]
    edges = [(a, b) for a, b, _j in pairs]
    alike = defaultdict(float)
    for a, b, j in pairs:
        alike[a] = max(alike[a], j)
        alike[b] = max(alike[b], j)
    for number, group in enumerate(_clusters(edges), 1):
        if len(group) < 2:
            continue
        members = [known.get(url) for url in group]
        langs = {(p.lang or "").lower().split("-")[0] for p in members if p is not None}
        langs.discard("")
        rows = [(rows_by_key or {}).get(url) for url in group]
        distinct = {tuple(sorted((r or {}).items())) for r in rows if r}
        if len(langs) > 1:
            # Непереведённая версия: canonical на одну из них выбросит язык.
            advice = tr("Что делать: страницы на разных языках совпадают текстом — "
                        "перевод не сделан. Переведи каждую версию. Canonical на одну "
                        "из них выбросит языковую версию из поиска.")
        elif len(distinct) > 1:
            # Двадцать четыре города из разных строк — дублирует их шаблон.
            advice = tr("Что делать: страницы собраны из разных строк датасета — "
                        "дублирует их шаблон, а не интент. Чини шаблон: больше данных "
                        "своей строки, разделы, которые зависят от данных. Склеивать их "
                        "canonical'ом нельзя — пропадут настоящие страницы.")
        else:
            advice = tr("Что делать: выбери одну страницу как основную и разведи "
                        "остальные по разным интентам — у каждой должен быть свой "
                        "вопрос, на который она отвечает. Если развести нечем — это "
                        "один интент: убери лишнюю строку из датасета (её покажет "
                        "`indexgap plan`) или поставь с остальных страниц canonical на "
                        "основную.")
        # Код находки называется и здесь: по нему наряд сверяют с отчётом.
        body = ["`near-duplicate` — "
                + tr("{a0} страниц почти совпадают друг с другом. Поисковик "
                     "оставит в индексе одну.", a0=len(group)), "", advice,
                tr("Обычные ссылки на соседние страницы и хабы оставь: ссылка не "
                   "делает страницы разными, но и не вредит им."), "",
                tr("Страницы группы (наибольшее совпадение с другой страницей группы):")]
        for url in group:
            page = known.get(url)
            where = f" — `{_where(page, root)}`" if page is not None else ""
            body.append(f"- {url}{where} — {alike[url]:.0%}")
        body += _verify(verify, site)
        # Имя — от первого адреса группы, а не от её номера: одна новая пара
        # раньше перенумеровывала сотни файлов, и каждый коммит нарядов был
        # шумом во всю их ширину.
        briefs.append({"name": f"_duplicates/{_slug(sorted(group)[0]).replace('/', '--')}.md",
                       "kind": "group",
                       "title": tr("Группа почти-дублей №{a0}", a0=number),
                       "body": "\n".join(body), "count": len(group)})

    # ── постранично ───────────────────────────────────────────────────────────
    order = {"critical": 0, "warning": 1, "info": 2}
    for url in sorted(by_page, key=lambda u: (
            min(order.get(l, 3) for l, _c, _m in by_page[u]), -len(by_page[u]), u)):
        found = by_page[url]
        page = known.get(url)
        body = []
        if page is not None:
            body.append(tr("Файл: `{a0}`", a0=_where(page, root)))
            if _is_built(page):
                body.append(_built_note())
        body.append(tr("Адрес: {a0}", a0=url))
        body.append("")
        body.append(tr("Что не так:"))
        for level, code, message in sorted(found, key=lambda i: order.get(i[0], 3)):
            body.append(f"- **`{code}`** ({level}) — {message}")
            fix = _fix(code)
            if fix:
                body.append(f"  {tr('Что делать:')} {fix}")
        row = (rows_by_key or {}).get(url)
        if row:
            body += ["", tr("Данные строки датасета — единственный источник чисел "
                            "для этой страницы:")]
            for key, value in row.items():
                if (value or "").strip():
                    body.append(f"- {key}: {value}")
        body += ["", tr("Чему страница должна удовлетворять после починки:")]
        own = (_requirements(cfg, profile_title, True, unmatched=True)
               if rows_by_key and not row else requirements)
        for line in own:
            body.append(f"- {line}")
        body += ["", tr("Ничего не выдумывать. Если данных нет, раздел не пишем.")]
        body += _verify(verify, site)
        briefs.append({"name": _slug(url) + ".md", "kind": "page", "url": url,
                       "title": tr("Починка страницы"), "body": "\n".join(body),
                       "count": len(found),
                       "worst": min(order.get(l, 3) for l, _c, _m in found)})
    return briefs


def write(briefs: list, out_dir: str, limit: int = 0) -> dict:
    """
    Раскладывает наряды по файлам. Существующие наряды перезаписывает —
    это отчёт, а не исходник; пользовательских правок в нём быть не должно.
    """
    if not out_dir:
        raise SourceError(tr("не указан каталог для нарядов"))
    root = os.path.abspath(out_dir)
    shared = [b for b in briefs if b["kind"] != "page"]
    pages = [b for b in briefs if b["kind"] == "page"]
    pages.sort(key=lambda b: (b.get("worst", 3), -b["count"]))
    skipped = 0
    if limit and len(pages) > limit:
        skipped = len(pages) - limit
        pages = pages[:limit]

    # Наряды прошлого прогона, которых в этом нет, убираются: задание на
    # страницу, которую уже удалили или починили, — устаревшее задание.
    # Убирается только то, что несёт метку наряда; чужие файлы не трогаются.
    keep = {os.path.normpath(os.path.join(root, b["name"])) for b in shared + pages}
    for base, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.normpath(os.path.join(base, name))
            if path in keep or not name.endswith(".md"):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    mine = fh.read(len(HEADER) + 8).lstrip().startswith(HEADER)
                if mine:
                    os.remove(path)
            except OSError:
                pass

    written = []
    for brief in shared + pages:
        path = os.path.join(root, brief["name"])
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        text = (f"{HEADER}\n---\nkind: {brief['kind']}\n"
                + (f"url: {brief['url']}\n" if brief.get("url") else "")
                + f"findings: {brief['count']}\n---\n\n"
                + f"# {brief['title']}\n\n{brief['body']}\n")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        written.append(os.path.relpath(path, root))
    return {"written": written, "skipped": skipped, "dir": root}
