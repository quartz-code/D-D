#!/usr/bin/env python3
"""Приложение-чат с искусственным разумом — запускающий скрипт.

Тот же результат даёт `python3 -m entropy.chat`.
"""

import sys

from entropy.chat import main

if __name__ == "__main__":
    sys.exit(main())
