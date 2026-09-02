"""Пути проекта.

Все приложения квеста ищут данные относительно корня репозитория, чтобы
ведущий мог просто скопировать папку в виртуальную машину и запустить скрипты
из любого каталога.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Корень репозитория (папка, в которой лежат run_*.py).
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
CANNED_DIR = DATA_DIR / "canned"
SCENARIO_DIR = DATA_DIR / "scenario"

CONFIG_FILE = CONFIG_DIR / "config.json"
CONFIG_EXAMPLE = CONFIG_DIR / "config.example.json"

COMPLEX_FILE = DATA_DIR / "complex.json"
STAGES_FILE = DATA_DIR / "stages.json"
PERSONA_FILE = DATA_DIR / "persona.json"


def expand(path: str | os.PathLike) -> Path:
    """Раскрывает ``~`` и переменные окружения в пути."""
    return Path(os.path.expandvars(os.path.expanduser(str(path))))


def resolve(path: str | os.PathLike) -> Path:
    """Абсолютный путь: относительные пути считаются от корня проекта."""
    p = expand(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def ensure_dir(path: str | os.PathLike) -> Path:
    """Создаёт каталог (со всеми родителями) и возвращает его путь."""
    p = resolve(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
