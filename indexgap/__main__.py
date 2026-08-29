# -*- coding: utf-8 -*-
"""Точка входа для `python -m indexgap`. Установленный пакет даёт команду `indexgap`."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
