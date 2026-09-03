"""Язык интерфейса движка.

Надписи меню, справки и сообщений об ошибках хранятся не в коде, а в
каталогах ``data/i18n/<язык>.json``. Язык выбирается настройкой
``ui.language``: «ru», «en» или «auto» (по локали системы).

Содержимое квеста здесь ни при чём: оно живёт в пакете и написано на том
языке, на котором его сочинил ведущий.

Использование::

    from .i18n import t
    print(t("terminal.help.title"))
    print(t("chat.limit.left", осталось=5))

Если перевода нет, возвращается русский вариант, а если нет и его — сам ключ:
интерфейс не должен падать из-за отсутствующей строки.
"""

from __future__ import annotations

import json
import locale
import os
from pathlib import Path
from typing import Any

from . import paths

ЯЗЫК_ПО_УМОЛЧАНИЮ = "ru"
ДОСТУПНЫЕ = ("ru", "en")

_каталоги: dict[str, dict[str, str]] = {}
_язык = ЯЗЫК_ПО_УМОЛЧАНИЮ


def каталог(язык: str) -> dict[str, str]:
    """Читает и запоминает каталог переводов."""
    if язык not in _каталоги:
        путь = paths.DATA_DIR / "i18n" / f"{язык}.json"
        try:
            данные = json.loads(путь.read_text(encoding="utf-8"))
            _каталоги[язык] = {к: str(з) for к, з in данные.items() if not к.startswith("_")}
        except (OSError, json.JSONDecodeError):
            _каталоги[язык] = {}
    return _каталоги[язык]


def определить_по_системе() -> str:
    """Язык из окружения: LANG=en_US.UTF-8 → «en»."""
    метка = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES")
             or os.environ.get("LANG") or "")
    if not метка:
        try:
            метка = locale.getdefaultlocale()[0] or ""
        except (ValueError, TypeError):      # pragma: no cover — зависит от системы
            метка = ""
    метка = метка.lower()
    for язык in ДОСТУПНЫЕ:
        if метка.startswith(язык):
            return язык
    return ЯЗЫК_ПО_УМОЛЧАНИЮ


def установить(язык: str | None) -> str:
    """Выбирает язык интерфейса. «auto» — по локали системы."""
    global _язык
    выбор = (язык or ЯЗЫК_ПО_УМОЛЧАНИЮ).strip().lower()
    if выбор in ("auto", "авто", ""):
        выбор = определить_по_системе()
    _язык = выбор if выбор in ДОСТУПНЫЕ else ЯЗЫК_ПО_УМОЛЧАНИЮ
    return _язык


def текущий() -> str:
    return _язык


def init(cfg: dict | None = None) -> str:
    """Настраивает язык по конфигурации (вызывается при запуске приложений)."""
    return установить((cfg or {}).get("ui", {}).get("language"))


def t(ключ: str, **подстановки: Any) -> str:
    """Строка интерфейса по ключу.

    Порядок поиска: выбранный язык → русский → сам ключ. Подстановки
    выполняются по именам: ``t("chat.left", осталось=3)``.
    """
    строка = каталог(_язык).get(ключ)
    if строка is None:
        строка = каталог(ЯЗЫК_ПО_УМОЛЧАНИЮ).get(ключ, ключ)
    if подстановки:
        try:
            return строка.format(**подстановки)
        except (KeyError, IndexError, ValueError):
            return строка
    return строка


def есть(ключ: str, язык: str | None = None) -> bool:
    return ключ in каталог(язык or _язык)


def ключи(язык: str | None = None) -> set[str]:
    return set(каталог(язык or _язык))
