"""Конфигурация квеста (раздел 9.6 ТЗ: ключ API не хардкодится в коде).

Порядок применения настроек, каждый следующий уровень перекрывает предыдущий:

1. ``DEFAULTS`` — значения по умолчанию из этого модуля;
2. ``config/config.json`` — локальный файл ведущего (в git не попадает);
3. переменные окружения — только для секретов (ключ API).
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from . import paths

#: Значения по умолчанию. Файл ``config/config.json`` может переопределить
#: любую ветку этого словаря, указав только изменяемые ключи.
DEFAULTS: dict[str, Any] = {
    "deepseek": {
        # Ключ сюда можно вписать, но надёжнее держать его в переменной
        # окружения, имя которой задаёт "api_key_env".
        "api_key": "",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "temperature": 1.15,
        "max_tokens": 700,
        "timeout_sec": 60,
    },
    "chat": {
        # Раздел 6.3 ТЗ — лимит на обращения за сессию.
        "limit_messages": 40,
        "limit_chars": 24000,
        # Предел длины одной реплики игрока: защита от попытки «затопить»
        # контекст простынёй текста и от лишнего расхода бюджета.
        "max_message_chars": 2000,
        # Сколько последних реплик уходит в модель вместе с системной настройкой.
        "history_window": 24,
        # Оформление «голоса комплекса» (раздел 4 ТЗ).
        "delay_min_sec": 0.8,
        "delay_max_sec": 2.4,
        "typewriter_cps": 90,
        "show_gm_notes": True,
        # "ручной" — ведущий меняет отношение сам; "авто" — приложение смещает
        # его само по реакции игроков (раздел 5, правило 7).
        "attitude_drift": "ручной",
    },
    "terminal": {
        # Каталог, в котором игроки «оказываются» при запуске терминала.
        "sandbox_root": "~/комплекс",
        "shell": "/bin/sh",
        # Локаль для запускаемых команд. Весь квест на русском, а некоторые
        # утилиты (например rev) зависают на UTF-8 в локали POSIX/C.
        # Пустая строка — не вмешиваться в окружение.
        "locale": "C.UTF-8",
        # false — приложение не выполняет команды по-настоящему, а работает
        # только на заготовленных ответах из data/canned (раздел 3 ТЗ).
        "real_execution": True,
        "command_timeout_sec": 20,
        # true — команда cd не выпускает игроков за пределы sandbox_root.
        "restrict_to_root": False,
        # Прячет от игроков файлы самого квеста (ключ API, характер разума,
        # разгадки, шпаргалку) и секреты из переменных окружения.
        "protect_project_files": True,
        "protected_patterns": [],
        "typewriter_cps": 0,
        "show_gm_notes": True,
        # Команды, которые способны испортить партию даже внутри ВМ.
        "blocked_patterns": [
            r"rm\s+(-[a-zA-Z]*\s+)*(-rf|-fr)\s+/(\s|$)",
            r"\bmkfs(\.|\s)",
            r"\bdd\b[^\n]*\bof=/dev/",
            r":\(\)\s*\{.*\};\s*:",
            r"\b(shutdown|reboot|halt|poweroff)\b",
            r">\s*/dev/sd[a-z]",
        ],
    },
    "ui": {
        "color": True,
        "bell": True,
        "flash_frames": 6,
        "flash_delay_sec": 0.16,
    },
    "session": {
        "state_dir": "state",
        "state_file": "state/session.json",
        "events_file": "state/events.jsonl",
        "history_file": "state/chat_history.json",
    },
    "files": {
        "complex": "data/complex.json",
        "stages": "data/stages.json",
        "persona": "data/persona.json",
        "scenario": "data/scenario/default.json",
        "canned_dir": "data/canned",
    },
}


class ConfigError(Exception):
    """Ошибка чтения конфигурации."""


def _merge(base: dict, patch: dict) -> dict:
    """Рекурсивно накладывает ``patch`` на копию ``base``."""
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def config_path(explicit: str | os.PathLike | None = None) -> Path:
    """Определяет, какой файл конфигурации использовать."""
    if explicit:
        return paths.resolve(explicit)
    from_env = os.environ.get("ENTROPY_CONFIG")
    if from_env:
        return paths.resolve(from_env)
    return paths.CONFIG_FILE


def load(explicit: str | os.PathLike | None = None) -> dict[str, Any]:
    """Читает конфигурацию. Отсутствие файла — не ошибка, берутся умолчания."""
    path = config_path(explicit)
    cfg = copy.deepcopy(DEFAULTS)
    if path.exists():
        try:
            patch = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path}: некорректный JSON ({exc})") from exc
        if not isinstance(patch, dict):
            raise ConfigError(f"{path}: ожидался объект JSON верхнего уровня")
        cfg = _merge(cfg, patch)
    cfg["_путь_конфига"] = str(path)
    cfg["_конфиг_найден"] = path.exists()
    return cfg


def api_key(cfg: dict) -> str:
    """Ключ DeepSeek: сначала переменная окружения, затем файл конфигурации.

    Возвращает пустую строку, если ключ нигде не задан — приложение чата в
    этом случае предлагает офлайн-режим, а не падает.
    """
    section = cfg.get("deepseek", {})
    env_name = section.get("api_key_env") or "DEEPSEEK_API_KEY"
    return (os.environ.get(env_name) or section.get("api_key") or "").strip()


def mask_key(key: str) -> str:
    """Ключ для показа ведущему: последние 4 символа, остальное — звёздочки."""
    if not key:
        return "(не задан)"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:3]}…{'*' * 6}{key[-4:]}"


def data_file(cfg: dict, name: str) -> Path:
    """Путь к файлу данных по имени ключа из секции ``files``."""
    try:
        return paths.resolve(cfg["files"][name])
    except KeyError as exc:
        raise ConfigError(f"в конфигурации нет files.{name}") from exc


def state_file(cfg: dict, name: str) -> Path:
    """Путь к файлу состояния по имени ключа из секции ``session``."""
    try:
        path = paths.resolve(cfg["session"][name])
    except KeyError as exc:
        raise ConfigError(f"в конфигурации нет session.{name}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
