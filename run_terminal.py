#!/usr/bin/env python3
"""Терминал-приложение для игроков — запускающий скрипт.

Тот же результат даёт `python3 -m questkit.terminal`.
"""

import sys

from questkit.terminal import main

if __name__ == "__main__":
    sys.exit(main())
