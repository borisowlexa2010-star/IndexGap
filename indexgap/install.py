# -*- coding: utf-8 -*-
"""
Установка в проект: `indexgap init`.

Инструмент бесполезен, если о нём надо помнить. Ученик курса не будет держать
в голове семь команд и два десятка флагов — он работает с агентом в терминале.
Поэтому установка кладёт в проект скиллы, которые агент подхватывает сам,
и конфиг, в котором записано то, что отличает этот проект от любого другого.

**Что копируется и что нет — главное правило этого модуля.**

Копируются только скиллы: инструкции о том, какие команды бывают, что значат
коды находок и что говорить человеку. Они одинаковы для каталога виз,
афиши и ленты обсуждений — это знание об инструменте, а не о проекте.

Не копируется ничего проектного. Адрес сайта, каталог страниц, тип контента,
пороги — определяются из самого проекта или спрашиваются. Отдельно и особо:
**ключ IndexNow между проектами не переносится никогда.** Он привязан к домену
файлом в корне сайта; чужой ключ гарантированно даст 403. Установщик может
только сгенерировать новый — для этого проекта и больше ни для какого.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from collections import Counter

from .core import SourceError, DEFAULT_EXTS, SKIP_DIRS, read_text
from .i18n import tr

SKILL_DIR = os.path.join(".claude", "skills")
CONFIG_NAME = "indexgap.json"
GITIGNORE_MARK = "# indexgap"
AGENTS_START = "<!-- indexgap:start -->"
AGENTS_END = "<!-- indexgap:end -->"

# Каталоги, в которых обычно лежат страницы. Порядок — приоритет при равенстве.
LIKELY_CONTENT = ("content", "src/content", "app/content", "pages", "src/pages",
                  "posts", "_posts", "docs", "articles", "blog", "site")

# Где обычно записан адрес сайта.
SITE_FILES = ("package.json", "astro.config.mjs", "astro.config.ts", "astro.config.js",
              "next.config.js", "next.config.mjs", "next-sitemap.config.js",
              "netlify.toml", "vercel.json", "gatsby-config.js", "nuxt.config.ts",
              "hugo.toml", "config.toml", "_config.yml", "mkdocs.yml", "CNAME")

SITE_RE = re.compile(r"https?://[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s\"'<>,)]*)?", re.I)
KEYWORD_COLUMNS = ("keyword", "keywords", "ключ", "query", "term", "запрос")
DATE_FIELDS = ("date", "startdate", "start_date", "event_date", "published")


def _pages_in(directory: str) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in SKIP_DIRS]
        total += sum(1 for f in filenames if f.lower().endswith(DEFAULT_EXTS))
        if total > 5000:
            break
    return total


def detect_content_dir(root: str) -> str:
    """
    Ищет каталог, который отображается в корень сайта.

    Это самая частая ошибка при запуске вручную: человек указывает корень
    проекта, адреса сдвигаются на сегмент, и все страницы выглядят сиротами.
    Поэтому лучше угадать и показать, чем промолчать.
    """
    candidates = {}
    for name in LIKELY_CONTENT:
        path = os.path.join(root, *name.split("/"))
        if os.path.isdir(path):
            count = _pages_in(path)
            if count:
                candidates[name] = count
    if candidates:
        best = max(candidates.items(), key=lambda kv: (kv[1], -LIKELY_CONTENT.index(kv[0])))
        return os.path.join(".", *best[0].split("/"))

    # Ничего знакомого — берём подкаталог первого уровня с наибольшим числом страниц.
    best_name, best_count = "", 0
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry)
        if not os.path.isdir(path) or entry.startswith(".") or entry in SKIP_DIRS:
            continue
        count = _pages_in(path)
        if count > best_count:
            best_name, best_count = entry, count
    if best_count >= 3:
        return os.path.join(".", best_name)
    return "." if _pages_in(root) else ""


def detect_site(root: str, content_dir: str = "") -> str:
    """Адрес сайта из sitemap, robots.txt или конфига сборщика."""
    for rel in ("public/sitemap.xml", "sitemap.xml", "out/sitemap.xml",
                "dist/sitemap.xml", "_site/sitemap.xml"):
        path = os.path.join(root, *rel.split("/"))
        if os.path.isfile(path):
            try:
                text, _ = read_text(path)
            except SourceError:
                continue
            found = re.search(r"<loc>\s*(https?://[^<\s]+)", text, re.I)
            if found:
                return _origin(found.group(1))

    for rel in ("public/robots.txt", "robots.txt", "static/robots.txt"):
        path = os.path.join(root, *rel.split("/"))
        if os.path.isfile(path):
            try:
                text, _ = read_text(path)
            except SourceError:
                continue
            found = re.search(r"^\s*sitemap\s*:\s*(\S+)", text, re.I | re.M)
            if found:
                return _origin(found.group(1))

    for name in SITE_FILES:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        try:
            text, _ = read_text(path)
        except SourceError:
            continue
        if name == "CNAME":
            host = text.strip().splitlines()[0].strip() if text.strip() else ""
            if host:
                return f"https://{host}/"
        for match in SITE_RE.finditer(text):
            url = match.group(0)
            if any(bad in url for bad in ("schema.org", "w3.org", "npmjs", "github.com",
                                          "localhost", "example.com", "json-schema")):
                continue
            return _origin(url)
    return ""


def _origin(url: str) -> str:
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}/"


def detect_dataset(root: str) -> str:
    """CSV с семантикой: ищем колонку с ключом, а не просто любой csv."""
    best = ""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in SKIP_DIRS]
        if dirpath.count(os.sep) - root.count(os.sep) > 2:
            dirnames[:] = []
        for name in sorted(filenames):
            if not name.lower().endswith((".csv", ".tsv")):
                continue
            path = os.path.join(dirpath, name)
            try:
                text, _ = read_text(path)
            except SourceError:
                continue
            header = (text.splitlines() or [""])[0].lower()
            if any(col in header for col in KEYWORD_COLUMNS):
                rel = os.path.relpath(path, root)
                if not best or len(rel) < len(best):
                    best = os.path.join(".", rel)
    return best


def detect_profile(root: str, content_dir: str, dataset: str) -> tuple:
    """
    Тип контента по форме проекта. Возвращает (профиль, на чём основан вывод).

    Вывод показывается человеку обязательно: угадывать молча — тот же грех,
    что и молчаливая автонастройка порогов.
    """
    from . import core

    path = os.path.join(root, content_dir) if content_dir else root
    if not os.path.isdir(path):
        return "catalog", tr("каталог страниц не найден, взят профиль по умолчанию")

    pages, dated, html, total, short = 0, 0, 0, 0, 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in SKIP_DIRS]
        for name in sorted(filenames):
            if not name.lower().endswith(DEFAULT_EXTS):
                continue
            total += 1
            if total > 200:
                break
            if name.lower().endswith((".html", ".htm")):
                html += 1
            try:
                text, _ = read_text(os.path.join(dirpath, name))
            except SourceError:
                continue
            pages += 1
            head = text[:1200].lower()
            if any(re.search(rf"^\s*{f}\s*:", head, re.M) for f in DATE_FIELDS):
                dated += 1
            if len(re.findall(r"\w+", text, flags=re.UNICODE)) < 120:
                short += 1
        if total > 200:
            break

    if not pages:
        return "catalog", tr("страниц не найдено, взят профиль по умолчанию")
    if dated / pages >= 0.4:
        return "events", tr("у {a0} из {a1} страниц есть дата во фронтматтере", a0=dated, a1=pages)
    if pages <= 40 and html / pages >= 0.6:
        return "product", tr("{a0} страниц, почти все собранный HTML — похоже на лендинги", a0=pages)
    if not dataset and short / pages >= 0.5:
        return "ugc", tr("датасета нет, {a0} из {a1} страниц короткие — похоже на ленту", a0=short, a1=pages)
    if dataset:
        return "catalog", tr("рядом лежит датасет {a0}", a0=os.path.basename(dataset))
    return "catalog", tr("{a0} страниц без явных признаков другого типа", a0=pages)


# ── запись ────────────────────────────────────────────────────────────────────

def skills_source() -> str:
    """Каталог со скиллами внутри установленного пакета."""
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
    if os.path.isdir(here):
        return here
    # Запуск из исходников репозитория, где скиллы лежат на уровень выше.
    fallback = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "skills")
    if os.path.isdir(fallback):
        return fallback
    raise SourceError(tr("не найден каталог скиллов внутри пакета — переустанови indexgap"))


def install_skills(target_root: str) -> list:
    """
    Кладёт скиллы в `.claude/skills/<имя>/SKILL.md`.

    Скиллы перезаписываются всегда: это знание об инструменте, оно обновляется
    вместе с ним и не содержит ничего, что человек мог бы там настроить.

    Язык берётся тот же, что у остального вывода. Рядом с русским `SKILL.md`
    лежит `SKILL.en.md`; если перевода для языка нет, ставится русский —
    скилл на понятном агенту языке лучше, чем отсутствие скилла.
    """
    from .i18n import get_lang

    source = skills_source()
    lang = get_lang()
    written = []
    for name in sorted(os.listdir(source)):
        skill_file = os.path.join(source, name, "SKILL.md")
        if lang != "ru":
            localized = os.path.join(source, name, f"SKILL.{lang}.md")
            if os.path.isfile(localized):
                skill_file = localized
        if not os.path.isfile(skill_file):
            continue
        destination = os.path.join(target_root, SKILL_DIR, name)
        os.makedirs(destination, exist_ok=True)
        shutil.copyfile(skill_file, os.path.join(destination, "SKILL.md"))
        written.append(os.path.join(SKILL_DIR, name, "SKILL.md"))
    if not written:
        raise SourceError(tr("в пакете не оказалось ни одного скилла"))
    return written


def write_config(root: str, detected: dict, force: bool = False) -> tuple:
    """
    Пишет `indexgap.json`. Существующий не трогает без `--force`:
    там могут быть пороги, подобранные под проект руками.
    """
    path = os.path.join(root, CONFIG_NAME)
    if os.path.isfile(path) and not force:
        return path, False

    config = {
        "_комментарий": tr("Настройки этого проекта. Профиль задаёт пороги по типу контента; всё, что написано здесь явно, сильнее профиля. Ключ IndexNow сюда не пишется: он свой у каждого сайта."),
        "profile": detected["profile"],
        "site": detected["site"],
        # `pages` — путь к страницам. Раздел настроек текстовых проверок
        # называется `content`, и путать их нельзя: одно имя на две разные
        # вещи роняло проверку с непонятной ошибкой.
        "pages": detected["content"],
    }
    if detected.get("dataset"):
        config["dataset"] = detected["dataset"]
    config["checks"] = {}
    config["content"] = {}
    config["aeo"] = {}

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path, True


GITIGNORE_LINES = (".indexgap-manifest.json", "indexgap-check.html", "indexgap-check.json",
                   "indexgap-doctor.html", "indexgap-doctor.json", "indexgap-portfolio.html",
                   "indexgap-portfolio.json", "indexgap-cite.json",
                   # Наряды перезаписываются каждым прогоном: держать их
                   # в истории — значит хранить устаревшие задания.
                   "indexgap-briefs/")


def update_gitignore(root: str) -> bool:
    """Служебные файлы не должны уезжать в сборку статического генератора."""
    path = os.path.join(root, ".gitignore")
    existing = ""
    if os.path.isfile(path):
        try:
            existing, _ = read_text(path)
        except SourceError:
            existing = ""
    if GITIGNORE_MARK in existing:
        return False
    missing = [line for line in GITIGNORE_LINES if line not in existing]
    if not missing:
        return False
    block = "\n" + GITIGNORE_MARK + "\n" + "\n".join(missing) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(block)
    return True


def update_agents_md(root: str, detected: dict, create: bool = False) -> str:
    """
    Codex читает `AGENTS.md`, а не `.claude/skills`. Если файл в проекте есть,
    дописываем в него короткий блок с маркерами — чтобы обновлять и удалять
    его можно было машинально, не задевая остальное.
    """
    path = os.path.join(root, "AGENTS.md")
    if not os.path.isfile(path) and not create:
        return ""
    block = (
        tr("{a0}\n## SEO-конвейер\n\nВ проекте установлен indexgap. Профиль контента — `{a1}`, страницы в `{a2}`.\n\nПеред публикацией сгенерированных страниц:\n\n```bash\nindexgap check {a3} --site {a4}{a5}\n```\n\nПолные инструкции — в `.claude/skills/indexgap-*/SKILL.md`: разбор семантики (`indexgap-plan`), проверка перед публикацией (`indexgap-review`), sitemap и IndexNow (`indexgap-publish`), несколько сайтов сразу (`indexgap-portfolio`).\n{a6}", a0=AGENTS_START, a1=detected['profile'], a2=detected['content'], a3=detected['content'], a4=detected['site'] or '<адрес сайта>', a5=' --dataset ' + detected['dataset'] if detected.get('dataset') else '', a6=AGENTS_END)
    )
    existing = ""
    if os.path.isfile(path):
        try:
            existing, _ = read_text(path)
        except SourceError:
            existing = ""
    if AGENTS_START in existing and AGENTS_END in existing:
        head, _, rest = existing.partition(AGENTS_START)
        _, _, tail = rest.partition(AGENTS_END)
        updated = head + block + tail
    else:
        updated = (existing.rstrip() + "\n\n" + block + "\n") if existing else block + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(updated)
    return path


def new_indexnow_key() -> str:
    """
    Новый ключ для ЭТОГО проекта.

    Ключ привязан к домену файлом в корне сайта. Взятый у соседнего проекта
    он гарантированно даёт 403, поэтому переносить его нельзя — только выдать
    новый. Секретом он не является: файл лежит на сайте открыто.
    """
    return secrets.token_hex(16)


def run(root: str, site: str = "", content: str = "", profile: str = "",
        dataset: str = "", force: bool = False, agents: bool = False) -> dict:
    """Собирает всё вместе. Возвращает отчёт о том, что сделано и что понято."""
    root = os.path.abspath(root or ".")
    if not os.path.isdir(root):
        raise SourceError(tr("Каталога {a0} нет.", a0=root))

    detected_content = content or detect_content_dir(root)
    detected_dataset = dataset or detect_dataset(root)
    detected_profile, why = ((profile, tr("задан флагом")) if profile
                             else detect_profile(root, detected_content, detected_dataset))
    detected = {
        "content": detected_content or "./content",
        "site": site or detect_site(root, detected_content),
        "dataset": detected_dataset,
        "profile": detected_profile,
        "profile_why": why,
        "content_guessed": not content,
        "site_guessed": not site,
    }

    skills = install_skills(root)
    config_path, config_written = write_config(root, detected, force)
    gitignore = update_gitignore(root)
    agents_path = update_agents_md(root, detected, create=agents)

    return {
        "root": root,
        "detected": detected,
        "skills": skills,
        "config": config_path,
        "config_written": config_written,
        "gitignore": gitignore,
        "agents": agents_path,
    }
