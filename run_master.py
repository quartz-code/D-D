#!/usr/bin/env python3
"""Пульт ведущего — запускающий скрипт.

Тот же результат даёт `python3 -m entropy.master`.
"""

import sys

from entropy.master import main

if __name__ == "__main__":
    sys.exit(main())
