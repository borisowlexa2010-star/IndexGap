# -*- coding: utf-8 -*-
"""
Короткая сводка прогона в Markdown — для страницы сборки в CI.

`python -m indexgap.summary indexgap-check.json >> "$GITHUB_STEP_SUMMARY"`.
HTML-отчёт в CI лежит артефактом, который надо скачать; сводка видна сразу
на странице прогона: сколько находок, какие новые, с чего начинать.
"""

from __future__ import annotations

import json
import sys
from collections import Counter

from .i18n import N_, tr

LEVELS = ("critical", "warning", "info")
LABELS = {"critical": N_("критично"), "warning": N_("внимание"), "info": N_("к сведению")}
LIMIT = 20


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render(data: dict) -> str:
    issues = [i for i in data.get("issues") or [] if isinstance(i, dict)]
    by_level = Counter(i.get("level") for i in issues)
    lines = [tr("### indexgap: {a0} страниц(ы), {a1}", a0=data.get("pages", 0),
                a1=data.get("site", "")), ""]
    lines += ["| " + " | ".join(tr(LABELS[level]) for level in LEVELS) + " |",
              "|" + "---:|" * len(LEVELS),
              "| " + " | ".join(str(by_level.get(level, 0)) for level in LEVELS) + " |", ""]

    baseline = data.get("baseline")
    if isinstance(baseline, dict):
        new = baseline.get("new") or []
        crit = [i for i in new if i.get("level") == "critical"]
        lines.append(tr("Против базовой линии: новых {a0}, из них критичных {a1}; "
                        "исчезло {a2}.", a0=len(new), a1=len(crit),
                        a2=len(baseline.get("fixed") or [])))
        lines.append("")
        shown = crit or new
        if shown:
            lines.append(tr("**Новые находки**") if not crit else tr("**Новые критичные находки**"))
            lines.append("")
            for item in shown[:LIMIT]:
                lines.append(f"- `{_cell(item.get('code'))}` {_cell(item.get('url'))} — "
                             f"{_cell(item.get('message'))}")
            if len(shown) > LIMIT:
                lines.append(tr("- … и ещё {a0}", a0=len(shown) - LIMIT))
            lines.append("")

    common = Counter((i.get("level"), i.get("code")) for i in issues
                     if i.get("level") in ("critical", "warning"))
    if common:
        lines += [tr("**Чаще всего**"), "", "| " + tr("уровень") + " | " + tr("код")
                  + " | " + tr("страниц") + " |", "|---|---|---:|"]
        order = {level: n for n, level in enumerate(LEVELS)}
        for (level, code), count in sorted(common.items(),
                                           key=lambda kv: (order.get(kv[0][0], 9), -kv[1],
                                                           str(kv[0][1])))[:10]:
            lines.append(f"| {tr(LABELS.get(level, level))} | `{_cell(code)}` | {count} |")
        lines.append("")
    if not issues:
        lines += [tr("Находок нет."), ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(tr("использование: python -m indexgap.summary indexgap-check.json"),
              file=sys.stderr)
        return 2
    try:
        with open(argv[0], "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"{argv[0]}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(data, dict):
        print(tr("{a0}: это не данные прогона indexgap check", a0=argv[0]), file=sys.stderr)
        return 2
    sys.stdout.write(render(data) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
