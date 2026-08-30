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
    "orphan": N_("Поставь ссылки на эту страницу с хабовых страниц раздела. "
                 "Анкор — описательный, не «подробнее»."),
    "unreachable": N_("Добавь путь от главной: страница есть в sitemap, но "
                      "краулер до неё не доходит."),
    "deep": N_("Подними страницу выше в структуре или дай на неё ссылку "
               "с более близкой к главной."),
    "low-uniqueness": N_("Добавь то, что отличает эту страницу от соседних: "
                         "конкретику из её строки данных. Шаблонного текста "
                         "должно стать меньше, чем своего."),
    "thin": N_("Наполни страницу или убери из индекса. Если порог не подходит "
               "этому типу контента — поправь его в indexgap.json, а не "
               "дописывай воду."),
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
    "hreflang-static-cluster": N_("Шаблон печатает кластер главной на каждой "
                                  "странице. Кластер должен собираться "
                                  "из переводов ЭТОЙ страницы."),
    "hreflang-canonical-conflict": N_("Верни canonical на саму страницу: сейчас "
                                      "он уводит на другой язык и отменяет "
                                      "hreflang."),
    "hreflang-missing": N_("Добавь альтернативы для языковых версий этой страницы."),
    "hreflang-bad-code": N_("Поправь код языка: чаще всего вместо языка написана "
                            "страна."),
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
    "near-duplicate": N_("Реши, что делать с группой целиком: оставить одну страницу и "
                         "увести остальные canonical'ом на неё — или развести их по разным "
                         "интентам. Одну страницу из группы починить нельзя."),
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
              "robots-unreadable", "no-robots", "hreflang-static-cluster"}

HEADER = "<!-- indexgap-brief -->"


def _slug(url: str) -> str:
    path = re.sub(r"^https?://[^/]+", "", url or "").strip("/")
    path = re.sub(r"[^\w\-/]+", "-", path, flags=re.UNICODE).strip("-/")
    return path or "index"


def _fix(code: str) -> str:
    found = FIX.get(code)
    return tr(found) if found else ""


def _where(page, root: str) -> str:
    """Путь к файлу — от корня проекта: абсолютный не помещается в строку."""
    path = getattr(page, "path", "") or ""
    if root and path:
        try:
            return os.path.relpath(path, root)
        except ValueError:                     # разные диски в Windows
            return path
    return path


def _requirements(cfg: dict, profile_title: str = "", has_rows: bool = True) -> list:
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
    if has_rows:
        out.append(tr("ни одного числа, которого нет в строке датасета"))
    return out


def build(pages: list, analysis: dict, cfg: dict = None,
          template_notes: list = None, rows_by_key: dict = None,
          profile_title: str = "", site: str = "", root: str = "") -> list:
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
    template_codes = set()
    for note in template_notes or ():
        match = re.search(r"`([a-z\-]+)`", note)
        if match:
            template_codes.add(match.group(1))

    for level, url, code, message in analysis.get("issues", ()):
        if code in SITE_LEVEL or not url or url == "robots.txt":
            site_issues.append((level, url, code, message))
        elif code in GROUPED:
            grouped_issues.append((level, url, code, message))
        elif code in template_codes:
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
        briefs.append({"name": "_site.md", "kind": "site",
                       "title": tr("Починка на уровне сайта"),
                       "body": "\n".join(body), "count": len(site_issues)})

    # ── группы дублей ─────────────────────────────────────────────────────────
    from .checks import _clusters

    edges = [(a.url, b.url) for a, b, j in analysis.get("duplicates", ())
             if j >= cfg.get("near_duplicate", 0.8)]
    for number, group in enumerate(_clusters(edges), 1):
        if len(group) < 2:
            continue
        body = [tr("{a0} страниц почти совпадают друг с другом. Поисковик "
                   "оставит в индексе одну.", a0=len(group)), "",
                tr("Что делать: выбери одну страницу как основную и разведи "
                   "остальные по разным интентам — у каждой должен быть свой "
                   "вопрос, на который она отвечает. Если развести нечем, "
                   "оставь одну, а с остальных поставь canonical на неё. "
                   "Связывать их ссылками между собой нельзя."), "",
                tr("Страницы группы:")]
        for url in group:
            page = known.get(url)
            where = f" — `{_where(page, root)}`" if page is not None else ""
            body.append(f"- {url}{where}")
        briefs.append({"name": f"_duplicates/group-{number:03d}.md",
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
        for line in requirements:
            body.append(f"- {line}")
        body += ["", tr("Ничего не выдумывать. Если данных нет, раздел не пишем."),
                 "", tr("Проверить результат:"),
                 "", "```bash", f"indexgap check{' --site ' + site if site else ''}",
                 "```"]
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
