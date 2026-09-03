"""Оформление вывода: «голос комплекса», рамки и боевой сигнал (раздел 8 ТЗ)."""

from __future__ import annotations

import os
import random
import shutil
import sys
import textwrap
import time
from typing import Any, Iterable

RESET = "\033[0m"
STYLES = {
    "жирный": "\033[1m",
    "тусклый": "\033[2m",
    "курсив": "\033[3m",
    "инверсия": "\033[7m",
    "красный": "\033[31m",
    "зелёный": "\033[32m",
    "жёлтый": "\033[33m",
    "синий": "\033[34m",
    "розовый": "\033[35m",
    "голубой": "\033[36m",
    "белый": "\033[37m",
    "фон_красный": "\033[41m",
    "фон_жёлтый": "\033[43m",
    "фон_серый": "\033[100m",
}

# По умолчанию цвет включён только в настоящем терминале; init() уточняет.
_color_enabled = sys.stdout.isatty()


def init(cfg: dict | None = None) -> None:
    """Включает/выключает цвет по конфигурации, TTY и переменной NO_COLOR."""
    global _color_enabled
    want = True if cfg is None else bool(cfg.get("ui", {}).get("color", True))
    if os.environ.get("NO_COLOR"):
        want = False
    _color_enabled = want and sys.stdout.isatty()


def color_enabled() -> bool:
    return _color_enabled


def c(text: str, *styles: str) -> str:
    """Красит текст, если цвет разрешён."""
    if not _color_enabled or not styles:
        return text
    prefix = "".join(STYLES.get(s, "") for s in styles)
    return f"{prefix}{text}{RESET}" if prefix else text


def width(default: int = 78) -> int:
    try:
        return min(shutil.get_terminal_size().columns, 100)
    except OSError:
        return default


def rule(char: str = "─", *styles: str) -> str:
    return c(char * width(), *(styles or ("тусклый",)))


def say(text: str = "", *styles: str) -> None:
    print(c(text, *styles))


def gm_note(text: str, enabled: bool = True) -> None:
    """Служебная пометка для ведущего — игрокам её можно не показывать."""
    if enabled:
        print(c(f"[мастер] {text}", "тусклый", "жёлтый"))


def error(text: str) -> None:
    print(c(f"[ошибка] {text}", "красный"))


def box(title: str, lines: Iterable[str], *styles: str) -> str:
    """Рамка с заголовком — используется для этапов и справки."""
    body = list(lines)
    w = max([len(title) + 4] + [len(line) for line in body] + [40])
    w = min(w, width() - 2)
    top = "┌" + "─" * (w + 2) + "┐"
    head = f"│ {title.ljust(w)} │"
    sep = "├" + "─" * (w + 2) + "┤"
    rows = [f"│ {line[:w].ljust(w)} │" for line in body]
    bottom = "└" + "─" * (w + 2) + "┘"
    frame = "\n".join([top, head, sep, *rows, bottom]) if body else "\n".join([top, head, bottom])
    return c(frame, *styles) if styles else frame


def typewriter(text: str, cps: float = 0.0, *styles: str) -> None:
    """Посимвольный вывод «голоса комплекса».

    ``cps`` — символов в секунду; 0 или отсутствие TTY отключает эффект.
    """
    if cps <= 0 or not sys.stdout.isatty():
        print(c(text, *styles))
        return
    delay = 1.0 / cps
    prefix = "".join(STYLES.get(s, "") for s in styles) if _color_enabled else ""
    if prefix:
        sys.stdout.write(prefix)
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay * (3.0 if ch in ".!?" else 1.0))
    if prefix:
        sys.stdout.write(RESET)
    sys.stdout.write("\n")
    sys.stdout.flush()


def dramatic_pause(cfg: dict) -> None:
    """Задержка перед ответом разума (раздел 4 ТЗ)."""
    chat = cfg.get("chat", {})
    low = float(chat.get("delay_min_sec", 0) or 0)
    high = float(chat.get("delay_max_sec", 0) or 0)
    if high <= 0:
        return
    if low > high:
        low, high = high, low
    time.sleep(random.uniform(low, high))


def bell(cfg: dict, times: int = 1) -> None:
    if cfg.get("ui", {}).get("bell", True) and sys.stdout.isatty():
        sys.stdout.write("\a" * times)
        sys.stdout.flush()


def combat_alert(cfg: dict, room: str, action: str, description: str = "", note: str = "") -> None:
    """Раздел 8 ТЗ: яркий сигнал перехода в боевую ситуацию.

    Мигающая инверсная рамка + звуковой сигнал: ведущий понимает, что пора
    отложить ноутбук и продолжать сцену за столом.
    """
    ui_cfg = cfg.get("ui", {})
    lines = [
        "",
        "!!!  ПРОТОКОЛ ПРИМЕНЁН  !!!",
        "",
        f"комната:   {room}",
        f"действие:  {action}",
    ]
    if description:
        lines.append(f"суть:      {description}")
    if note:
        lines.append(f"пометка:   {note}")
    lines += [
        "",
        "ОТЛОЖИТЕ НОУТБУК — СЦЕНА ПРОДОЛЖАЕТСЯ ЗА СТОЛОМ",
        "",
    ]
    frame_text = box("ВНИМАНИЕ: БОЕВАЯ СИТУАЦИЯ", lines)
    frames = int(ui_cfg.get("flash_frames", 6) or 0)
    delay = float(ui_cfg.get("flash_delay_sec", 0.16) or 0)
    bell(cfg, 3)
    if _color_enabled and frames > 0 and sys.stdout.isatty():
        height = frame_text.count("\n") + 1
        for i in range(frames):
            style = ("фон_красный", "белый", "жирный") if i % 2 == 0 else ("красный", "жирный")
            sys.stdout.write(c(frame_text, *style) + "\n")
            sys.stdout.flush()
            if i < frames - 1:
                time.sleep(delay)
                sys.stdout.write(f"\033[{height}A\033[J")  # вернуться и стереть кадр
    else:
        print(c(frame_text, "красный", "жирный"))
    print(c(">>> состояние комплекса изменено пультом ведущего <<<", "красный", "жирный"))


def stage_banner(name: str, title: str, description: str = "") -> None:
    lines = [title]
    if description:
        lines += [""] + textwrap.wrap(description, width=min(70, width() - 6))
    print(box(f"ЭТАП: {name}", lines, "голубой", "жирный"))


def event_line(event: dict[str, Any]) -> str:
    """Однострочное описание события из журнала — для «хвоста» в приложениях."""
    kind = event.get("тип", "?")
    if kind == "действие_подтверждено":
        return (f"{event.get('время')} ▸ подтверждено: {event.get('комната')} / "
                f"{event.get('действие')}")
    if kind == "действие_отменено":
        return (f"{event.get('время')} ▸ отменено: {event.get('комната')} / "
                f"{event.get('действие')}")
    if kind == "этап":
        return f"{event.get('время')} ▸ этап: {event.get('этап')} ({event.get('источник', '?')})"
    if kind == "отношение":
        return f"{event.get('время')} ▸ отношение разума: {event.get('отношение')}"
    return f"{event.get('время')} ▸ {kind}: " + ", ".join(
        f"{k}={v}" for k, v in event.items() if k not in ("время", "тип")
    )
