"""
Русский текст самого argparse: «positional arguments», «show this help message
and exit», «error: the following arguments are required».

Пакет пишет по-русски, а каркас справки и ошибки разбора аргументов оставались
английскими — полупереведённый вывод выглядит сломанным. argparse берёт строки
через gettext в момент вызова (`argparse._`, `argparse.ngettext`), поэтому
подмена этих двух имён переводит и справку, и ошибки. Строки разных версий
Python различаются («optional arguments» до 3.10, «options» после) — словарь
держит обе. Чего в словаре нет, остаётся как было.
"""

import argparse

from . import i18n

RU = {
    "usage: ": "использование: ",
    "positional arguments": "позиционные аргументы",
    "optional arguments": "параметры",
    "options": "параметры",
    "subcommands": "команды",
    "%(heading)s:": "%(heading)s:",
    " (default: %(default)s)": " (по умолчанию: %(default)s)",
    "show this help message and exit": "показать эту справку и выйти",
    "show program's version number and exit": "показать версию и выйти",
    "%(prog)s: error: %(message)s\n": "%(prog)s: ошибка: %(message)s\n",
    "%(prog)s: warning: %(message)s\n": "%(prog)s: предупреждение: %(message)s\n",
    "the following arguments are required: %s": "не хватает обязательных аргументов: %s",
    "unrecognized arguments: %s": "неизвестные аргументы: %s",
    "invalid choice: %(value)r (choose from %(choices)s)":
        "недопустимое значение: %(value)r (можно: %(choices)s)",
    "argument %(argument_name)s: %(message)s": "аргумент %(argument_name)s: %(message)s",
    "invalid %(type)s value: %(value)r": "недопустимое значение типа %(type)s: %(value)r",
    "expected one argument": "нужно одно значение",
    "expected at least one argument": "нужно хотя бы одно значение",
    "expected at most one argument": "можно не больше одного значения",
    "ambiguous option: %(option)s could match %(matches)s":
        "неоднозначный параметр: %(option)s подходит к %(matches)s",
    "not allowed with argument %s": "нельзя вместе с аргументом %s",
    "one of the arguments %s is required": "нужен один из аргументов: %s",
    "ignored explicit argument %r": "лишнее значение %r проигнорировано",
    "can't open '%(filename)s': %(error)s": "не открывается «%(filename)s»: %(error)s",
    "unknown parser %(parser_name)r (choices: %(choices)s)":
        "неизвестная команда %(parser_name)r (можно: %(choices)s)",
}
RU_PLURAL = {
    ("expected %s argument", "expected %s arguments"): ("нужно значений: %s", "нужно значений: %s"),
}

_installed = False


def install() -> None:
    """Один раз за процесс; язык проверяется при каждом вызове, а не при установке."""
    global _installed
    if _installed:
        return
    original, original_n = argparse._, argparse.ngettext

    def gettext(message):
        if i18n.get_lang() == "ru":
            return RU.get(message, original(message))
        return original(message)

    def ngettext(singular, plural, n):
        if i18n.get_lang() == "ru" and (singular, plural) in RU_PLURAL:
            one, many = RU_PLURAL[(singular, plural)]
            return one if n == 1 else many
        return original_n(singular, plural, n)

    argparse._ = gettext
    argparse.ngettext = ngettext
    _installed = True
