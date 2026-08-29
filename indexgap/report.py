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

LEVEL_LABEL = {"critical": ("bad", "критично"), "warning": ("warn", "внимание"),
               "info": ("ok", "мелочь")}

# Что означает код и что с ним делать. Раньше половина кодов, которые выдаёт
# пакет, не была описана нигде — человек видел находку без инструкции.
CODE_HELP = {
    "unsupported-number": "Число в тексте, которого нет в данных. Проверь по строке "
                          "датасета и либо исправь, либо убери утверждение.",
    "check-by-eye": "Числа со словами, которых нет в данных. Часть таких — обычная речь "
                    "(«3 шага», «5 звёзд»), часть — выдумка агента. Список для просмотра "
                    "глазами, а не приговор.",
    "robots-unreadable": "robots.txt не прочитался — проверь путь в --robots.",
    "stale-event": "Дата на странице прошла, а страница открыта для индексации. "
                   "Поисковик показывает людям то, чего уже нет: закрой noindex, "
                   "поставь редирект на актуальное или перепиши в отчёт о прошедшем.",
    "stale-closed": "Дата прошла, и страница уже закрыта от индексации — так и надо. "
                    "Строка справочная.",
    "still-draft": "В фронтматтере `status: draft`. Страница попадёт в сборку "
                   "недописанной — допиши или исключи из публикации.",
    "brief-left": "В файле остался блок брифа или TODO — он уедет в текст страницы.",
    "noindex": "Страница закрыта от индексации. Если это ошибка шаблона — убери "
               "мета-тег robots.",
    "nosnippet": "Запрещён сниппет. Страница может быть в индексе, но не появится "
                 "ни в расширенной выдаче, ни в ответах ИИ-поиска.",
    "canonical-elsewhere": "Canonical ведёт на другую страницу — эта отдаёт ей вес "
                           "и сама из индекса выпадает.",
    "orphan": "На страницу не ведёт ни одна внутренняя ссылка. В sitemap она есть, "
              "но краулер до неё не дойдёт. Поставь ссылки с хабовых страниц раздела.",
    "unreachable": "От главной до страницы нельзя дойти по ссылкам.",
    "near-duplicate": "Почти совпадает с другой страницей. Поисковик оставит одну. "
                      "Перепиши под другой интент или оставь одну с canonical.",
    "similar": "Похожа на другую страницу, но ниже порога дубля. Повод посмотреть.",
    "low-uniqueness": "Шаблон вытеснил содержание: уникального текста меньше четверти.",
    "template-skeleton": "Одинаковый скелет заголовков на многих страницах — "
                         "для поисковика это признак штамповки.",
    "same-opening": "Одинаковое начало текста на многих страницах.",
    "thin": "Текста меньше порога. Порог правится в indexgap.json — "
            "для карточки товара 250 слов абсурдны, для гайда нормальны.",
    "no-title": "Нет title.",
    "title-short": "Title короче рекомендованного.",
    "title-long": "Title обрежется в выдаче.",
    "no-description": "Нет meta description — поисковик соберёт сниппет сам.",
    "description-length": "Длина description вне рекомендованного диапазона.",
    "no-h1": "Нет H1 — поисковику нечем определить тему страницы.",
    "many-h1": "H1 больше одного.",
    "no-headings": "На странице нет заголовков — структуры нет.",
    "duplicate-title": "Одинаковый title у нескольких страниц — склейка в выдаче.",
    "duplicate-description": "Одинаковый description у нескольких страниц.",
    "deep": "Слишком много кликов от главной.",
    "vague-anchor": "Анкоры вида «здесь» и «подробнее» не передают смысл.",
    "source-note": "Замечание к самому файлу: кодировка, фронтматтер, разметка.",
    "js-shell": "В исходном HTML почти нет текста. Краулеры ИИ-поиска не исполняют "
                "JavaScript и увидят пустую страницу.",
    "answer-preamble": "Первый абзац — разгон, а не ответ. Именно первый абзац "
                       "цитируют ИИ-поиск и блок быстрых ответов.",
    "answer-short": "Первый абзац слишком короткий для самостоятельного ответа.",
    "answer-long": "Первый абзац длинноват для цитирования.",
    "no-answer": "Не нашлось ни одного абзаца.",
    "no-question-headings": "Ни один подзаголовок не сформулирован как вопрос.",
    "long-paragraph": "Очень длинные абзацы плохо извлекаются.",
    "no-structure": "Нет ни списков, ни таблиц.",
    "img-no-alt": "Изображения без alt.",
    "jsonld-broken": "Блок JSON-LD не парсится — для поисковика его нет.",
    "jsonld-faq-invisible": "В разметке FAQ есть вопросы, которых нет на странице. "
                            "Это риск ручных санкций.",
    "jsonld-no-type": "В блоке JSON-LD нет @type.",
    "no-date": "Нет машиночитаемой даты.",
    "no-author": "Не указан автор или организация.",
    "robots-blocks-all": "robots.txt закрывает сайт целиком.",
    "ai-crawler-blocked": "В robots.txt закрыт краулер ИИ-поисковика.",
    "robots-no-sitemap": "В robots.txt нет строки Sitemap.",
    "no-robots": "robots.txt не проверялся.",
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
        lines.append(f"<li><strong>{_esc(code)}</strong> — {count} стр.: "
                     f"{_esc(CODE_HELP.get(code, ''))}</li>")
    if not lines:
        return ('<div class="first"><strong>Критичных находок нет.</strong> '
                'Дальше смотри в Search Console и Вебмастере: локальные проверки '
                'своё сказали.</div>')
    return ('<div class="first"><strong>Начни с этого</strong>'
            '<ol>' + "".join(lines) + '</ol></div>')


def _groups_html(issues: list, per_group: int = 25) -> str:
    if not issues:
        return '<div class="empty">Ничего не найдено.</div>'
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
        shown = rows[:per_group]
        more = (f'<p class="note">Показано {len(shown)} из {len(rows)}. '
                f'Полный список — в JSON рядом с отчётом.</p>'
                if len(rows) > per_group else "")
        items = "".join(
            f'<li><span class="mono">{_esc(url)}</span> — {_esc(msg)}</li>'
            for url, msg in shown)
        help_text = CODE_HELP.get(code, "")
        blocks.append(
            f'<details class="grp"{" open" if level == "critical" else ""}>'
            f'<summary><span class="pill {cls}">{_esc(label)}</span>'
            f'<span class="what"><span class="mono">{_esc(code)}</span> — '
            f'{_esc(help_text)}</span>'
            f'<span class="cnt">{len(rows)}</span></summary>'
            f'<div class="grp-body"><ul>{items}</ul>{more}</div></details>')
    return "".join(blocks)


def build(analysis: dict, funnel_result: dict = None, causes: list = None,
          out_path: str = "indexgap-report.html", site: str = "",
          cross: list = None, notes: list = None, title: str = "Отчёт конвейера") -> str:
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
    ) or '<tr><td colspan="3" style="color:var(--fg3)">Похожих страниц не найдено.</td></tr>'
    dupe_more = (f'<p class="note">Показано 60 пар из {len(dupes)}. '
                 f'Остальные — в JSON.</p>' if len(dupes) > 60 else "")

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
                '<h2>Сравнение поисковиков</h2>'
                '<div class="scroll"><table><thead><tr><th>где страница</th>'
                '<th class="n">страниц</th><th>что это значит</th></tr></thead>'
                '<tbody>' + rows + '</tbody></table></div>'
                '<p class="note">Страница, которой нет нигде, — почти всегда техническая '
                'проблема. Страница, которая есть в одном индексе и нет в другом, — '
                'уже вопрос оценки качества или скорости конкретного поисковика, '
                'и техническими правками обычно не лечится.</p>')

    causes_block = (
        '<h2>Почему страницы не в индексе</h2>'
        '<div class="scroll"><table><thead><tr><th>причина</th><th class="n">страниц</th>'
        '<th>что делать</th></tr></thead><tbody>' + cause_rows + '</tbody></table></div>'
        '<p class="note">Разбор адресный: конкретные URL по каждой причине лежат в JSON. '
        'Страница может попасть сразу в несколько причин — так и бывает.</p>'
    ) if cause_rows else ""

    funnel_block = ""
    if funnel_result and funnel_result.get("steps"):
        funnel_block = ("<h2>Воронка конвейера</h2>" + _funnel_html(funnel_result) +
                        '<p class="note">Каждый переход теряет страницы. '
                        'Потери на разных переходах лечатся по-разному, поэтому важно '
                        'видеть, где именно они происходят. Учти: экспорт «Страницы» '
                        'из Search Console — это отчёт о показах, и страница в индексе '
                        'без показов в него не попадает.</p>')

    doc = f"""<!doctype html><!-- indexgap-report --><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}{(" — " + _esc(site)) if site else ""}</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>{_esc(title)}</h1>
<p class="sub">{_esc(site)} · {len(pages)} страниц · {datetime.now().strftime("%d.%m.%Y %H:%M")}</p>

{warn_html}

<div class="cards">
  <div class="card"><div class="n">{len(pages)}</div><div class="l">страниц разобрано</div></div>
  <div class="card"><div class="n bad">{counts.get("critical", 0)}</div><div class="l">критично</div></div>
  <div class="card"><div class="n warn">{counts.get("warning", 0)}</div><div class="l">внимание</div></div>
  <div class="card"><div class="n bad">{len(graph.get("orphans") or [])}</div><div class="l">сирот без входящих ссылок</div></div>
  <div class="card"><div class="n bad">{len(dupes)}</div><div class="l">пар похожих страниц</div></div>
</div>

{_first_things(issues, graph, dupes)}

{funnel_block}
{cross_block}
{causes_block}

<h2>Все находки по причинам</h2>
{_groups_html(issues)}

<h2>Похожие страницы</h2>
<div class="scroll"><table><thead><tr><th>страница</th><th>похожа на</th>
<th class="n">совпадение</th></tr></thead><tbody>{dupe_rows}</tbody></table></div>
{dupe_more}
<p class="note">Совпадение выше порога означает, что поисковик, скорее всего, оставит
в индексе одну страницу из пары. На конвейере это происходит, когда шаблон
даёт больше текста, чем подставляемые данные.</p>
</div></body></html>"""

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
                f'<div class="pcard err"><div class="nm">{_esc(r["name"])}</div>'
                f'<div class="pr">не проверен</div>'
                f'<div class="row" style="display:block">{_esc(r["error"])}</div></div>')
            continue
        counts = r.get("counts") or {}
        rows = [
            ("страниц", r.get("pages", 0)),
            ("критично", counts.get("critical", 0)),
            ("внимание", counts.get("warning", 0)),
            ("сирот", r.get("orphans", 0)),
            ("похожих пар", r.get("duplicates", 0)),
        ]
        body = "".join(f'<div class="row"><span>{k}</span><b>{v}</b></div>'
                       for k, v in rows)
        cards.append(
            f'<div class="pcard"><div class="nm">{_esc(r["name"])}</div>'
            f'<div class="pr">{_esc(r.get("profile_title") or r.get("profile", ""))}</div>'
            f'{body}</div>')
    return '<div class="pgrid">' + "".join(cards) + "</div>"


def _pattern_rows(patterns: list, results: list, scope: str = "page") -> str:
    names = [r["name"] for r in results if not r.get("error")]
    rows = []
    for p in patterns:
        if p.get("scope", "page") != scope:
            continue
        cls, label = LEVEL_LABEL.get(p["level"], ("", p["level"]))
        cells = []
        for name in names:
            detail = p["detail"].get(name)
            if not detail:
                cells.append('<td class="n" style="color:var(--fg3)">—</td>')
            elif scope == "site":
                cells.append('<td class="n share">есть</td>')
            else:
                cells.append(f'<td class="n share">{detail["share"]:.0%}</td>')
        hint = ('<br><span style="color:var(--warn)">Срабатывает почти на всех '
                'страницах всех проектов — это вопрос к порогу, а не к страницам.</span>'
                if p.get("threshold_suspect") else "")
        rows.append(
            f'<tr><td><span class="pill {cls}">{_esc(label)}</span></td>'
            f'<td class="mono">{_esc(p["code"])}</td>'
            f'<td>{_esc(CODE_HELP.get(p["code"], ""))}{hint}</td>'
            + "".join(cells) + "</tr>")
    head = "".join(f'<th class="n">{_esc(n)}</th>' for n in names)
    return ('<div class="scroll"><table><thead><tr><th></th><th>код</th>'
            '<th>что это</th>' + head + '</tr></thead><tbody>'
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
        notes_block = ('<h2>Что пакет сказал о самих проектах</h2>'
                       '<div class="grp-body"><ul>' + "".join(note_items) + '</ul></div>')

    unique_block = ""
    if uniques:
        items = "".join(
            f'<li><b>{_esc(u["name"])}</b>: '
            + ", ".join(f'<span class="mono">{_esc(c)}</span>' for c in u["codes"][:12])
            + "</li>" for u in uniques)
        unique_block = ('<h2>Личное у каждого</h2>'
                        '<p class="note">Эти находки встретились ровно в одном проекте. '
                        'Их чинят по месту, в отличие от общих граблей выше.</p>'
                        '<div class="grp-body"><ul>' + items + '</ul></div>')

    profiles_block = ""
    seen_profiles = {}
    for r in ok:
        if r.get("profile") and r["profile"] not in seen_profiles:
            seen_profiles[r["profile"]] = (r.get("profile_title", ""),
                                           r.get("profile_notes") or [])
    if seen_profiles:
        rows = "".join(
            f'<tr><td class="mono">{_esc(key)}</td><td>{_esc(title)}</td>'
            f'<td>{_esc(" ".join(notes))}</td></tr>'
            for key, (title, notes) in sorted(seen_profiles.items()))
        profiles_block = ('<h2>Профили, по которым считали</h2>'
                          '<div class="scroll"><table><thead><tr><th>профиль</th>'
                          '<th>тип контента</th><th>что важно помнить</th></tr></thead>'
                          '<tbody>' + rows + '</tbody></table></div>'
                          '<p class="note">Пороги у профилей разные намеренно: '
                          '250 слов — норма для гайда и приговор для карточки события, '
                          'а сверка фактов бессмысленна там, где датасета нет.</p>')

    failed_block = ""
    if failed:
        items = "".join(f'<li><b>{_esc(r["name"])}</b> — {_esc(r["error"])}</li>'
                        for r in failed)
        failed_block = ('<h2>Не проверены</h2><div class="grp-body"><ul>'
                        + items + '</ul></div>')

    page_patterns = [p for p in patterns if p.get("scope", "page") == "page"]
    site_patterns = [p for p in patterns if p.get("scope") == "site"]
    patterns_block = ('<h2>Общие грабли на страницах</h2>'
                      '<p class="note">Находки, встретившиеся минимум в двух проектах. '
                      'В ячейках — доля затронутых страниц проекта: сто находок '
                      'на трёх тысячах страниц и десять на двадцати — одна болезнь '
                      'разной громкости. Это уже не баг конкретного сайта, а свойство '
                      'того, как эти сайты собираются: чинить надо привычку.</p>'
                      + _pattern_rows(patterns, results, "page")) if page_patterns else (
        '<h2>Общие грабли на страницах</h2><div class="empty">Ни одна страничная находка '
        'не повторилась в двух проектах — либо проектов мало, либо они действительно '
        'разные.</div>')
    if site_patterns:
        patterns_block += ('<h2>Общее в настройке сайтов</h2>'
                           '<p class="note">Это свойства сайта целиком, а не страниц: '
                           'robots.txt, разметка, доступность краулерам. Доля страниц '
                           'здесь бессмысленна, поэтому просто «есть».</p>'
                           + _pattern_rows(patterns, results, "site"))

    doc = f"""<!doctype html><!-- indexgap-report --><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Портфель — сводный отчёт</title>
<style>{CSS}{PORTFOLIO_CSS}</style></head><body><div class="wrap">
<h1>Портфель</h1>
<p class="sub">{len(ok)} проектов · {total_pages} страниц · {total_critical} критичных
· {datetime.now().strftime("%d.%m.%Y %H:%M")}</p>

{_portfolio_cards(results)}
{failed_block}
{patterns_block}
{unique_block}
{profiles_block}
{notes_block}
</div></body></html>"""

    directory = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(directory, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return out_path
