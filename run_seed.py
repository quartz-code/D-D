#!/usr/bin/env python3
"""Генератор файловой системы-головоломки — запускающий скрипт.

Тот же результат даёт `python3 -m entropy.seed`.
"""

import sys

from entropy.seed import main

if __name__ == "__main__":
    sys.exit(main())
