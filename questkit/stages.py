"""Этапы квеста и контекстная справка (разделы 3 и 4 ТЗ).

Команда «помощь» в терминале показывает не весь список команд, а только те,
что относятся к текущему этапу. Этап переключается либо вручную ведущим
(``мастер этап <имя>``), либо автоматически — когда игроки добираются до
нужного файла или выполняют ключевую команду.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from . import paths, constants as constants_mod, schema, ui

#: Команды, чтение файла которыми считается «нашёл и прочитал».
READ_COMMANDS = (
    "cat", "less", "more", "head", "tail", "strings", "file", "od", "hexdump",
    "xxd", "nano", "vi", "vim", "view", "grep", "bat", "unzip", "gunzip", "tar",
    "base64", "mv", "cp", "chmod",
)
_READ_RE = re.compile(r"\b(" + "|".join(READ_COMMANDS) + r")\b")


class Stages:
    """Карта этапов из ``data/stages.json``."""

    def __init__(self, path: str | os.PathLike,
                 constants: "constants_mod.Constants | None" = None):
        self.path: Path = paths.resolve(path)
        self.constants = (constants if constants is not None
                          else constants_mod.для_файла(self.path))
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError(f"карта этапов не найдена: {self.path}")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        # Константы квеста подставляются при чтении: на диске остаются шаблоны.
        self.data = self.constants.render(data) if self.constants else data
        return self.data

    # -------------------------------------------------------------- справочная
    @property
    def order(self) -> list[str]:
        order = schema.поле(self.data, "порядок")
        return list(order) if order else list(self.stages)

    @property
    def stages(self) -> dict[str, Any]:
        return schema.поле(self.data, "этапы", {})

    @property
    def always(self) -> list[dict[str, str]]:
        return list(schema.поле(self.data, "всегда", []))

    def first(self) -> str:
        order = self.order
        return order[0] if order else ""

    def exists(self, name: str) -> bool:
        return name in self.stages

    def info(self, name: str) -> dict[str, Any]:
        return self.stages.get(name, {})

    def title(self, name: str) -> str:
        return str(schema.поле(self.info(name), "название", name))

    def next_in_order(self, name: str) -> str | None:
        order = self.order
        if name in order:
            index = order.index(name) + 1
            if index < len(order):
                return order[index]
        return None

    # ---------------------------------------------------------------- справка
    def help_text(self, name: str, *, gm: bool = False) -> str:
        """Контекстный список команд текущего этапа (раздел 3 ТЗ)."""
        info = self.info(name)
        lines: list[str] = []
        описание = schema.поле(info, "описание")
        if описание:
            lines.append(описание)
            lines.append("")
        commands = schema.поле(info, "команды", [])
        if commands:
            lines.append("НА ЭТОМ УЧАСТКЕ ДОСТУПНО:")
            width = max((len(str(schema.поле(c, "команда", ""))) for c in commands), default=0)
            for item in commands:
                имя = str(schema.поле(item, "команда", ""))
                lines.append(f"  {имя.ljust(width)}  — {schema.поле(item, 'описание', '')}")
        else:
            lines.append("НА ЭТОМ УЧАСТКЕ ОТДЕЛЬНЫХ КОМАНД НЕ ЗАРЕГИСТРИРОВАНО.")
        always = self.always
        if always:
            lines.append("")
            lines.append("ВСЕГДА ДОСТУПНО:")
            width = max((len(str(schema.поле(c, "команда", ""))) for c in always), default=0)
            for item in always:
                имя = str(schema.поле(item, "команда", ""))
                lines.append(f"  {имя.ljust(width)}  — {schema.поле(item, 'описание', '')}")
        заметка = schema.поле(info, "подсказка_мастеру")
        if gm and заметка:
            lines.append("")
            lines.append(f"[мастеру] {заметка}")
        return ui.box(f"СПРАВКА · {self.title(name)}", lines, "голубой")

    def known_commands(self, name: str) -> list[str]:
        """Плоский список команд этапа — для автодополнения."""
        items = list(schema.поле(self.info(name), "команды", [])) + self.always
        имена = [str(schema.поле(item, "команда", "")) for item in items]
        return [и.split()[0] for и in имена if и]

    # ------------------------------------------------------- сценарные команды
    def scripted(self, name: str, command: str) -> dict[str, Any] | None:
        """Ищет заготовленный ответ для команды на этом этапе."""
        text = command.strip()
        for entry in schema.поле(self.info(name), "сценарные_команды", []):
            pattern = schema.поле(entry, "шаблон")
            if pattern and re.search(pattern, text, re.IGNORECASE):
                return entry
        return None

    def canned_text(self, entry: dict[str, Any], canned_dir: str | os.PathLike) -> str:
        """Читает заготовленный вывод. ``текст`` в JSON важнее, чем ``файл``."""
        текст = schema.поле(entry, "текст")
        if текст:
            return self._подставить(str(текст))
        name = schema.поле(entry, "файл")
        if not name:
            return ""
        path = paths.resolve(canned_dir) / name
        if not path.exists():
            return f"[нет файла заготовки: {path}]"
        return self._подставить(path.read_text(encoding="utf-8").rstrip("\n"))

    def _подставить(self, text: str) -> str:
        return self.constants.substitute(text) if self.constants else text

    # ------------------------------------------------------------- автопереход
    def check_transition(
        self,
        name: str,
        command: str,
        *,
        cwd: str | os.PathLike | None = None,
        success: bool = True,
    ) -> str | None:
        """Определяет, пора ли сменить этап после выполненной команды.

        Возвращает имя следующего этапа или ``None``.
        """
        if not success:
            return None
        rule = schema.поле(self.info(name), "переход") or {}
        target = schema.поле(rule, "следующий")
        if not target:
            return None
        text = command.strip()

        for pattern in schema.поле(rule, "при_команде", []):
            if pattern and re.search(pattern, text, re.IGNORECASE):
                return target

        files = schema.поле(rule, "при_чтении_файла", [])
        if files and _READ_RE.search(text):
            for filename in files:
                base = Path(filename).name
                if base and base.lower() in text.lower():
                    return target
        return None

    def transition_on_event(self, name: str, event: dict[str, Any]) -> str | None:
        """Переход по подтверждённому событию комплекса (``при_событии``)."""
        rule = schema.поле(self.info(name), "переход") or {}
        target = schema.поле(rule, "следующий")
        if not target:
            return None
        wanted = schema.поле(rule, "при_событии") or []
        marker = f"{event.get('комната')}/{event.get('действие')}"
        if event.get("действие") in wanted or marker in wanted:
            return target
        return None
