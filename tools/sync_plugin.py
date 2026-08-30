#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Собирает обёртку плагина Claude Code вокруг скиллов, которые уже есть в пакете.

Источник один — `indexgap/skills/`. Здесь ничего не пишется руками: манифест
берёт версию из `indexgap.__version__`, а `skills/` в корне репозитория
получается из английских `SKILL.en.md`. Каталог плагинов международный,
поэтому основным становится английский, а не русский оригинал.

Расхождение ловит `tests/test_plugin.py`: он собирает то же самое в памяти и
сравнивает с тем, что лежит в репозитории. Значит забыть пересобрать нельзя —
CI покажет это раньше, чем каталог.

Запуск:  python3 tools/sync_plugin.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from indexgap import __version__                       # noqa: E402

SOURCE = ROOT / "indexgap" / "skills"
SKILLS = ROOT / "skills"
MANIFEST = ROOT / ".claude-plugin" / "plugin.json"

REPO = "https://github.com/borisowlexa2010-star/IndexGap"
DOCS = "https://borisowlexa2010-star.github.io/IndexGap/"


def manifest() -> dict:
    return {
        "name": "indexgap",
        "description": (
            "Quality control for programmatic SEO pipelines. Gives an agent "
            "deterministic ground truth about a generated site: which numbers on "
            "a page are absent from the dataset row that produced it, which "
            "findings are one template defect rather than a thousand, which "
            "pages are near-duplicates of each other, and what search engines "
            "actually indexed. Runs the indexgap CLI — Python standard library "
            "only, no dependencies, no API keys except for the optional "
            "AI-citation command."
        ),
        "version": __version__,
        "author": {"name": "Alexey Borisov"},
        "homepage": DOCS,
        "repository": REPO,
        "license": "MIT",
        "keywords": [
            "seo", "programmatic-seo", "technical-seo", "content-quality",
            "hreflang", "sitemap", "site-audit", "quality-assurance",
        ],
    }


def skill_names() -> list:
    return sorted(p.name for p in SOURCE.iterdir()
                  if p.is_dir() and (p / "SKILL.en.md").exists())


def build(write: bool = True) -> dict:
    """Возвращает {путь относительно корня: содержимое}. write=False — только собрать."""
    files = {".claude-plugin/plugin.json":
             json.dumps(manifest(), ensure_ascii=False, indent=2) + "\n"}

    for name in skill_names():
        text = (SOURCE / name / "SKILL.en.md").read_text(encoding="utf-8")
        files[f"skills/{name}/SKILL.md"] = text

    if write:
        if SKILLS.exists():
            shutil.rmtree(SKILLS)
        for path, text in files.items():
            target = ROOT / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    return files


if __name__ == "__main__":
    made = build()
    print(f"плагин indexgap {__version__}: "
          f"{len(made) - 1} скилл(ов) + манифест")
    for path in made:
        print(f"  {path}")
