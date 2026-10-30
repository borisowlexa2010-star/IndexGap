# -*- coding: utf-8 -*-
"""
Английский словарь.

Разложен по файлам так же, как исходники: правя сообщение в `checks.py`,
переводчик открывает `locale/en/checks.py`, а не ищет строку среди семисот.
"""

from . import (checks, cite, cli, content, core, diff, doctor, hreflang, repair, report,
               signals, summary)

MESSAGES = {}
for _part in (core, checks, report, doctor, content, cli, hreflang, cite, repair, summary, signals,
              diff):
    MESSAGES.update(_part.MESSAGES)
del _part
