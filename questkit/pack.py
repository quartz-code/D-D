"""Пакет содержимого: манифест квеста.

Движок ничего не знает о конкретной игре. Всё, что делает квест этим квестом —
название, язык, подпись собеседника, приглашение терминала, — задаётся в
``pack.json`` рядом с остальными файлами пакета.

Пустой шаблон лежит в ``templates/``, готовые квесты — в ``examples/``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import paths

#: Значения, если манифеста нет или в нём чего-то не хватает.
УМОЛЧАНИЯ: dict[str, Any] = {
    "name": "Безымянный квест",
    "language": "ru",
    "author": "",
    "description": "",
    "terminal": {
        "prompt": "терминал",
        "title": "ТЕРМИНАЛ",
        "greeting": "Терминал служебного доступа.",
    },
    "chat": {
        "title": "СВЯЗЬ",
        "speaker": "собеседник",
        "greeting": "Канал связи открыт.",
    },
}


def _слить(основа: dict, поверх: dict) -> dict:
    итог = dict(основа)
    for ключ, значение in поверх.items():
        if isinstance(значение, dict) and isinstance(итог.get(ключ), dict):
            итог[ключ] = _слить(итог[ключ], значение)
        else:
            итог[ключ] = значение
    return итог


class Манифест:
    """Описание пакета содержимого."""

    def __init__(self, path: str | os.PathLike | None = None):
        self.path: Path | None = paths.resolve(path) if path else None
        self.data: dict[str, Any] = dict(УМОЛЧАНИЯ)
        self.load()

    def load(self) -> dict[str, Any]:
        if self.path and self.path.exists():
            try:
                прочитанное = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                прочитанное = {}
            if isinstance(прочитанное, dict):
                чистое = {к: з for к, з in прочитанное.items() if not к.startswith("_")}
                self.data = _слить(УМОЛЧАНИЯ, чистое)
        return self.data

    # ------------------------------------------------------------------ доступ
    @property
    def name(self) -> str:
        return str(self.data.get("name") or УМОЛЧАНИЯ["name"])

    @property
    def language(self) -> str:
        return str(self.data.get("language") or "ru")

    @property
    def author(self) -> str:
        return str(self.data.get("author") or "")

    @property
    def description(self) -> str:
        return str(self.data.get("description") or "")

    def раздел(self, имя: str) -> dict[str, Any]:
        значение = self.data.get(имя)
        return dict(значение) if isinstance(значение, dict) else {}

    def надпись(self, раздел: str, ключ: str, запасная: str = "") -> str:
        """Надпись из манифеста с откатом к умолчанию движка."""
        значение = self.раздел(раздел).get(ключ)
        if значение:
            return str(значение)
        умолчание = УМОЛЧАНИЯ.get(раздел, {})
        return str(умолчание.get(ключ, запасная)) if isinstance(умолчание, dict) else запасная


def load(cfg: dict) -> Манифест:
    """Манифест активного пакета содержимого."""
    from . import config
    try:
        путь = config.data_file(cfg, "manifest")
    except Exception:
        путь = None
    return Манифест(путь)
