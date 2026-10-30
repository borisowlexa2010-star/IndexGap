# -*- coding: utf-8 -*-
"""
HTML-отчёт: одна страница, которую открываешь двойным кликом.

Отчёт отвечает на один вопрос — **что чинить первым**. Поэтому находки
сгруппированы по причине и отсортированы по важности, а не по алфавиту кода.
Раньше сортировка шла по коду, сверху оказывались двенадцать однотипных
предупреждений, главная находка пакета уезжала вниз, а при трёхстах находках
целые классы проблем не попадали в отчёт вовсе: срез в 120 строк отрезал всё,
что алфавитно ниже. Теперь усечение происходит внутри группы, и ни одна
причина не исчезает.
"""

from __future__ import annotations

import html
import os
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime

from .checks import CODE_WEIGHT, LEVEL_ORDER
from .i18n import N_, tr

CSS = """
:root{--bg:#F6F8F7;--card:#fff;--fg:#141D1C;--fg2:#55635F;--fg3:#7D8B87;
--line:#DDE5E2;--line2:#C3CFCB;--ok:#008C82;--warn:#8A6A15;--bad:#A6342A;}
@media(prefers-color-scheme:dark){:root{--bg:#131817;--card:#1A2120;--fg:#E9EEEC;
--fg2:#9AA7A3;--fg3:#78847F;--line:#2B3432;--line2:#3A4543;--ok:#1AA294;
--warn:#C6A24A;--bad:#D4685C;}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:44px 24px 90px}
h1{font-size:27px;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:19px;margin:44px 0 14px;letter-spacing:-.01em}
.sub{color:var(--fg2);margin:0 0 30px;font-size:14px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:4px;padding:14px 16px}
.card .n{font-size:26px;font-weight:600;letter-spacing:-.02em;
font-variant-numeric:tabular-nums;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.card .l{color:var(--fg2);font-size:12px;margin-top:3px;line-height:1.35}
.bad{color:var(--bad)}.warn{color:var(--warn)}.ok{color:var(--ok)}
.first{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--bad);
border-radius:4px;padding:16px 20px;margin:14px 0 0}
.first ol{margin:8px 0 0;padding-left:20px}
.first li{margin:4px 0}
.funnel{display:flex;flex-direction:column;gap:8px}
.step{background:var(--card);border:1px solid var(--line);border-radius:4px;
padding:12px 16px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.step .bar{height:8px;border-radius:2px;background:var(--ok);flex:none}
.step .nm{min-width:190px;font-size:14px}
.step .ct{font-family:ui-monospace,monospace;font-variant-numeric:tabular-nums;
margin-left:auto;font-size:14px}
.step .ls{color:var(--bad);font-size:12.5px;font-family:ui-monospace,monospace}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:4px;background:var(--card)}
table{width:100%;border-collapse:collapse;font-size:13.5px;min-width:520px}
th,td{text-align:left;padding:8px 13px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:last-child td{border-bottom:none}
th{font-size:10.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--fg3);
font-weight:500;background:var(--bg);border-bottom:1px solid var(--line2)}
td.n{text-align:right;font-family:ui-monospace,monospace;font-variant-numeric:tabular-nums;
white-space:nowrap}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;
word-break:break-all}
.note{font-size:13px;color:var(--fg2);margin-top:10px;max-width:66ch}
.pill{display:inline-block;padding:1px 7px;border-radius:3px;font-size:11px;
font-family:ui-monospace,monospace;border:1px solid currentColor;white-space:nowrap}
.empty{color:var(--fg3);padding:14px 16px;background:var(--card);
border:1px solid var(--line);border-radius:4px;font-size:14px}
details.grp{background:var(--card);border:1px solid var(--line);border-radius:4px;
margin-bottom:8px}
details.grp>summary{padding:12px 16px;cursor:pointer;display:flex;gap:12px;
align-items:baseline;flex-wrap:wrap;list-style:none}
details.grp>summary::-webkit-details-marker{display:none}
details.grp>summary:focus-visible{outline:2px solid var(--ok);outline-offset:-2px}
summary .cnt{font-family:ui-monospace,monospace;font-variant-numeric:tabular-nums;
margin-left:auto;color:var(--fg2);font-size:13px}
summary .what{flex:1 1 260px;min-width:0}
.grp-body{padding:0 16px 14px;font-size:13.5px;color:var(--fg2)}
.grp-body ul{margin:6px 0 0;padding-left:18px}
.grp-body li{margin:3px 0}
.warnbox{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--warn);
border-radius:4px;padding:12px 16px;margin-bottom:10px;font-size:14px}
"""

LEVEL_LABEL = {"critical": ("bad", N_("критично")), "warning": ("warn", N_("внимание")),
               "info": ("ok", N_("мелочь"))}

# Что означает код и что с ним делать. Раньше половина кодов, которые выдаёт
# пакет, не была описана нигде — человек видел находку без инструкции.
def _help(code, default=""):
    """
    Описание кода — переводится в момент отрисовки, а не при импорте.

    Раньше словарь строился с `tr()` на уровне модуля, то есть до того, как
    разобран `--lang`. `indexgap profiles --lang ru` печатал русский заголовок
    и английские названия профилей: наполовину переведённый отчёт выглядит
    сломанным, и это хуже, чем честно один язык.
    """
    found = CODE_HELP.get(code)
    return tr(found) if found else default


CODE_HELP = {
    "unsupported-number": N_("Число в тексте, которого нет в данных. Проверь по строке датасета и либо исправь, либо убери утверждение."),
    "check-by-eye": N_("Числа со словами, которых нет в данных. Часть таких — обычная речь («3 шага», «5 звёзд»), часть — выдумка агента. Список для просмотра глазами, а не приговор."),
    "robots-unreadable": N_("robots.txt не прочитался — проверь путь в --robots."),
    "stale-event": N_("Дата на странице прошла, а страница открыта для индексации. Поисковик показывает людям то, чего уже нет: закрой noindex, поставь редирект на актуальное или перепиши в отчёт о прошедшем."),
    "stale-closed": N_("Дата прошла, и страница уже закрыта от индексации — так и надо. Строка справочная."),
    "still-draft": N_("В фронтматтере `status: draft`. Страница попадёт в сборку недописанной — допиши или исключи из публикации."),
    "unfilled-slot": N_("На странице осталось незаполненное место шаблона — `{{city}}`, `%CITY%`, `undefined`, `NaN`, пустое место в заголовке или lorem ipsum. Читатель и поисковик видят шов генератора. Чинится в данных или в шаблоне, а не на странице."),
    "llm-leftover": N_("В тексте остался ответ модели вместо текста страницы: «As an AI language model…», «Certainly! Here is…». Такую страницу видно сразу, и её нельзя публиковать."),
    "mojibake": N_("Часть текста прочитана не в той кодировке: «CafÃ©», «â€™». Обычно это данные, сохранённые в UTF-8 и прочитанные как Latin-1 где-то в конвейере."),
    "brief-left": N_("В файле остался блок брифа или TODO — он уедет в текст страницы."),
    "noindex": N_("Страница закрыта от индексации. Если это ошибка шаблона — убери мета-тег robots."),
    "nosnippet": N_("Запрещён сниппет. Страница может быть в индексе, но не появится ни в расширенной выдаче, ни в ответах ИИ-поиска."),
    "canonical-elsewhere": N_("Canonical ведёт на другую страницу — эта отдаёт ей вес и сама из индекса выпадает."),
    "jsonld-mismatch": N_("Разметка называет цену, рейтинг или число отзывов, которых нет в видимом тексте. Google требует, чтобы структурированные данные повторяли страницу."),
    "hub-missing-links": N_("Страница раздела не ссылается на часть своих страниц: до них доходят только через sitemap, и вес раздела до них не доходит."),
    "stale-year": N_("В заголовке прошлый год: страница обещает свежесть, а выглядит заброшенной."),
    "title-h1-mismatch": N_("title и H1 говорят о разном — поисковик может переписать заголовок в выдаче."),
    "no-og": N_("Нет og:title или og:image — ссылка на страницу в соцсетях и мессенджерах выходит без превью."),
    "no-viewport": N_("Нет meta viewport — на телефоне страница не адаптирована, а Google индексирует мобильную версию."),
    "heavy-html": N_("HTML тяжелее 2 МБ: Googlebot читает первые 2 МБ, хвост страницы в индекс не попадает."),
    "heavy-images": N_("Картинки тяжелее 1 МБ замедляют загрузку на телефоне."),
    "dataset-unbound": N_("Сверка с датасетом покрыла меньше половины страниц: числа остальных не проверены, и «критичных 0» ничего о них не говорит."),
    "broken-link": N_("Ссылка ведёт на страницу, которой в сборке нет: на живом сайте это 404. Чаще всего шаблон ссылается на строку данных, которую фильтр не пропустил в генерацию. Убери ссылку из шаблона или верни страницу."),
    "wrong-link-form": N_("Ссылка ведёт на страницу сборки, но в форме, которую хостинг не отдаёт: другой регистр букв, /about.html при about/index.html, /faq/ при faq.html. url_key сводит формы в одну страницу, живой сервер — нет, и отвечает 404."),
    "orphan": N_("На страницу не ведёт ни одна внутренняя ссылка. В sitemap она есть, но краулер до неё не дойдёт. Поставь ссылки с хабовых страниц раздела."),
    "unreachable": N_("От главной до страницы нельзя дойти по ссылкам."),
    "near-duplicate": N_("Почти совпадает с другой страницей. Поисковик оставит одну. Если у страниц разные запросы (город, модель, услуга), дай каждой свои данные — canonical здесь спрячет страницы, ради которых их делали. Если запрос один — оставь одну страницу и уведи остальные на неё."),
    "similar": N_("Похожа на другую страницу, но ниже порога дубля. Повод посмотреть."),
    "low-uniqueness": N_("Шаблон вытеснил содержание: уникального текста меньше четверти."),
    "template-skeleton": N_("Одинаковый скелет заголовков на многих страницах — для поисковика это признак штамповки."),
    "same-opening": N_("Одинаковое начало текста на многих страницах."),
    "thin": N_("Текста меньше порога. Порог правится в indexgap.json — для карточки товара 250 слов абсурдны, для гайда нормальны."),
    "no-title": N_("Нет title."),
    "title-short": N_("Title короче рекомендованного."),
    "title-long": N_("Title обрежется в выдаче."),
    "no-description": N_("Нет meta description — поисковик соберёт сниппет сам."),
    "description-length": N_("Длина description вне рекомендованного диапазона."),
    "no-h1": N_("Нет H1 — поисковику нечем определить тему страницы."),
    "many-h1": N_("H1 больше одного."),
    "no-headings": N_("На странице нет заголовков — структуры нет."),
    "duplicate-title": N_("Одинаковый title у нескольких страниц — склейка в выдаче."),
    "duplicate-description": N_("Одинаковый description у нескольких страниц."),
    "deep": N_("Слишком много кликов от главной."),
    "vague-anchor": N_("Анкоры вида «здесь» и «подробнее» не передают смысл."),
    "hreflang-no-self": N_("В кластере hreflang нет ссылки на саму страницу. "
                           "Без self-ссылки кластер невалиден целиком."),
    "hreflang-no-return": N_("Односторонняя связь hreflang: обратной ссылки нет. "
                             "Google отбрасывает такую связь, а не учитывает частично."),
    "hreflang-unknown-target": N_("Альтернатива указывает на страницу, которой нет "
                                  "среди разобранных — взаимность не проверить."),
    "hreflang-target-blocked": N_("Альтернатива закрыта от индексации или отдаёт "
                                  "canonical другой странице."),
    "hreflang-canonical-conflict": N_("Canonical ведёт на другую языковую версию — "
                                      "это отменяет hreflang."),
    "hreflang-bad-code": N_("Код языка в hreflang неверен — частая подмена языка страной."),
    "hreflang-lang-mismatch": N_("Код в self-ссылке не совпадает с lang страницы."),
    "lang-script-mismatch": N_("lang страницы говорит одно, а текст написан другим письмом: "
                               "поисковик и экранный диктор поймут язык неверно."),
    "hreflang-missing": N_("Сайт мультиязычный, а у страницы нет ни одной альтернативы."),
    "hreflang-static-cluster": N_("Шаблон печатает один и тот же кластер hreflang "
                                  "на всех страницах — связей между версиями нет."),
    "translations-parked": N_("Переводы закрыты от индекса и отдают canonical "
                              "оригиналу — правилом шаблона, а не постранично."),
    "source-note": N_("Замечание к самому файлу: кодировка, фронтматтер, разметка."),
    "js-shell": N_("В исходном HTML почти нет текста. Краулеры ИИ-поиска не исполняют JavaScript и увидят пустую страницу."),
    "answer-preamble": N_("Первый абзац — разгон, а не ответ. Именно первый абзац цитируют ИИ-поиск и блок быстрых ответов."),
    "answer-short": N_("Первый абзац слишком короткий для самостоятельного ответа."),
    "answer-long": N_("Первый абзац длинноват для цитирования. Это эвристика, а не правило поисковика: ИИ-ответы чаще берут короткий самостоятельный ответ, но длинный абзац их не запрещает."),
    "no-answer": N_("Не нашлось ни одного абзаца."),
    "no-question-headings": N_("Ни один подзаголовок не сформулирован как вопрос. Это эвристика из корреляционных исследований, а не требование поисковика: вопросы в подзаголовках упрощают цитирование, но переписывать под них живой текст не обязательно."),
    "long-paragraph": N_("Очень длинные абзацы плохо извлекаются."),
    "no-structure": N_("Нет ни списков, ни таблиц."),
    "img-no-alt": N_("Изображения без alt."),
    "jsonld-broken": N_("Блок JSON-LD не парсится — для поисковика его нет."),
    "jsonld-faq-invisible": N_("В разметке FAQ есть вопросы, которых нет на странице. Это риск ручных санкций."),
    "jsonld-no-type": N_("В блоке JSON-LD нет @type."),
    "no-date": N_("Нет машиночитаемой даты."),
    "no-author": N_("Не указан автор или организация."),
    "robots-blocks-page": N_("robots.txt не пускает поисковик на эту страницу: она есть в сборке и, скорее всего, в sitemap, но текст её прочитан не будет."),
    "robots-blocks-all": N_("robots.txt закрывает сайт целиком."),
    "ai-crawler-blocked": N_("В robots.txt закрыт краулер ИИ-поисковика."),
    "robots-no-sitemap": N_("В robots.txt нет строки Sitemap."),
    "no-robots": N_("robots.txt не проверялся."),
}


def _esc(s) -> str:
    return html.escape(str(s))


def _funnel_html(f: dict) -> str:
    steps = [s for s in (f.get("steps") or []) if isinstance(s, dict)]
    if not steps:
        return ""
    top = max((s.get("count") or 0) for s in steps) or 1
    rows = []
    for s in steps:
        count = s.get("count") or 0
        width = max(3, round(360 * count / top))
        lost = s.get("lost")
        lost_html = f'<span class="ls">−{lost}</span>' if lost else ""
        why = (f'<div class="note" style="margin:2px 0 0">{_esc(s.get("why", ""))}</div>'
               if lost and s.get("why") else "")
        rows.append(
            f'<div class="step"><span class="nm">{_esc(s.get("name", ""))}{why}</span>'
            f'<span class="bar" style="width:{width}px"></span>'
            f'{lost_html}<span class="ct">{count}</span></div>')
    return '<div class="funnel">' + "".join(rows) + "</div>"


def _first_things(issues: list, graph: dict, dupes: list) -> str:
    """Три числа и порядок действий — то, с чего начинают."""
    counts = Counter(item[2] for item in issues
                     if len(item) >= 3 and item[0] == "critical")
    lines = []
    for code, count in counts.most_common(3):
        lines.append(tr("<li><strong>{a0}</strong> — {a1} стр.: {a2}</li>", a0=_esc(code), a1=count, a2=_esc(_help(code, ''))))
    if not lines:
        return (tr("<div class=\"first\"><strong>Критичных находок нет.</strong> Дальше смотри в Search Console и Вебмастере: локальные проверки своё сказали.</div>"))
    return (tr("<div class=\"first\"><strong>Начни с этого</strong><ol>") + "".join(lines) + '</ol></div>')


def _groups_html(issues: list, per_group: int = 25, helper=None) -> str:
    helper = helper or _help
    if not issues:
        return tr("<div class=\"empty\">Ничего не найдено.</div>")
    grouped = defaultdict(list)
    for item in issues:
        level, url, code, message = (list(item) + ["", "", "", ""])[:4]
        grouped[(level, code)].append((url or "", message or ""))

    order = sorted(grouped,
                   key=lambda k: (LEVEL_ORDER.get(k[0], 3),
                                  CODE_WEIGHT.get(k[1], 50), k[1]))
    blocks = []
    for level, code in order:
        rows = sorted(grouped[(level, code)])
        cls, label = LEVEL_LABEL.get(level, ("", level))
        label = tr(label)
        shown = rows[:per_group]
        more = (tr("<p class=\"note\">Показано {a0} из {a1}. Полный список — в JSON рядом с отчётом.</p>", a0=len(shown), a1=len(rows))
                if len(rows) > per_group else "")
        items = "".join(
            f'<li><span class="mono">{_esc(url)}</span> — {_esc(msg)}</li>'
            for url, msg in shown)
        help_text = helper(code, "")
        blocks.append(
            f'<details class="grp"{" open" if level == "critical" else ""}>'
            f'<summary><span class="pill {cls}">{_esc(label)}</span>'
            f'<span class="what"><span class="mono">{_esc(code)}</span> — '
            f'{_esc(help_text)}</span>'
            f'<span class="cnt">{len(rows)}</span></summary>'
            f'<div class="grp-body"><ul>{items}</ul>{more}</div></details>')
    return "".join(blocks)


def _templates_html(templates: list) -> str:
    """Таблица риска по шаблонам. Шаблонов нет — нет и раздела."""
    if not templates:
        return ""
    rows = []
    for t in templates:
        cls = " bad" if t["risk"] >= 50 else " warn" if t["risk"] >= 20 else ""
        codes = ", ".join(c["code"] for c in t["top_codes"])
        rows.append(
            f'<tr><td class="mono">{_esc(t["pattern"])}</td><td class="n">{t["pages"]}</td>'
            f'<td class="n">{t["critical_share"]:.0%}</td>'
            f'<td class="n">{t["warning_share"]:.0%}</td>'
            f'<td class="mono">{_esc(codes)}</td><td class="n{cls}">{t["risk"]}</td></tr>')
    return (tr("<h2>Риск по шаблонам</h2><div class=\"scroll\"><table><thead><tr>"
               "<th>шаблон</th><th class=\"n\">страниц</th><th class=\"n\">критично</th>"
               "<th class=\"n\">внимание</th><th>частые коды</th><th class=\"n\">риск</th>"
               "</tr></thead><tbody>")
            + "".join(rows)
            + tr("</tbody></table></div><p class=\"note\">Риск 0–100 — средняя по страницам "
                 "шаблона тяжесть самой тяжёлой находки: критичная весит от 0,5 до 1 "
                 "в зависимости от кода, внимание — от 0,15 до 0,3. В «other» сложены "
                 "шаблоны меньше десяти страниц.</p>"))


def build(analysis: dict, funnel_result: dict = None, causes: list = None,
          out_path: str = "indexgap-report.html", site: str = "",
          cross: list = None, notes: list = None, title: str = tr("Отчёт конвейера"),
          templates: list = None) -> str:
    pages = analysis.get("pages") or []
    issues = analysis.get("issues") or []
    graph = analysis.get("graph") or {}
    dupes = analysis.get("duplicates") or []
    counts = Counter(i[0] for i in issues if i)

    warn_html = "".join(
        f'<div class="warnbox">{_esc(n)}</div>' for n in (notes or []))

    dupe_rows = "".join(
        f'<tr><td class="mono">{_esc(a.url)}</td><td class="mono">{_esc(b.url)}</td>'
        f'<td class="n">{j:.0%}</td></tr>'
        for a, b, j in dupes[:60]
    ) or tr("<tr><td colspan=\"3\" style=\"color:var(--fg3)\">Похожих страниц не найдено.</td></tr>")
    dupe_more = (tr("<p class=\"note\">Показано 60 пар из {a0}. Остальные — в JSON.</p>", a0=len(dupes)) if len(dupes) > 60 else "")

    cause_rows = "".join(
        f'<tr><td>{_esc(c.get("cause", ""))}</td><td class="n">{c.get("count", 0)}</td>'
        f'<td>{_esc(c.get("fix", ""))}</td></tr>'
        for c in (causes or []) if isinstance(c, dict))

    cross_block = ""
    if cross:
        rows = "".join(
            f'<tr><td>{_esc(c.get("kind", ""))}</td><td class="n">{c.get("count", 0)}</td>'
            f'<td>{_esc(c.get("note", ""))}</td></tr>'
            for c in cross if isinstance(c, dict) and c.get("count"))
        if rows:
            cross_block = (
                tr("<h2>Сравнение поисковиков</h2><div class=\"scroll\"><table><thead><tr><th>где страница</th><th class=\"n\">страниц</th><th>что это значит</th></tr></thead><tbody>") + rows + tr("</tbody></table></div><p class=\"note\">Страница, которой нет нигде, — почти всегда техническая проблема. Страница, которая есть в одном индексе и нет в другом, — уже вопрос оценки качества или скорости конкретного поисковика, и техническими правками обычно не лечится.</p>"))

    causes_block = (
        (tr("<h2>Почему у страниц нет показов</h2>")
         if (funnel_result or {}).get("impressions_only")
         else tr("<h2>Почему страницы не в индексе</h2>"))
        + tr("<div class=\"scroll\"><table><thead><tr><th>причина</th><th class=\"n\">страниц</th><th>что делать</th></tr></thead><tbody>") + cause_rows + tr("</tbody></table></div><p class=\"note\">Разбор адресный: конкретные URL по каждой причине лежат в JSON. Страница может попасть сразу в несколько причин — так и бывает.</p>")
    ) if cause_rows else ""

    funnel_block = ""
    if funnel_result and funnel_result.get("steps"):
        funnel_block = (tr("<h2>Воронка конвейера</h2>") + _funnel_html(funnel_result) +
                        tr("<p class=\"note\">Каждый переход теряет страницы. Потери на разных переходах лечатся по-разному, поэтому важно видеть, где именно они происходят. Учти: экспорт «Страницы» из Search Console — это отчёт о показах, и страница в индексе без показов в него не попадает.</p>"))

    doc = tr("<!doctype html><!-- indexgap-report --><html lang=\"ru\"><head><meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n<title>{a0}{a1}</title>\n<style>{a2}</style></head><body><div class=\"wrap\">\n<h1>{a3}</h1>\n<p class=\"sub\">{a4} · {a5} страниц · {a6}</p>\n\n{a7}\n\n<div class=\"cards\">\n  <div class=\"card\"><div class=\"n\">{a8}</div><div class=\"l\">страниц разобрано</div></div>\n  <div class=\"card\"><div class=\"n bad\">{a9}</div><div class=\"l\">критично</div></div>\n  <div class=\"card\"><div class=\"n warn\">{a10}</div><div class=\"l\">внимание</div></div>\n  <div class=\"card\"><div class=\"n bad\">{a11}</div><div class=\"l\">сирот без входящих ссылок</div></div>\n  <div class=\"card\"><div class=\"n bad\">{a12}</div><div class=\"l\">пар похожих страниц</div></div>\n</div>\n\n{a13}\n\n{a14}\n{a15}\n{a16}\n\n<h2>Все находки по причинам</h2>\n{a17}\n\n<h2>Похожие страницы</h2>\n<div class=\"scroll\"><table><thead><tr><th>страница</th><th>похожа на</th>\n<th class=\"n\">совпадение</th></tr></thead><tbody>{a18}</tbody></table></div>\n{a19}\n<p class=\"note\">Совпадение выше порога означает, что поисковик, скорее всего, оставит\nв индексе одну страницу из пары. На конвейере это происходит, когда шаблон\nдаёт больше текста, чем подставляемые данные.</p>\n</div></body></html>", a0=_esc(title), a1=' — ' + _esc(site) if site else '', a2=CSS, a3=_esc(title), a4=_esc(site), a5=len(pages), a6=datetime.now().strftime('%d.%m.%Y %H:%M'), a7=warn_html, a8=len(pages), a9=counts.get('critical', 0), a10=counts.get('warning', 0), a11=len(graph.get('orphans') or []), a12=len(dupes), a13=_first_things(issues, graph, dupes) + _templates_html(templates), a14=funnel_block, a15=cross_block, a16=causes_block, a17=_groups_html(issues), a18=dupe_rows, a19=dupe_more)

    directory = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(directory, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return out_path


# ── сводный отчёт по портфелю ─────────────────────────────────────────────────

PORTFOLIO_CSS = """
.pgrid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));
margin-bottom:8px}
.pcard{background:var(--card);border:1px solid var(--line);border-radius:4px;
padding:14px 16px;display:flex;flex-direction:column;gap:6px}
.pcard .nm{font-size:15px;font-weight:600}
.pcard .pr{font-size:11.5px;color:var(--fg3);font-family:ui-monospace,monospace;
text-transform:uppercase;letter-spacing:.08em}
.pcard .row{display:flex;justify-content:space-between;font-size:13px;color:var(--fg2)}
.pcard .row b{font-family:ui-monospace,monospace;font-variant-numeric:tabular-nums;
font-weight:500;color:var(--fg)}
.pcard.err{border-left:3px solid var(--bad)}
.bars{display:flex;gap:3px;align-items:flex-end;height:26px;margin-top:2px}
.bars i{flex:1;background:var(--line2);border-radius:1px;min-height:2px;display:block}
.bars i.on{background:var(--bad)}
.share{font-family:ui-monospace,monospace;font-variant-numeric:tabular-nums}
"""


def _portfolio_cards(results: list) -> str:
    cards = []
    for r in results:
        if r.get("error"):
            cards.append(
                tr("<div class=\"pcard err\"><div class=\"nm\">{a0}</div><div class=\"pr\">не проверен</div><div class=\"row\" style=\"display:block\">{a1}</div></div>", a0=_esc(r['name']), a1=_esc(r['error'])))
            continue
        counts = r.get("counts") or {}
        rows = [
            (tr("страниц"), r.get("pages", 0)),
            (tr("критично"), counts.get("critical", 0)),
            (tr("внимание"), counts.get("warning", 0)),
            (tr("сирот"), r.get("orphans", 0)),
            (tr("похожих пар"), r.get("duplicates", 0)),
        ]
        body = "".join(f'<div class="row"><span>{k}</span><b>{v}</b></div>'
                       for k, v in rows)
        cards.append(
            f'<div class="pcard"><div class="nm">{_esc(r["name"])}</div>'
            f'<div class="pr">{_esc(tr(r.get("profile_title") or "") or r.get("profile", ""))}</div>'
            f'{body}</div>')
    return '<div class="pgrid">' + "".join(cards) + "</div>"


def _pattern_rows(patterns: list, results: list, scope: str = "page") -> str:
    names = [r["name"] for r in results if not r.get("error")]
    rows = []
    for p in patterns:
        if p.get("scope", "page") != scope:
            continue
        cls, label = LEVEL_LABEL.get(p["level"], ("", p["level"]))
        label = tr(label)
        cells = []
        for name in names:
            detail = p["detail"].get(name)
            if not detail:
                cells.append('<td class="n" style="color:var(--fg3)">—</td>')
            elif scope == "site":
                cells.append(tr("<td class=\"n share\">есть</td>"))
            else:
                cells.append(f'<td class="n share">{detail["share"]:.0%}</td>')
        hint = (tr("<br><span style=\"color:var(--warn)\">Срабатывает почти на всех страницах всех проектов — это вопрос к порогу, а не к страницам.</span>")
                if p.get("threshold_suspect") else "")
        rows.append(
            f'<tr><td><span class="pill {cls}">{_esc(label)}</span></td>'
            f'<td class="mono">{_esc(p["code"])}</td>'
            f'<td>{_esc(_help(p["code"]))}{hint}</td>'
            + "".join(cells) + "</tr>")
    head = "".join(f'<th class="n">{_esc(n)}</th>' for n in names)
    return (tr("<div class=\"scroll\"><table><thead><tr><th></th><th>код</th><th>что это</th>") + head + '</tr></thead><tbody>'
            + "".join(rows) + '</tbody></table></div>')


def build_portfolio(results: list, patterns: list, uniques: list = None,
                    out_path: str = "indexgap-portfolio.html") -> str:
    """
    Сводный отчёт: не «что не так у сайта», а «что ломается одинаково везде».

    Доля страниц важнее абсолютного числа: сто находок на трёх тысячах страниц
    и десять на двадцати — одна болезнь разной громкости, и в таблице они
    стоят рядом именно в процентах.
    """
    ok = [r for r in results if not r.get("error")]
    failed = [r for r in results if r.get("error")]
    total_pages = sum(r.get("pages", 0) for r in ok)
    total_critical = sum((r.get("counts") or {}).get("critical", 0) for r in ok)

    notes_block = ""
    note_items = []
    for r in ok:
        for note in (r.get("notes") or [])[:4]:
            note_items.append(f'<li><b>{_esc(r["name"])}</b> — {_esc(note)}</li>')
    if note_items:
        notes_block = (tr("<h2>Что пакет сказал о самих проектах</h2><div class=\"grp-body\"><ul>") + "".join(note_items) + '</ul></div>')

    unique_block = ""
    if uniques:
        items = "".join(
            f'<li><b>{_esc(u["name"])}</b>: '
            + ", ".join(f'<span class="mono">{_esc(c)}</span>' for c in u["codes"][:12])
            + "</li>" for u in uniques)
        unique_block = (tr("<h2>Личное у каждого</h2><p class=\"note\">Эти находки встретились ровно в одном проекте. Их чинят по месту, в отличие от общих граблей выше.</p><div class=\"grp-body\"><ul>") + items + '</ul></div>')

    profiles_block = ""
    seen_profiles = {}
    for r in ok:
        if r.get("profile") and r["profile"] not in seen_profiles:
            seen_profiles[r["profile"]] = (tr(r.get("profile_title", "")),
                                           [tr(n) for n in (r.get("profile_notes") or [])])
    if seen_profiles:
        rows = "".join(
            f'<tr><td class="mono">{_esc(key)}</td><td>{_esc(title)}</td>'
            f'<td>{_esc(" ".join(notes))}</td></tr>'
            for key, (title, notes) in sorted(seen_profiles.items()))
        profiles_block = (tr("<h2>Профили, по которым считали</h2><div class=\"scroll\"><table><thead><tr><th>профиль</th><th>тип контента</th><th>что важно помнить</th></tr></thead><tbody>") + rows + tr("</tbody></table></div><p class=\"note\">Пороги у профилей разные намеренно: 250 слов — норма для гайда и приговор для карточки события, а сверка фактов бессмысленна там, где датасета нет.</p>"))

    failed_block = ""
    if failed:
        items = "".join(f'<li><b>{_esc(r["name"])}</b> — {_esc(r["error"])}</li>'
                        for r in failed)
        failed_block = (tr("<h2>Не проверены</h2><div class=\"grp-body\"><ul>")
                        + items + '</ul></div>')

    page_patterns = [p for p in patterns if p.get("scope", "page") == "page"]
    site_patterns = [p for p in patterns if p.get("scope") == "site"]
    patterns_block = (tr("<h2>Общие грабли на страницах</h2><p class=\"note\">Находки, встретившиеся минимум в двух проектах. В ячейках — доля затронутых страниц проекта: сто находок на трёх тысячах страниц и десять на двадцати — одна болезнь разной громкости. Это уже не баг конкретного сайта, а свойство того, как эти сайты собираются: чинить надо привычку.</p>")
                      + _pattern_rows(patterns, results, "page")) if page_patterns else (
        tr("<h2>Общие грабли на страницах</h2><div class=\"empty\">Ни одна страничная находка не повторилась в двух проектах — либо проектов мало, либо они действительно разные.</div>"))
    if site_patterns:
        patterns_block += (tr("<h2>Общее в настройке сайтов</h2><p class=\"note\">Это свойства сайта целиком, а не страниц: robots.txt, разметка, доступность краулерам. Доля страниц здесь бессмысленна, поэтому просто «есть».</p>")
                           + _pattern_rows(patterns, results, "site"))

    doc = tr("<!doctype html><!-- indexgap-report --><html lang=\"ru\"><head><meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n<title>Портфель — сводный отчёт</title>\n<style>{a0}{a1}</style></head><body><div class=\"wrap\">\n<h1>Портфель</h1>\n<p class=\"sub\">{a2} проектов · {a3} страниц · {a4} критичных\n· {a5}</p>\n\n{a6}\n{a7}\n{a8}\n{a9}\n{a10}\n{a11}\n</div></body></html>", a0=CSS, a1=PORTFOLIO_CSS, a2=len(ok), a3=total_pages, a4=total_critical, a5=datetime.now().strftime('%d.%m.%Y %H:%M'), a6=_portfolio_cards(results), a7=failed_block, a8=patterns_block, a9=unique_block, a10=profiles_block, a11=notes_block)

    directory = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(directory, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return out_path


# ── сравнение двух сборок ─────────────────────────────────────────────────────

DIFF_HELP = {
    "page-removed": N_("Страница была в старой сборке и пропала из новой. Если она была открыта для индекса и редиректа на неё нет — на живом сайте по адресу с показами будет 404. Верни страницу или поставь 301 на ближайшую замену."),
    "page-redirected": N_("Страница пропала или стала заглушкой, но адрес переведён редиректом — посетители и вес уйдут по нему. Проверь, что цель редиректа существует."),
    "page-closed": N_("Страница была открыта для индекса и закрылась: появился noindex, canonical стал вести на другую страницу или она стала черновиком. Если это сделал шаблон — закроется весь раздел."),
    "nosnippet-added": N_("Появился запрет сниппета: страница останется в индексе, но пропадёт из ответов ИИ-поиска и расширенной выдачи."),
    "text-shrunk": N_("Текст сократился больше чем вдвое. Обычно это поломка генератора или данных, а не правка редактора."),
    "template-change": N_("title, H1 или description поменялись у многих страниц одного шаблона сразу — это правка шаблона. Убедись, что она намеренная: поисковик переоценит все эти страницы."),
    "new-finding": N_("Критичная находка `check`, которой в старой сборке не было."),
    "page-opened": N_("Страница была закрыта от индекса и открылась."),
    "pages-added": N_("Новые страницы по шаблонам адресов."),
}


def _diff_help(code, default=""):
    found = DIFF_HELP.get(code)
    return tr(found) if found else default


def build_diff(result: dict, items: list, findings: dict = None,
               out_path: str = "indexgap-diff.html", site: str = "",
               old_root: str = "", new_root: str = "", redirect_files: list = None) -> str:
    """Отчёт `diff`: изменения сгруппированы по виду, как находки в `check`."""
    counts = Counter(i[0] for i in items)
    changes = [c for c in result.get("template_changes") or [] if c.get("template")]
    rows = "".join(
        f'<tr><td class="mono">{_esc(c["pattern"])}</td><td>{_esc(c["field"])}</td>'
        f'<td class="n">{c["changed"]} / {c["pages"]}</td>'
        f'<td>{_esc(c["examples"][0]["old"])} → {_esc(c["examples"][0]["new"])}</td></tr>'
        for c in changes)
    template_block = (
        tr("<h2>Правки шаблонов</h2><div class=\"scroll\"><table><thead><tr><th>шаблон</th>"
           "<th>поле</th><th class=\"n\">страниц</th><th>например</th></tr></thead><tbody>")
        + rows + "</tbody></table></div>") if rows else ""
    findings_block = ""
    if findings is not None:
        findings_block = tr(
            "<p class=\"note\">Проверки check по обеим сборкам: новых критичных {a0}, "
            "новых «внимание» {a1}, исчезло критичных {a2}. Полные списки — в JSON.</p>",
            a0=findings["new_critical"], a1=findings["new_warning"],
            a2=findings["fixed_critical"])
    redirects = (tr("Редиректы учтены: {a0}.", a0=", ".join(redirect_files))
                 if redirect_files else
                 tr("Файлов редиректов рядом с новой сборкой нет: исчезнувшая страница "
                    "считается 404."))
    doc = tr(
        "<!doctype html><!-- indexgap-report --><html lang=\"ru\"><head><meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
        "<title>Что сломает деплой{a0}</title>\n<style>{a1}</style></head><body><div class=\"wrap\">\n"
        "<h1>Что сломает деплой</h1>\n<p class=\"sub\">{a2} · было {a3} → стало {a4} · {a5}</p>\n"
        "<div class=\"cards\">\n"
        "  <div class=\"card\"><div class=\"n\">{a6}</div><div class=\"l\">страниц было</div></div>\n"
        "  <div class=\"card\"><div class=\"n\">{a7}</div><div class=\"l\">страниц стало</div></div>\n"
        "  <div class=\"card\"><div class=\"n bad\">{a8}</div><div class=\"l\">критично</div></div>\n"
        "  <div class=\"card\"><div class=\"n warn\">{a9}</div><div class=\"l\">внимание</div></div>\n"
        "  <div class=\"card\"><div class=\"n\">{a10}</div><div class=\"l\">исчезло страниц</div></div>\n"
        "  <div class=\"card\"><div class=\"n\">{a11}</div><div class=\"l\">новых страниц</div></div>\n"
        "</div>\n<p class=\"note\">{a12}</p>\n{a13}\n<h2>Изменения по видам</h2>\n{a14}\n{a15}\n"
        "</div></body></html>",
        a0=" — " + _esc(site) if site else "", a1=CSS, a2=_esc(site),
        a3=_esc(old_root), a4=_esc(new_root), a5=datetime.now().strftime('%d.%m.%Y %H:%M'),
        a6=result.get("old_pages", 0), a7=result.get("new_pages", 0),
        a8=counts.get("critical", 0), a9=counts.get("warning", 0),
        a10=len(result.get("removed") or []), a11=(result.get("added") or {}).get("total", 0),
        a12=_esc(redirects), a13=findings_block,
        a14=(_groups_html(items, helper=_diff_help) if items else
             tr("<div class=\"empty\">Сборки не различаются ничем, что видит поисковик.</div>")),
        a15=template_block)

    directory = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(directory, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return out_path
