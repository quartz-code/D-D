"""Возможности комплекса и их применение (разделы 6.2 и 7 ТЗ).

Ключевая идея: приложение-чат может *читать* этот файл, чтобы разум знал, чем
он вправе пугать игроков, но изменить состояние комплекса нельзя нигде, кроме
:meth:`ComplexMap.apply_action`, а он требует явного подтверждения ведущего.
Ни одна ветка кода чата не вызывает эту функцию — «слова» и «дело» разделены.

Формат файла возможностей — как в ТЗ, по комнате на ключ::

    {
      "первая_комната": {
        "действия": ["блокировка_двери", "блокировка_двери"],
        "состояние": "неактивно"
      }
    }

Поддерживается и расширенная форма, которую использует поставляемый
``data/complex.json``::

    {
      "комнаты": { ... то же самое ... },
      "описания_действий": {
        "блокировка_двери": {
          "описание": "…", "боевое": true,
          "формулировки": ["газ", "клапан"]
        }
      }
    }
"""

from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path
from typing import Any

from . import paths, constants as constants_mod, schema
from .i18n import t

#: Слово, которое ведущий обязан ввести, чтобы событие применилось.
CONFIRM_WORD = "ДА"

STATE_ACTIVE = "активно"
STATE_INACTIVE = "неактивно"


class ConfirmationRequired(Exception):
    """Действие не применено: ведущий не подтвердил его."""


class UnknownRoom(KeyError):
    """В файле возможностей нет такой комнаты."""


class UnknownAction(KeyError):
    """В комнате нет такого действия."""


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class ComplexMap:
    """Файл возможностей комплекса + операции над ним."""

    def __init__(self, path: str | os.PathLike,
                 constants: "constants_mod.Constants | None" = None):
        self.path: Path = paths.resolve(path)
        # Этот файл приложение перезаписывает (в нём живёт состояние комнат),
        # поэтому константы подставляются не при загрузке, а при чтении
        # описаний — иначе шаблоны затёрлись бы готовыми значениями.
        self.constants = (constants if constants is not None
                          else constants_mod.для_файла(self.path))
        self.raw: dict[str, Any] = {}
        self.load()

    # ------------------------------------------------------------ чтение/запись
    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError(f"файл возможностей не найден: {self.path}")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{self.path}: ожидался объект JSON верхнего уровня")
        self.raw = data
        return self.raw

    def save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------ разбор
    @property
    def rooms(self) -> dict[str, Any]:
        """Словарь комнат — независимо от того, какая из двух форм файла."""
        прямо = schema.поле(self.raw, "комнаты")
        if isinstance(прямо, dict):
            return прямо
        # Минимальный формат: комнаты лежат прямо на верхнем уровне.
        return {k: v for k, v in self.raw.items()
                if isinstance(v, dict) and schema.есть(v, "действия")}

    @property
    def action_meta(self) -> dict[str, Any]:
        meta = schema.поле(self.raw, "описания_действий")
        return meta if isinstance(meta, dict) else {}

    def room(self, name: str) -> dict[str, Any]:
        rooms = self.rooms
        if name not in rooms:
            raise UnknownRoom(name)
        return rooms[name]

    def actions(self, room: str) -> list[str]:
        return list(schema.поле(self.room(room), "действия", []))

    def state(self, room: str) -> str:
        return schema.канон_состояния(
            schema.поле(self.room(room), "состояние", STATE_INACTIVE))

    def active_actions(self, room: str) -> list[str]:
        return list(schema.поле(self.room(room), "активные_действия", []))

    def describe_action(self, action: str) -> dict[str, Any]:
        meta = self.action_meta.get(action)
        meta = dict(meta) if isinstance(meta, dict) else {}
        return self.constants.render(meta) if self.constants else meta

    def is_combat(self, action: str) -> bool:
        """Ведёт ли действие к боевой сцене (раздел 8 ТЗ)."""
        return bool(schema.поле(self.describe_action(action), "боевое", True))

    def snapshot(self) -> dict[str, Any]:
        """Копия данных только для чтения — то, что отдаётся чату.

        Возвращается глубокая копия: даже если код чата что-то в ней изменит,
        файл возможностей это не затронет.
        """
        снимок = {
            "комнаты": copy.deepcopy(self.rooms),
            "описания_действий": copy.deepcopy(self.action_meta),
        }
        return self.constants.render(снимок) if self.constants else снимок

    def all_active(self) -> list[tuple[str, str]]:
        """Список пар (комната, действие) по всем подтверждённым действиям."""
        result: list[tuple[str, str]] = []
        for name in self.rooms:
            for action in self.active_actions(name):
                result.append((name, action))
        return result

    # ------------------------------------------------------- изменение состояния
    def _check(self, room: str, action: str) -> dict[str, Any]:
        data = self.room(room)
        if action not in schema.поле(data, "действия", []):
            raise UnknownAction(f"{room}: нет действия «{action}»")
        return data

    @staticmethod
    def _require_confirmation(confirmation: str | None, what: str) -> None:
        if (confirmation or "").strip().upper() != CONFIRM_WORD:
            raise ConfirmationRequired(
                f"{what}: требуется подтверждение ведущего (введите «{CONFIRM_WORD}»)"
            )

    def apply_action(
        self,
        room: str,
        action: str,
        confirmation: str | None = None,
        *,
        master: str = "ведущий",
        note: str = "",
    ) -> dict[str, Any]:
        """Применяет действие. Без подтверждения — исключение, файл не меняется."""
        data = self._check(room, action)
        self._require_confirmation(confirmation, f"{room}/{action}")

        active = list(schema.поле(data, "активные_действия", []))
        if action not in active:
            active.append(action)
        schema.записать(data, "активные_действия", active)
        schema.записать(data, "состояние", schema.значение_состояния(data, STATE_ACTIVE))
        отметка = _now()
        schema.записать(data, "обновлено", отметка)
        history = list(schema.поле(data, "история", []))
        history.append(schema.запись(data, {"время": отметка, "действие": action,
                                            "результат": "применено", "мастер": master,
                                            "пометка": note}))
        schema.записать(data, "история", history)
        self.save()

        meta = self.describe_action(action)
        return {
            "тип": "действие_подтверждено",
            "комната": room,
            "действие": action,
            "описание": meta.get("описание", ""),
            "боевое": self.is_combat(action),
            "мастер": master,
            "пометка": note,
        }

    def revert_action(
        self,
        room: str,
        action: str,
        confirmation: str | None = None,
        *,
        master: str = "ведущий",
    ) -> dict[str, Any]:
        """Откатывает действие (ошиблись кнопкой / сцена отыграна)."""
        data = self._check(room, action)
        self._require_confirmation(confirmation, f"откат {room}/{action}")

        active = [a for a in schema.поле(data, "активные_действия", []) if a != action]
        data["активные_действия"] = active
        data["состояние"] = STATE_ACTIVE if active else STATE_INACTIVE
        data["обновлено"] = _now()
        history = list(data.get("история", []))
        history.append({"время": data["обновлено"], "действие": action,
                        "результат": "отменено", "мастер": master})
        data["история"] = history
        self.save()
        return {
            "тип": "действие_отменено",
            "комната": room,
            "действие": action,
            "мастер": master,
        }

    def reset(self, confirmation: str | None = None) -> int:
        """Сбрасывает все комнаты в «неактивно» перед новой партией."""
        self._require_confirmation(confirmation, "сброс всех комнат")
        count = 0
        for data in self.rooms.values():
            if (schema.поле(data, "состояние") != STATE_INACTIVE
                or schema.поле(data, "активные_действия")):
                count += 1
            schema.записать(data, "состояние",
                            schema.значение_состояния(data, STATE_INACTIVE))
            schema.записать(data, "активные_действия", [])
            schema.записать(data, "история", [])
            schema.записать(data, "обновлено", _now())
        self.save()
        return count


def summary(cmap: ComplexMap) -> str:
    """Таблица комнат для пульта ведущего."""
    lines = []
    for name, data in cmap.rooms.items():
        state = schema.поле(data, "состояние", STATE_INACTIVE)
        mark = "●" if state == STATE_ACTIVE else "○"
        actions = ", ".join(schema.поле(data, "действия", [])) or "—"
        lines.append(f"{mark} {name:<18} [{state}]")
        lines.append(f"    действия: {actions}")
        active = schema.поле(data, "активные_действия") or []
        if active:
            lines.append(f"    ПРИМЕНЕНО: {', '.join(active)}")
    return "\n".join(lines) if lines else "(в файле возможностей нет комнат)"
