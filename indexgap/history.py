# -*- coding: utf-8 -*-
"""
История прогонов `doctor`: что было, что стало и как это менялось.

Одна выгрузка говорит, где сайт сейчас. Ряд выгрузок говорит, работают ли
правки: «после перевода раздела в индексе стало на 40 страниц больше»,
«PerplexityBot перестал приходить на прошлой неделе». Без ряда пакет
советовал, но не показывал результата.

Каждый прогон ложится в папку отдельным JSON (`runs/<время>.json`), рядом —
`trend.html`: число страниц на каждом шаге воронки и открытые ИИ-поиском
страницы по датам. Без зависимостей: график — встроенный SVG.
"""

from __future__ import annotations

import datetime
import html
import json
import os

from .core import SourceError
from .i18n import tr


def _runs_dir(root: str) -> str:
    return os.path.join(root, "runs")


def runs(root: str) -> list:
    """Пути прошлых прогонов по порядку времени."""
    folder = _runs_dir(root)
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, n) for n in sorted(os.listdir(folder)) if n.endswith(".json")]


def latest(root: str) -> dict:
    """Последний сохранённый прогон или None."""
    for path in reversed(runs(root)):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("funnel"), dict):
            data.setdefault("_path", path)
            return data
    return None


def save(root: str, run: dict, now: datetime.datetime = None) -> str:
    """Кладёт прогон в историю. Имя — время, чтобы порядок файлов был порядком прогонов."""
    folder = _runs_dir(root)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        raise SourceError(tr("Папку истории {a0} не создать: {a1}", a0=root, a1=exc))
    now = now or datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%dT%H-%M-%S")
    path = os.path.join(folder, stamp + ".json")
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(folder, f"{stamp}-{n}.json")
    record = {**run, "_saved": now.isoformat(timespec="seconds")}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=1, default=str)
    return path


def series(root: str) -> dict:
    """{подпись шага: [(дата, число), …]} по всем прогонам — для графика."""
    out, dates = {}, []
    for path in runs(root):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        when = (data.get("_saved") or os.path.basename(path)[:19].replace("T", " "))
        dates.append(when.replace("T", " ")[:16])
        for step in (data.get("funnel") or {}).get("steps") or ():
            if step.get("id") == "in-source":
                continue                  # строки «из них в …» загромождают график
            name = (step.get("name") or step.get("id") or "").strip()
            out.setdefault(name, []).append((len(dates) - 1, step.get("count") or 0))
    # Дата — если все прогоны в разные дни; если нет, со временем.
    if len({d[:10] for d in dates}) == len(dates):
        dates = [d[:10] for d in dates]
    return {"dates": dates, "lines": out}


_COLORS = ("#2563eb", "#059669", "#d97706", "#dc2626", "#7c3aed", "#0891b2", "#4b5563")


def render(root: str, site: str = "") -> str:
    """trend.html рядом с историей. Возвращает путь."""
    data = series(root)
    dates, lines = data["dates"], data["lines"]
    path = os.path.join(root, "trend.html")
    width, height, pad = 760, 320, 44
    top = max([v for pts in lines.values() for _, v in pts] + [1])
    span = max(len(dates) - 1, 1)

    def x(i):
        return pad + (width - 2 * pad) * i / span

    def y(v):
        return height - pad - (height - 2 * pad) * v / top

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="trend" '
             f'style="width:100%;max-width:{width}px">',
             f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" '
             'stroke="#9ca3af"/>',
             f'<text x="{pad - 6}" y="{y(top) + 4}" text-anchor="end" font-size="11" '
             f'fill="#6b7280">{top}</text>',
             f'<text x="{pad - 6}" y="{y(0) + 4}" text-anchor="end" font-size="11" '
             'fill="#6b7280">0</text>']
    legend = []
    for n, (name, pts) in enumerate(sorted(lines.items())):
        color = _COLORS[n % len(_COLORS)]
        path_d = " ".join(f"{'M' if i == 0 else 'L'}{x(d):.1f},{y(v):.1f}"
                          for i, (d, v) in enumerate(pts))
        parts.append(f'<path d="{path_d}" fill="none" stroke="{color}" stroke-width="2"/>')
        for d, v in pts:
            parts.append(f'<circle cx="{x(d):.1f}" cy="{y(v):.1f}" r="3" fill="{color}">'
                         f'<title>{html.escape(name)}: {v} ({html.escape(dates[d])})</title></circle>')
        legend.append(f'<li><span style="background:{color}"></span>{html.escape(name)}: '
                      f'{pts[-1][1] if pts else 0}</li>')
    for i, when in enumerate(dates):
        if len(dates) <= 12 or i in (0, len(dates) - 1) or i % max(1, len(dates) // 8) == 0:
            parts.append(f'<text x="{x(i):.1f}" y="{height - pad + 16}" text-anchor="middle" '
                         f'font-size="11" fill="#6b7280">{html.escape(when)}</text>')
    parts.append("</svg>")
    title = tr("Динамика воронки")
    doc = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>"
        "body{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;"
        "background:#f8fafc;color:#111827}.wrap{max-width:820px;margin:0 auto;padding:32px 16px}"
        "ul{list-style:none;padding:0;columns:2}li{margin:2px 0}"
        "li span{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}"
        "@media(prefers-color-scheme:dark){body{background:#0f172a;color:#e5e7eb}}"
        "</style></head><body><div class=\"wrap\">"
        f"<h1>{html.escape(title)}</h1><p>{html.escape(site)} · "
        + tr("прогонов: {a0}", a0=len(dates)) + "</p>"
        + "".join(parts) + "<ul>" + "".join(legend) + "</ul>"
        + "<p>" + tr("Каждая точка — один прогон `indexgap doctor --history`. "
                     "Наведи на точку, чтобы увидеть число.") + "</p>"
        + "</div></body></html>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path
