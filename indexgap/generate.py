# -*- coding: utf-8 -*-
"""
Шаг «генерация»: подготовка заданий, а не сам текст.

Текст пишет агент — Claude Code или Codex, у которого уже есть подписка.
Этот модуль делает вокруг него то, что агенту делать не нужно и в чём он ошибается
на сотнях строк: проверяет датасет, отсекает синонимичные ключи ДО генерации
и раскладывает заготовки с готовым брифом внутри.

Дедупликация на входе важнее фильтра на выходе: два ключа-синонима гарантированно
дадут две почти одинаковые страницы, и дешевле не создавать их вовсе,
чем потом склеивать canonical.

Что переделано после аудита:

  * **синонимы.** Жаккар по сырым токенам ловил 3 пары из 10 обязательных
    и ложно схлопывал 4 из 10 нужных: «виза в сингапур» и «сингапур виза»
    расходились из-за предлога, а два длинных ключа, отличающихся одним словом,
    схлопывались автоматически — при шести токенах отношение 6/7 само по себе
    выше порога 0,85. Теперь сравниваются нормализованные значимые основы,
    и синонимом считается только полное совпадение смыслового состава;
  * **отбраковка по заполненности** больше не выкидывает весь датасет из-за
    одной пустой необязательной колонки — она называет колонку и предупреждает;
  * **--pattern** не может вывести файлы за пределы --out-dir.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import unicodedata
from collections import Counter, defaultdict

from .core import read_text, SourceError
from .i18n import N_, tr

CONFIG = {
    "min_fields_filled": 0.0,     # 0 — не отбраковывать, только предупреждать
    "slug_max": 80,
}

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e",
    "ю": "yu", "я": "ya",
}

# Служебные слова, которые не меняют интент запроса.
STOPWORDS = {
    "в", "во", "на", "по", "из", "с", "со", "до", "от", "за", "к", "ко", "о",
    "об", "обо", "при", "для", "и", "или", "а", "но", "же", "ли", "не", "ни",
    "то", "это", "как", "что", "the", "a", "an", "of", "in", "on", "at", "to",
    "for", "by", "with", "and", "or", "is", "are",
}

# Окончания, снятие которых сводит словоформы одного слова к общей основе.
# Это не морфология, а грубая нормализация — её достаточно, чтобы «квартир»,
# «квартиры» и «квартире» стали одним токеном, и мало, чтобы склеить разные слова.
_ENDINGS = ("ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими", "ых", "их",
            "ах", "ях", "ов", "ев", "ий", "ый", "ой", "ая", "яя", "ое", "ее",
            "ые", "ие", "ем", "ом", "ым", "им", "ей", "ям", "ам", "ум", "ую",
            "юю", "ы", "и", "а", "я", "е", "у", "ю", "о", "ь", "й", "s")

# Обрезать основу по длине нельзя: «город0» и «город1» превратились бы в одно
# слово, и датасет из пяти тысяч ключей схлопнулся бы в одну строку.
# Поэтому вместо обрезки — повторное снятие окончаний.
#
# Третьего прохода по «ог/ег/ок» здесь намеренно нет, хотя он и сводил бы
# «недорого» с «недорогие». Ценой было бы схлопывание настоящих слов:
# «молоток» → «молот», «каталог» → «катал», «звонок» → «звон». Пропустить
# пару синонимов дешевле, чем молча удалить строку каталога.


def _stem(token: str) -> str:
    token = token.lower()
    if len(token) <= 4:
        return token
    for _ in range(2):
        changed = False
        for ending in _ENDINGS:
            if token.endswith(ending) and len(token) - len(ending) >= 4:
                token = token[:-len(ending)]
                changed = True
                break
        if not changed:
            break
    return token


def intent_key(value: str) -> frozenset:
    """
    Смысловой состав запроса: значимые слова, приведённые к основе.

    «виза в сингапур», «сингапур виза» и «визы в сингапуре» дают один и тот же
    набор — это один интент и одна страница. «виза в сингапур для россиян»
    даёт другой: там есть слово, которого нет в первом.
    """
    tokens = re.findall(r"\w+", (value or "").lower(), flags=re.UNICODE)
    # Цифра — значимое слово. Фильтр «длиннее одного символа» отбрасывал её,
    # и «1 комнатная квартира» становилась тем же интентом, что и
    # «5 комнатная квартира»: на каталоге недвижимости удалялось 80% строк.
    return frozenset(_stem(t) for t in tokens
                     if t not in STOPWORDS and (len(t) > 1 or t.isdigit()))


def slugify(value: str, max_len: int = None) -> str:
    """
    Латинский slug. Кириллица транслитерируется, диакритика снимается.

    Длинный ключ обрезается по границе слова, и к обрезанному добавляется
    короткий хеш исходной строки: иначе весь длинный хвост — основной материал
    programmatic SEO — схлопывался бы в один и тот же slug.

    Для письменностей, которые в латиницу не переводятся (китайская, японская,
    арабская, тайская), результат оказался бы пустым — там возвращается
    устойчивый короткий хеш.
    """
    max_len = max_len or CONFIG["slug_max"]
    original = (value or "").strip()
    text = original.lower()
    text = "".join(_TRANSLIT.get(ch, ch) for ch in text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    if not text:
        if not original:
            return ""
        digest = hashlib.blake2b(original.encode("utf-8"), digest_size=5).hexdigest()
        return f"p-{digest}"
    if len(text) > max_len:
        digest = hashlib.blake2b(original.encode("utf-8"), digest_size=3).hexdigest()
        cut = text[:max_len - len(digest) - 1]
        cut = cut.rsplit("-", 1)[0] if "-" in cut else cut
        text = f"{cut.strip('-')}-{digest}"
    return text


# ── чтение датасета ───────────────────────────────────────────────────────────

# csv не умеет «без разделителя», а файлу с одной колонкой любой разделитель
# только вредит. На эту роль берётся управляющий символ, которого в тексте нет.
# NUL подошёл бы лучше всех, но CPython до 3.11 принимает его за «разделитель
# не задан» и роняет чтение целиком.
_SINGLE_COLUMN_SEPARATORS = "\x1f\x1e\x01\x02\x03\x04\x05\x06\x07"


def _single_column_delimiter(text: str) -> str:
    """Управляющий символ, которого нет в тексте, — на роль разделителя."""
    for char in _SINGLE_COLUMN_SEPARATORS:
        if char not in text:
            return char
    return _SINGLE_COLUMN_SEPARATORS[0]


def read_dataset(path: str) -> dict:
    """
    Читает семантику: CSV или XLSX.

    Кодировка определяется, а не предполагается: русский Excel сохраняет CSV
    в cp1251 с точкой с запятой, и раньше такой файл — самый частый вход —
    ронял команду двенадцатью строками стека.
    """
    from . import sources

    if not os.path.exists(path):
        raise SourceError(tr("Файл {a0} не найден. Проверь путь и имя.", a0=path))
    if os.path.isdir(path):
        raise SourceError(tr("{a0} — это каталог, а нужен файл с ключами.", a0=path))

    with open(path, "rb") as fh:
        signature = fh.read(2)
    if signature == b"PK":
        # Ahrefs, Semrush и Keys.so по умолчанию отдают xlsx. Раньше пакет
        # отправлял человека пересохранять файл вручную — и на этом
        # заканчивался путь того, кто не программирует.
        rows_raw = sources.read_table(path)[0]
        if not rows_raw:
            raise SourceError(tr("{a0}: в книге нет данных.", a0=path))
        fields = [str(c).strip() for c in rows_raw[0]]
        rows = []
        for raw in rows_raw[1:]:
            row = {fields[i]: str(raw[i]).strip()
                   for i in range(min(len(fields), len(raw)))}
            if any(v for v in row.values()):
                rows.append(row)
        return {"rows": rows, "fields": fields, "encoding": "xlsx",
                "delimiter": "", "problems": []}

    text, encoding = read_text(path)
    first_line = text.splitlines()[0] if text.strip() else ""
    single_column = not any(ch in first_line for ch in ",;\t|")
    if single_column:
        # Один столбец: запятая внутри значения — часть ключа, а не разделитель.
        # Раньше «аренда, дома москва» превращалось в «аренда».
        class _Single(csv.excel):
            delimiter = _single_column_delimiter(text)
        dialect = _Single
    else:
        sample = text[:8192]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text, newline=""), dialect=dialect,
                            restkey="__extra__", restval="")
    rows, problems = [], []
    fields = [f.strip() for f in (reader.fieldnames or [])]

    duplicates = [name for name, count in Counter(fields).items() if count > 1 and name]
    if duplicates:
        problems.append(
            tr("в шапке повторяются колонки: ") + ", ".join(sorted(duplicates))
            + tr(" — останется только последняя из одноимённых"))
    if not fields or fields == [""]:
        raise SourceError(tr("{a0}: не удалось прочитать шапку — файл пустой?", a0=path))

    ragged = []
    for number, raw in enumerate(reader, start=2):
        row = {}
        for key, value in raw.items():
            if key == "__extra__":
                ragged.append(number)
                continue
            if key is None:
                continue
            row[str(key).strip()] = (value or "").strip() if isinstance(value, str) else value
        if any((v or "").strip() for v in row.values()):
            rows.append(row)
    if ragged:
        shown = ", ".join(str(n) for n in ragged[:5])
        problems.append(
            tr("в {a0} строк(ах) колонок больше, чем в шапке — лишнее отброшено (строки {a1}{a2})", a0=len(ragged), a1=shown, a2=' и далее' if len(ragged) > 5 else ''))
    return {"rows": rows, "fields": fields, "encoding": encoding,
            "delimiter": "" if single_column else getattr(dialect, "delimiter", ","),
            "problems": problems}


# ── аудит семантики ───────────────────────────────────────────────────────────

def audit_dataset(rows: list, fields: list, keyword_field: str,
                  cfg: dict = None) -> dict:
    """
    Проверяет семантику до генерации. Возвращает строки, годные к генерации,
    и объяснённые отбраковки.
    """
    cfg = {**CONFIG, **(cfg or {})}
    variables = [f for f in fields if f != keyword_field]

    exact = defaultdict(list)
    for i, row in enumerate(rows):
        key = (row.get(keyword_field) or "").strip().lower()
        exact[key].append(i)

    rejected, warnings = [], []
    seen_slugs = {}
    kept = []

    for key, idxs in sorted(exact.items()):
        if not key:
            for i in idxs:
                rejected.append({"row": i + 2, "reason": tr("пустой ключ"), "keyword": ""})
            continue
        if len(idxs) > 1:
            for i in idxs[1:]:
                rejected.append({"row": i + 2, "reason": tr("точный дубль ключа"), "keyword": key})
        kept.append(idxs[0])

    empty_columns = Counter()
    survivors = []
    for i in sorted(kept):
        row = rows[i]
        key = (row.get(keyword_field) or "").strip()

        for f in variables:
            if not (row.get(f) or "").strip():
                empty_columns[f] += 1

        filled = sum(1 for f in variables if (row.get(f) or "").strip())
        share = filled / len(variables) if variables else 1.0
        if variables and cfg["min_fields_filled"] and share < cfg["min_fields_filled"]:
            rejected.append({"row": i + 2, "keyword": key,
                             "reason": tr("заполнено {a0} из {a1} полей", a0=filled, a1=len(variables))})
            continue

        if not re.search(r"\w", key, flags=re.UNICODE):
            rejected.append({"row": i + 2, "keyword": key,
                             "reason": tr("ключ не содержит ни одной буквы или цифры")})
            continue

        slug = slugify(key)
        if slug in seen_slugs:
            rejected.append({"row": i + 2, "keyword": key,
                             "reason": tr("slug совпадает с «{a0}»", a0=seen_slugs[slug])})
            continue
        seen_slugs[slug] = key
        survivors.append((i, key, slug, row))

    for column, count in sorted(empty_columns.items()):
        if count == len(kept) and kept:
            warnings.append(tr("колонка «{a0}» пуста во всех строках — её можно удалить из файла", a0=column))
        elif count > len(kept) * 0.5 and kept:
            warnings.append(tr("колонка «{a0}» пуста в {a1} строках из {a2}", a0=column, a1=count, a2=len(kept)))

    # Синонимичные интенты: одинаковый смысловой состав ключа.
    groups = defaultdict(list)
    for pos, (i, key, slug, row) in enumerate(survivors):
        groups[intent_key(key)].append(pos)

    near, drop = [], set()
    for intent, positions in sorted(groups.items(), key=lambda kv: survivors[kv[1][0]][1]):
        if len(positions) < 2 or not intent:
            continue
        keeper = positions[0]
        for pos in positions[1:]:
            near.append((survivors[keeper][1], survivors[pos][1], 1.0))
            drop.add(pos)

    final = [s for pos, s in enumerate(survivors) if pos not in drop]
    for pos, (i, key, slug, row) in enumerate(survivors):
        if pos in drop:
            rejected.append({"row": i + 2, "keyword": key,
                             "reason": tr("тот же интент, что и у другой строки")})

    return {
        "keep": final,
        "rejected": sorted(rejected, key=lambda r: r["row"]),
        "near_synonyms": near,
        "warnings": warnings,
        "variables": variables,
        "total": len(rows),
    }


# ── заготовки ─────────────────────────────────────────────────────────────────

# Бриф намеренно не описывает структуру страницы: она у каждого бизнеса своя.
# Каталог квартир, справочник по визам, сравнение тарифов и карточка станка
# требуют разных разделов, и навязывать им общий скелет — верный способ
# получить те самые шаблонные швы, которые пакет потом ловит.
# Свой шаблон подставляется через --brief.
DEFAULT_BRIEF = N_("---\ntitle: \"\"\ndescription: \"\"\nkeyword: {keyword_yaml}\nstatus: draft\n---\n\n<!-- БРИФ ДЛЯ АГЕНТА. Удали этот блок, когда страница написана.\n\nКлюч: {keyword}\nДанные строки:\n{variables}\n\nТребования:\n  * title {title_min}–{title_max} символов, содержит ключ,\n    не совпадает с другими страницами;\n  * description {desc_min}–{desc_max} символов, без повтора title;\n  * не меньше {min_words} слов осмысленного текста;\n  * первый абзац — прямой ответ на запрос, 40–320 символов, без разгона\n    вроде «в этой статье мы рассмотрим»: именно его цитируют ИИ-поиск\n    и блок быстрых ответов;\n  * структура — под данные строки и под то, что человеку нужно решить\n    на этой странице. НЕ переноси одни и те же разделы со страницы на страницу:\n    одинаковый скелет заголовков читается как штамповка;\n  * минимум {min_links} ссылки на соседние страницы этого раздела,\n    анкоры описательные — иначе страница останется сиротой;\n  * ничего не выдумывать. Каждое число должно быть в данных строки.\n    Если данных нет, раздел не пишем.\n-->\n")

_BAD_SEGMENT = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


def _path_segment(value: str) -> str:
    """
    Значение колонки, пригодное как часть пути. Готовый slug из датасета
    остаётся как есть — раньше он повторно прогонялся через slugify,
    и `avto/kran` превращался в `avto-kran`, а иероглифический — в хеш.
    """
    value = _BAD_SEGMENT.sub("-", str(value or "")).strip().strip(".")
    value = re.sub(r"\.\.+", ".", value)
    return value


def _yaml_value(value: str) -> str:
    """Значение фронтматтера, которое не сломает YAML любого генератора."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _brief_value(value: str) -> str:
    """Значение внутри HTML-комментария: `-->` в данных закрывает комментарий."""
    return re.sub(r"\s+", " ", str(value or "")).replace("-->", "-- >").strip()


def check_pattern(pattern: str, fields: list) -> None:
    """Проверяет шаблон пути до записи, а не на первой же строке."""
    names = set()
    try:
        for literal, name, spec, conv in __import__("string").Formatter().parse(pattern):
            if name:
                names.add(name.split(".")[0].split("[")[0])
    except ValueError as exc:
        raise SourceError(
            tr("--pattern «{a0}»: {a1}. Фигурные скобки должны быть парными, а внутри них — имя колонки.", a0=pattern, a1=exc))
    known = set(fields) | {"slug", "keyword"}
    unknown = sorted(names - known)
    if unknown:
        raise SourceError(
            tr("--pattern «{a0}»: колонок ", a0=pattern) + ", ".join(unknown) + tr(" в датасете нет.\n    Доступны: ") + ", ".join(sorted(known)))


def write_tasks(audit: dict, out_dir: str, keyword_field: str,
                path_pattern: str = "{slug}/index.md",
                brief: str = "",
                min_words: int = 350, min_links: int = 3,
                title_min: int = 20, title_max: int = 65,
                desc_min: int = 70, desc_max: int = 165) -> dict:
    """Раскладывает заготовки с брифом. Существующие файлы не трогает."""
    # Бриф переводится здесь, а не при импорте: язык известен только к моменту
    # запуска команды. Раньше константа с `tr()` на уровне модуля замерзала
    # на языке, определённом до разбора `--lang`.
    brief = brief or tr(DEFAULT_BRIEF)
    written, skipped, failed = [], [], []
    root = os.path.abspath(out_dir)
    for i, key, slug, row in audit["keep"]:
        fields = {k: _path_segment(v) for k, v in row.items()}
        # Собственная колонка `slug` в датасете важнее нашей: человек завёл её
        # ровно затем, чтобы задать адреса самому. Раньше она молча
        # перезаписывалась, и продуманная структура URL исчезала без следа.
        if not (row.get("slug") or "").strip():
            fields["slug"] = slug
        if not (row.get("keyword") or "").strip() or keyword_field != "keyword":
            fields["keyword"] = slug
        try:
            rel = path_pattern.format(**fields)
        except (KeyError, IndexError, ValueError) as exc:
            failed.append({"keyword": key, "reason": tr("шаблон пути: {a0}", a0=exc)})
            continue
        # Пустая колонка в шаблоне даёт `/файл.md` или `a//b.md`. Раньше ведущий
        # слеш делал путь абсолютным, каталог назначения отбрасывался, и файлы
        # уезжали в корень файловой системы — при бодром «создано N в out».
        if not rel.strip() or rel.startswith(("/", "\\")) or "//" in rel.replace("\\", "/") \
                or rel.endswith(("/", "\\")):
            failed.append({"keyword": key,
                           "reason": tr("в шаблоне пути пустое значение колонки — заполни её или убери из --pattern")})
            continue
        path = os.path.abspath(os.path.join(root, rel))
        # Пустое значение колонки или `..` в шаблоне раньше уводили запись
        # за пределы каталога — вплоть до корня файловой системы.
        if os.path.commonpath([root, path]) != root:
            failed.append({"keyword": key,
                           "reason": tr("шаблон уводит файл за пределы --out-dir")})
            continue
        if os.path.exists(path):
            skipped.append(path)
            continue
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        variables = "\n".join(f"  {k}: {_brief_value(v)}" for k, v in row.items()
                              if k != keyword_field and (v or "").strip())
        try:
            body = brief.format(
                keyword=_brief_value(key).replace('"', "'"),
                keyword_yaml=_yaml_value(key),
                variables=variables or tr("  (нет)"),
                min_words=min_words, min_links=min_links,
                title_min=title_min, title_max=title_max,
                desc_min=desc_min, desc_max=desc_max)
        except (KeyError, IndexError, ValueError) as exc:
            raise SourceError(
                tr("--brief: в шаблоне есть подстановка {a0}, которой пакет не знает.\n    Доступны: keyword, keyword_yaml, variables, min_words, min_links, title_min, title_max, desc_min, desc_max.\n    Если нужны фигурные скобки как текст — удвой их: {{{{ и }}}}.", a0=exc))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        written.append(path)
    return {"written": written, "skipped": skipped, "failed": failed}
