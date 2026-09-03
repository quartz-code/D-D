#!/usr/bin/env python3
"""Пульт ведущего — запускающий скрипт.

Тот же результат даёт `python3 -m questkit.master`.
"""

import sys

from questkit.master import main

if __name__ == "__main__":
    sys.exit(main())
