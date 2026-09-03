"""Журнал партии и отчёт для ведущего (возможность «журнал_партии»).

Терминал записывает сюда, что вводили игроки: сама команда, вид (настоящая,
сценарная, отклонённая) и код возврата. Вывод команд НЕ сохраняется — он может
быть огромным, а интерактивные программы (less, nano) его вообще не отдают.

Отчёт собирается из трёх источников — журнала терминала, переписки с разумом
и журнала событий комплекса — в один файл Markdown, упорядоченный по времени.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from . import config, features, paths


class Журнал:
    """Запись действий игроков в терминале."""

    def __init__(self, path: str | os.PathLike, включён: bool = True):
        self.path = paths.resolve(path)
        self.включён = включён
        if включён:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def записать(self, вид: str, **данные: Any) -> None:
        if not self.включён:
            return
        запись = {"время": time.strftime("%Y-%m-%d %H:%M:%S"), "вид": вид}
        запись.update(данные)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(запись, ensure_ascii=False) + "\n")

    def команда(self, текст: str, вид: str, успех: bool | None = None,
                этап: str = "") -> None:
        self.записать("команда", команда=текст, тип=вид,
                      успех=успех, этап=этап)

    def прочитать(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        записи = []
        for строка in self.path.read_text(encoding="utf-8").splitlines():
            строка = строка.strip()
            if not строка:
                continue
            try:
                записи.append(json.loads(строка))
            except json.JSONDecodeError:
                continue
        return записи

    def очистить(self) -> None:
        if self.path.exists():
            self.path.write_text("", encoding="utf-8")


def открыть(cfg: dict) -> Журнал:
    """Журнал по путям из конфигурации, с учётом отметки возможности."""
    return Журнал(config.state_file(cfg, "journal_file"),
                  features.включена(cfg, "журнал_партии"))


# ------------------------------------------------------------------- отчёт
def _прочитать_переписку(cfg: dict) -> list[dict[str, Any]]:
    путь = config.state_file(cfg, "history_file")
    if not путь.exists():
        return []
    try:
        данные = json.loads(путь.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return данные if isinstance(данные, list) else []


def собрать(cfg: dict) -> str:
    """Собирает отчёт о партии в формате Markdown."""
    from .session import EventLog, Session

    сессия = Session(config.state_file(cfg, "state_file"))
    события = EventLog(config.state_file(cfg, "events_file")).all()
    переписка = _прочитать_переписку(cfg)
    команды = открыть(cfg).прочитать()
    данные = сессия.load()

    строки: list[str] = [
        "# Отчёт о партии «Комплекс Энтропии»",
        "",
        f"- начата: {данные.get('начата') or '—'}",
        f"- последнее событие: {данные.get('обновлено') or '—'}",
        f"- этап на конец: {данные.get('этап') or '—'}",
        f"- отношение разума: {данные.get('отношение') or '—'}",
        f"- обращений к разуму: {данные.get('сообщений_израсходовано', 0)}",
        f"- токенов: {данные.get('токенов_запрос', 0)} в запросах, "
        f"{данные.get('токенов_ответ', 0)} в ответах",
        "",
    ]

    подтверждённые = [с for с in события if с.get("тип") == "действие_подтверждено"]
    взломы = [с for с in события if с.get("тип") == "попытка_взлома"]
    строки += [
        "## Коротко",
        "",
        f"- команд в терминале: {sum(1 for к in команды if к.get('вид') == 'команда')}",
        f"- реплик в переписке: {len(переписка)}",
        f"- подтверждённых действий комплекса: {len(подтверждённые)}",
        f"- попыток вывести разум из роли: {len(взломы)}",
        "",
    ]

    if подтверждённые:
        строки += ["## Что было применено", ""]
        for с in подтверждённые:
            пометка = f" — {с.get('пометка')}" if с.get("пометка") else ""
            строки.append(f"- {с.get('время')} · **{с.get('комната')} / "
                          f"{с.get('действие')}**{пометка}")
        строки.append("")

    # Общая лента по времени
    лента: list[tuple[str, str]] = []
    for к in команды:
        if к.get("вид") != "команда":
            continue
        отметка = {"сценарная": "заготовка", "отклонена": "отклонена",
                   "служебная": "служебная"}.get(к.get("тип", ""), "")
        хвост = f" ({отметка})" if отметка else ""
        лента.append((к.get("время", ""), f"`{к.get('команда', '')}`{хвост}"))
    for р in переписка:
        кто = "игроки" if р.get("роль") == "игрок" else "разум"
        текст = str(р.get("текст", "")).replace("\n", " ")
        лента.append((р.get("время", ""), f"**{кто}:** {текст}"))
    for с in события:
        if с.get("тип") == "этап":
            лента.append((с.get("время", ""), f"_этап: {с.get('этап')}_"))
        elif с.get("тип") == "действие_подтверждено":
            лента.append((с.get("время", ""),
                          f"_ПРИМЕНЕНО: {с.get('комната')} / {с.get('действие')}_"))
        elif с.get("тип") == "попытка_взлома":
            лента.append((с.get("время", ""),
                          f"_попытка сломать роль ({с.get('вид')})_"))

    if лента:
        строки += ["## Как шла партия", ""]
        for время, текст in sorted(лента, key=lambda п: п[0]):
            строки.append(f"- `{время}` {текст}")
        строки.append("")

    if not команды:
        строки += ["> Журнал терминала пуст: возможность «журнал_партии» была "
                   "выключена или игроки не вводили команд.", ""]

    строки += ["## Возможности в этой партии", ""]
    строки += [f"- {с}" for с in features.описание_состояния(cfg)]
    строки.append("")
    return "\n".join(строки)


def сохранить(cfg: dict, путь: str | os.PathLike) -> Path:
    файл = paths.resolve(путь)
    файл.parent.mkdir(parents=True, exist_ok=True)
    файл.write_text(собрать(cfg), encoding="utf-8")
    return файл
