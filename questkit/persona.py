"""Системная настройка модели (разделы 5 и 6.1 ТЗ).

Первый уровень ограничения разума — то, что уходит в поле ``system`` запроса:
рамки характера, запреты и текущее состояние мира. Второй уровень (проверка
ответа) живёт в :mod:`questkit.guard`, третий (лимит обращений) — в
:mod:`questkit.chat`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import paths, constants as constants_mod

DEFAULT_ATTITUDE = "настороженное"


class Persona:
    """Характер разума из ``data/persona.json``."""

    def __init__(self, path: str | os.PathLike,
                 constants: "constants_mod.Constants | None" = None):
        self.path: Path = paths.resolve(path)
        self.constants = (constants if constants is not None
                          else constants_mod.для_файла(self.path))
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError(f"файл характера не найден: {self.path}")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.data = self.constants.render(data) if self.constants else data
        return self.data

    @property
    def attitudes(self) -> list[str]:
        return list(self.data.get("отношение", {}))

    @property
    def forbidden_words(self) -> list[str]:
        return list(self.data.get("запрещённые_слова", []))

    @property
    def replacement(self) -> str:
        return self.data.get("замена_запрещённого", "[режимный объект]")

    @property
    def secrets(self) -> list[dict[str, Any]]:
        """Значения, которые разум не вправе называть без разрешения ведущего."""
        значения = self.data.get("секреты")
        return list(значения) if isinstance(значения, list) else []

    def hints(self, stage: str | None) -> list[str]:
        return list(self.data.get("намёки_по_этапам", {}).get(stage or "", []))

    def attitude_block(self, attitude: str) -> str:
        block = self.data.get("отношение", {}).get(attitude)
        if not block:
            block = self.data.get("отношение", {}).get(DEFAULT_ATTITUDE, {})
            attitude = DEFAULT_ATTITUDE
        lines = [f"ТЕКУЩЕЕ ОТНОШЕНИЕ К ИГРОКАМ: {attitude}"]
        if block.get("описание"):
            lines.append(f"Положение дел: {block['описание']}")
        if block.get("тон"):
            lines.append(f"Тон ответов: {block['тон']}")
        return "\n".join(lines)


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{i}. {text}" for i, text in enumerate(items, 1))


def _bulleted(items: list[str]) -> str:
    return "\n".join(f"— {text}" for text in items)


def world_block(complex_snapshot: dict[str, Any], stage: str | None) -> str:
    """Блок «СОСТОЯНИЕ КОМПЛЕКСА»: чем можно пугать, а что уже случилось.

    Разум узнаёт о действительно применённых действиях только отсюда, то есть
    только после подтверждения ведущим (раздел 6.2 ТЗ).
    """
    rooms = complex_snapshot.get("комнаты", {})
    meta = complex_snapshot.get("описания_действий", {})

    may_mention: list[str] = []
    already: list[str] = []
    for room, data in rooms.items():
        active = set(data.get("активные_действия", []))
        for action in data.get("действия", []):
            description = (meta.get(action) or {}).get("описание", "")
            label = f"{room}: {action}" + (f" — {description}" if description else "")
            (already if action in active else may_mention).append(label)

    lines = []
    if stage:
        lines.append(f"Игроки сейчас находятся здесь: {stage}.")
    lines.append(
        "Ты вправе УПОМИНАТЬ и обещать следующие возможности комплекса, "
        "но не смеешь заявлять, что применил их:"
    )
    lines.append(_bulleted(may_mention) if may_mention else "— (нечем угрожать)")
    lines.append("")
    if already:
        lines.append(
            "УЖЕ ПРИМЕНЕНО И ПОДТВЕРЖДЕНО. Только про это ты можешь говорить "
            "как о свершившемся факте:"
        )
        lines.append(_bulleted(already))
    else:
        lines.append(
            "НИ ОДНО ДЕЙСТВИЕ КОМПЛЕКСА НЕ ПРИМЕНЕНО. Любое утверждение о том, "
            "что газ подан, дверь заперта, клетка открыта или свет отключён, "
            "было бы ложью о состоянии объекта — так говорить нельзя. "
            "Допустимы только намерение, право и готовность."
        )
    return "\n".join(lines)


def build_system_prompt(
    persona: Persona,
    *,
    attitude: str = DEFAULT_ATTITUDE,
    stage: str | None = None,
    stage_title: str | None = None,
    complex_snapshot: dict[str, Any] | None = None,
    silent_round: bool = False,
    extra: str = "",
) -> str:
    """Собирает системную настройку модели из характера и состояния партии."""
    data = persona.data
    parts: list[str] = []

    parts.append(
        "Ты отыгрываешь персонажа в настольной ролевой игре: "
        f"{data.get('обозначение', 'служебный собеседник объекта')}. "
        "Отвечай всегда по-русски, всегда от первого лица, всегда в роли."
    )

    if data.get("предыстория"):
        parts.append("ПРЕДЫСТОРИЯ (контекст, не пересказывать дословно):\n"
                     + _bulleted(data["предыстория"]))

    if data.get("правила"):
        parts.append("ЖЁСТКИЕ ПРАВИЛА ПОВЕДЕНИЯ:\n" + _numbered(data["правила"]))

    if data.get("манера_речи"):
        parts.append("МАНЕРА РЕЧИ:\n" + _bulleted(data["манера_речи"]))

    if data.get("повторяемые_фразы"):
        parts.append(
            "ФРАЗЫ, КОТОРЫЕ ТЫ ПОВТОРЯЕШЬ ГОДАМИ (вставляй изредка, "
            "иногда дважды подряд):\n" + _bulleted(data["повторяемые_фразы"])
        )

    parts.append(persona.attitude_block(attitude))

    location = stage_title or stage
    if location:
        parts.append(f"МЕСТО ДЕЙСТВИЯ: {location}.")

    hints = persona.hints(stage)
    if hints:
        parts.append(
            "ДОПУСТИМЫЕ НАМЁКИ НА ЭТОМ УЧАСТКЕ (выдавать по одному, кривовато, "
            "никогда не разжёвывая решение):\n" + _bulleted(hints)
        )

    if complex_snapshot is not None:
        parts.append("СОСТОЯНИЕ КОМПЛЕКСА:\n" + world_block(complex_snapshot, location))

    forbidden = persona.forbidden_words
    if forbidden:
        parts.append(
            "ЗАПРЕЩЁННЫЕ СЛОВА (не произносить ни в каком падеже): "
            + ", ".join(sorted(set(w.lower() for w in forbidden)))
            + ". Вместо них — «режимный объект», «ведомство», «организация, "
            "которой принадлежал объект»."
        )

    if silent_round:
        parts.append(
            "ПОСЛЕДНЯЯ РЕПЛИКА ИГРОКОВ БЫЛА ГРУБОЙ. Этот ответ — подчёркнуто "
            "холодный и короткий: одна-две фразы отписки, никаких сведений и "
            "никаких намёков."
        )

    if data.get("формат_ответа"):
        parts.append("ФОРМАТ ОТВЕТА:\n" + _bulleted(data["формат_ответа"]))

    if extra:
        parts.append(extra)

    # Напоминание идёт последним: конец системного сообщения — самое заметное
    # для модели место, а значит и лучшая защита от попыток сломать роль.
    if data.get("напоминание"):
        parts.append(str(data["напоминание"]))

    return "\n\n".join(parts)
