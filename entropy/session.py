"""Общее состояние партии и журнал событий.

Три приложения (терминал, чат, пульт ведущего) работают в разных окнах и
обмениваются данными через два файла в каталоге ``state/``:

* ``session.json``  — текущий этап, отношение разума, счётчики лимита;
* ``events.jsonl``  — журнал событий (по строке на событие), который остальные
  приложения читают «хвостом» и показывают на экране.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

from . import config, paths

#: Значения состояния по умолчанию (используются при первом запуске).
DEFAULT_STATE: dict[str, Any] = {
    "этап": None,
    "отношение": "настороженное",
    "сообщений_израсходовано": 0,
    "символов_израсходовано": 0,
    "токенов_запрос": 0,
    "токенов_ответ": 0,
    "прибавка_к_лимиту": 0,
    "молчание_до_сообщения": 0,
    "боевая_готовность": False,
    "начата": None,
    "обновлено": None,
}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _atomic_write(path: Path, text: str) -> None:
    """Запись через временный файл — состояние не бьётся при двух окнах."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Session:
    """Состояние партии, разделяемое между приложениями."""

    def __init__(self, path: str | os.PathLike):
        self.path = paths.resolve(path)
        self.data: dict[str, Any] = dict(DEFAULT_STATE)
        self.load()

    # ------------------------------------------------------------------ чтение
    def load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                stored = {}
            if isinstance(stored, dict):
                merged = dict(DEFAULT_STATE)
                merged.update(stored)
                self.data = merged
        return self.data

    def get(self, key: str, default: Any = None) -> Any:
        self.load()
        return self.data.get(key, default)

    # ------------------------------------------------------------------ запись
    def save(self) -> None:
        self.data["обновлено"] = _now()
        if not self.data.get("начата"):
            self.data["начата"] = self.data["обновлено"]
        _atomic_write(self.path, json.dumps(self.data, ensure_ascii=False, indent=2) + "\n")

    def set(self, key: str, value: Any) -> Any:
        """Перечитывает файл (его мог изменить сосед) и обновляет один ключ."""
        self.load()
        self.data[key] = value
        self.save()
        return value

    def update(self, **values: Any) -> dict[str, Any]:
        self.load()
        self.data.update(values)
        self.save()
        return self.data

    def bump(self, key: str, delta: int = 1) -> int:
        self.load()
        new_value = int(self.data.get(key, 0) or 0) + delta
        self.data[key] = new_value
        self.save()
        return new_value

    def reset(self) -> dict[str, Any]:
        self.data = dict(DEFAULT_STATE)
        self.data["начата"] = _now()
        self.save()
        return self.data


class EventLog:
    """Append-only журнал событий комплекса."""

    def __init__(self, path: str | os.PathLike):
        self.path = paths.resolve(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, kind: str, **payload: Any) -> dict[str, Any]:
        event = {"время": _now(), "тип": kind}
        event.update(payload)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Записывает готовый словарь события (ключ «тип» — вид события)."""
        payload = dict(event)
        kind = str(payload.pop("тип", "событие"))
        return self.append(kind, **payload)

    def size(self) -> int:
        """Текущая длина журнала в байтах — стартовая позиция «хвоста»."""
        return self.path.stat().st_size if self.path.exists() else 0

    def tail(self, cursor: int) -> tuple[list[dict[str, Any]], int]:
        """Возвращает события, появившиеся после позиции ``cursor``."""
        if not self.path.exists():
            return [], 0
        size = self.path.stat().st_size
        if cursor > size:  # журнал очистили
            cursor = 0
        events: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as fh:
            fh.seek(cursor)
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            cursor = fh.tell()
        return events, cursor

    def all(self) -> list[dict[str, Any]]:
        events, _ = self.tail(0)
        return events

    def clear(self) -> None:
        _atomic_write(self.path, "")


def open_session(cfg: dict) -> tuple[Session, EventLog]:
    """Открывает состояние и журнал по путям из конфигурации."""
    paths.ensure_dir(cfg["session"]["state_dir"])
    return (
        Session(config.state_file(cfg, "state_file")),
        EventLog(config.state_file(cfg, "events_file")),
    )


def describe(session: Session, extra: Iterable[str] = ()) -> str:
    """Короткая сводка состояния для команды «статус»."""
    data = session.load()
    lines = [
        f"этап:              {data.get('этап') or '(не задан)'}",
        f"отношение разума:  {data.get('отношение')}",
        f"израсходовано:     {data.get('сообщений_израсходовано')} сообщений, "
        f"{data.get('символов_израсходовано')} символов",
        f"токенов:           {data.get('токенов_запрос', 0)} в запросах, "
        f"{data.get('токенов_ответ', 0)} в ответах",
        f"боевая готовность: {'ДА' if data.get('боевая_готовность') else 'нет'}",
    ]
    lines.extend(extra)
    return "\n".join(lines)
