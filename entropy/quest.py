"""Константы квеста и подстановка их в данные.

Раньше код от внешней двери был вписан в пяти местах сразу: в сценарии
раскладки, в надписи на картинке, в шаблоне команды, в заготовке ответа и в
списке секретов разума. Поменять его для новой партии, ничего не забыв, было
почти невозможно — и квест ломался тихо.

Теперь значение задаётся один раз в ``data/quest.json``, а остальные файлы
ссылаются на него через ``{{код_двери}}``. Подстановка выполняется при чтении
данных, поэтому файлы на диске остаются с шаблонами.
"""

from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path
from typing import Any

from . import paths

#: Шаблон ссылки на константу: {{имя}}. Имена — русские или латинские.
PLACEHOLDER = re.compile(r"\{\{\s*([^\s{}]+)\s*\}\}")


class Constants:
    """Значения из ``data/quest.json`` и подстановка их в любые данные."""

    def __init__(self, path: str | os.PathLike):
        self.path: Path = paths.resolve(path)
        self.values: dict[str, str] = {}
        self.load()

    @classmethod
    def empty(cls) -> "Constants":
        """Набор без значений: подстановка ничего не меняет."""
        пустой = cls.__new__(cls)
        пустой.path = None
        пустой.values = {}
        return пустой

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            raise FileNotFoundError(f"файл констант квеста не найден: {self.path}")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{self.path}: ожидался объект JSON верхнего уровня")
        self.values = {k: str(v) for k, v in data.items() if not k.startswith("_")}
        return self.values

    def save(self) -> None:
        """Пишет значения обратно, сохраняя пояснение в начале файла."""
        if self.path is None:
            raise ValueError("этот набор констант не привязан к файлу")
        данные = json.loads(self.path.read_text(encoding="utf-8"))
        данные.update(self.values)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(данные, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    # ---------------------------------------------------------------- доступ
    def __getitem__(self, key: str) -> str:
        return self.values[key]

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def set(self, key: str, value: str) -> str:
        self.values[key] = str(value)
        self.save()
        return self.values[key]

    # ----------------------------------------------------------- подстановка
    def substitute(self, text: str) -> str:
        """Заменяет ``{{имя}}`` на значение. Неизвестные ссылки не трогает."""
        return PLACEHOLDER.sub(
            lambda m: self.values.get(m.group(1), m.group(0)), text
        )

    def render(self, value: Any) -> Any:
        """Рекурсивно подставляет константы в строки словаря/списка/строки."""
        if isinstance(value, str):
            return self.substitute(value)
        if isinstance(value, dict):
            return {k: self.render(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.render(v) for v in value]
        return value

    def missing(self, value: Any) -> set[str]:
        """Ссылки, которым не нашлось значения, — для проверки готовности."""
        найдено: set[str] = set()
        if isinstance(value, str):
            найдено.update(имя for имя in PLACEHOLDER.findall(value)
                           if имя not in self.values)
        elif isinstance(value, dict):
            for v in value.values():
                найдено |= self.missing(v)
        elif isinstance(value, list):
            for v in value:
                найдено |= self.missing(v)
        return найдено

    # ------------------------------------------------------------- генерация
    def randomize_door_code(self, digits: int = 4) -> str:
        """Выдаёт новый случайный код на партию и сохраняет его.

        Полезно, если игроки могли увидеть репозиторий: код в файлах остаётся
        шаблоном ``{{код_двери}}``, а настоящее значение появляется только в
        разложенных файлах конкретной партии.
        """
        код = "".join(random.choice("0123456789") for _ in range(digits))
        return self.set("код_двери", код)


def load(cfg: dict | None = None) -> Constants:
    """Константы по пути из конфигурации (или из data/quest.json)."""
    if cfg:
        return Constants(cfg["files"].get("quest", "data/quest.json"))
    return Constants(paths.DATA_DIR / "quest.json")


def default() -> Constants:
    """Константы по умолчанию для тех, кто не передал их явно.

    Подстановка должна работать всегда: если её забыть, шаблон вида
    ``{{код_двери}}`` уедет прямо в файлы, которые читают игроки.
    """
    try:
        return load()
    except (FileNotFoundError, ValueError):
        return Constants.empty()
