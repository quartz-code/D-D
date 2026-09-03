#!/usr/bin/env python3
"""Пусковое окно квеста — подготовка партии и выбор возможностей.

Тот же результат даёт `python3 -m questkit.launcher`.
Без графики: `python3 run_launcher.py --текст`.
"""

import sys

from questkit.launcher import main

if __name__ == "__main__":
    sys.exit(main())
