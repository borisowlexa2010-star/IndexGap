# -*- coding: utf-8 -*-
"""
Язык вывода. / Output language.

Пакет писался по-русски, и русский остаётся исходным языком сообщений:
ключ перевода — сама русская строка. Это значит, что русский вывод ничего
не стоит и не может «отстать» от кода, а английский — это словарь поверх него.
Пропущенная строка не ломает команду: она выводится по-русски, а тест
`test_i18n` показывает, каких именно строк не хватает.

Язык выбирается в таком порядке:

  1. `--lang en` / `--lang ru` — явный флаг;
  2. `INDEXGAP_LANG`;
  3. `LC_ALL`, `LC_MESSAGES`, `LANG` — то, что уже настроено в системе;
  4. английский.

Четвёртый пункт — решение, а не умолчание по невнимательности: пакет лежит
на GitHub, и человек, у которого локаль не выставлена, скорее всего читает
по-английски.
"""

from __future__ import annotations

import os

LANGS = ("en", "ru")
DEFAULT = "en"

_lang = None
_catalog = {}
_missing = set()


def _detect() -> str:
    for name in ("INDEXGAP_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = (os.environ.get(name) or "").strip().lower()
        if not value:
            continue
        code = value.split(".")[0].split("_")[0]
        if code in LANGS:
            return code
        if code in ("be", "uk", "kk", "ky", "uz", "tg"):
            # Постсоветские локали: русский вывод им ближе английского,
            # своих переводов пока нет — и это сказано честно, а не спрятано.
            return "ru"
        if code:
            return DEFAULT
    return DEFAULT


def set_lang(lang: str = None) -> str:
    """Задаёт язык вывода. Пустое значение — определить самому."""
    global _lang, _catalog
    code = (lang or "").strip().lower() or _detect()
    if code not in LANGS:
        code = DEFAULT
    _lang = code
    _catalog = {}
    if code != "ru":
        try:
            module = __import__(f"indexgap.locale.{code}", fromlist=["MESSAGES"])
            _catalog = getattr(module, "MESSAGES", {})
        except ImportError:
            _catalog = {}
    return code


def get_lang() -> str:
    if _lang is None:
        set_lang()
    return _lang


def missing() -> list:
    """Строки, для которых перевода не нашлось. Нужны тесту, а не человеку."""
    return sorted(_missing)


def t(text: str, **kwargs) -> str:
    """
    Переводит строку и подставляет значения.

    Шаблон именованный (`{count}`), а не позиционный: при переводе порядок
    слов меняется, и позиционные номера пришлось бы держать в голове.
    """
    if _lang is None:
        set_lang()
    out = text
    if _lang != "ru":
        found = _catalog.get(text)
        if found is None:
            _missing.add(text)
        else:
            out = found
    if kwargs:
        try:
            out = out.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            # Кривой шаблон в словаре не должен ронять команду: человеку
            # нужен отчёт, а не трейсбек из-за забытой фигурной скобки.
            try:
                out = text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                pass
    return out


# Короткое имя: этой функцией размечен весь вывод пакета.
#
# Именно `tr`, а не привычное по gettext `_`: в коде `_` уже занят под
# «значение мне не нужно» — `text, _ = read_text(path)`. Импорт `_` молча
# перекрывался локальной переменной, и первая же попытка перевести строку
# падала с «str object is not callable». Имя должно быть таким, чтобы
# столкнуться было нечем.
tr = t


def N_(text: str) -> str:
    """
    Пометка «перевести потом», ничего не делающая сейчас.

    Нужна для таблиц на уровне модуля: описания кодов, названия профилей,
    подписи источников. Их нельзя переводить в момент импорта — импорт
    случается раньше, чем разобран `--lang`, и `indexgap profiles --lang ru`
    печатал русский заголовок и английские названия профилей. Наполовину
    переведённый отчёт выглядит сломанным.

    Поэтому в таблице лежит русский ключ, помеченный `N_`, а `tr()` зовётся
    в момент печати. Пометка нужна, чтобы сборщик словаря видел эти строки:
    без неё они молча выпали бы из перевода.
    """
    return text
