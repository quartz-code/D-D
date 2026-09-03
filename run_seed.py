#!/usr/bin/env python3
"""Генератор файловой системы-головоломки — запускающий скрипт.

Тот же результат даёт `python3 -m questkit.seed`.
"""

import sys

from questkit.seed import main

if __name__ == "__main__":
    sys.exit(main())
