#!/usr/bin/env python3
"""Приложение-чат с искусственным разумом — запускающий скрипт.

Тот же результат даёт `python3 -m questkit.chat`.
"""

import sys

from questkit.chat import main

if __name__ == "__main__":
    sys.exit(main())
