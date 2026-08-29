# -*- coding: utf-8 -*-
"""
Английский словарь.

Разложен по файлам так же, как исходники: правя сообщение в `checks.py`,
переводчик открывает `locale/en/checks.py`, а не ищет строку среди семисот.
"""

from . import checks, cli, content, core, doctor, report

MESSAGES = {}
for _part in (core, checks, report, doctor, content, cli):
    MESSAGES.update(_part.MESSAGES)
del _part
