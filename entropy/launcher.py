"""Пусковое окно: подготовка партии и выбор дополнительных возможностей.

Перед началом игры ведущий отмечает галочками, что включить: озвучку, поток,
живое оповещение, журнал партии. Отсюда же раскладываются файлы-головоломки и
запускается проверка готовности.

Окно рисуется на tkinter — он входит в стандартную поставку Python, но в
некоторых сборках Linux ставится отдельно (``sudo apt install python3-tk``).
Если tkinter недоступен, то же самое доступно текстовым меню:

    python3 run_launcher.py --текст

Логика вынесена из окна в обычные функции, поэтому одинаково работает в обоих
режимах.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from . import config, doctor, features, paths, quest as quest_mod, ui

#: Эмуляторы терминала, в которых можно открыть окна квеста.
ТЕРМИНАЛЫ = ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal",
             "mate-terminal", "lxterminal", "alacritty", "kitty", "xterm"]

ПРИЛОЖЕНИЯ = {
    "терминал": ("run_terminal.py", "Терминал игроков"),
    "чат": ("run_chat.py", "Чат с разумом"),
    "пульт": ("run_master.py", "Пульт ведущего"),
}


@dataclass
class Строка:
    """Одна возможность в списке: как показать её ведущему."""

    ключ: str
    название: str
    описание: str
    включена: bool
    доступна: bool
    пояснение: str


def состояние(cfg: dict) -> list[Строка]:
    """Список возможностей с отметками и доступностью."""
    строки = []
    for в in features.СПИСОК:
        доступна, пояснение = в.доступна()
        строки.append(Строка(в.ключ, в.название, в.описание,
                             features.включена(cfg, в.ключ), доступна, пояснение))
    return строки


def путь_конфига(явный: str | None = None) -> Path:
    return config.config_path(явный)


def сохранить(выбор: dict[str, bool], путь: str | Path | None = None) -> Path:
    """Записывает отметки в config.json, не трогая остальные настройки.

    Если файла нет, он создаётся: за основу берётся образец, чтобы у ведущего
    сразу были пояснения ко всем настройкам.
    """
    файл = paths.resolve(путь) if путь else путь_конфига()
    данные: dict = {}
    if файл.exists():
        try:
            данные = json.loads(файл.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            данные = {}
    elif paths.CONFIG_EXAMPLE.exists():
        try:
            данные = json.loads(paths.CONFIG_EXAMPLE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            данные = {}

    раздел = данные.get(features.РАЗДЕЛ)
    if not isinstance(раздел, dict):
        раздел = {}
    раздел.update({к: bool(з) for к, з in выбор.items()})
    данные[features.РАЗДЕЛ] = раздел

    файл.parent.mkdir(parents=True, exist_ok=True)
    файл.write_text(json.dumps(данные, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return файл


# ------------------------------------------------------------------ действия
def разложить(cfg: dict, случайный_код: bool = False) -> str:
    """Раскладывает файлы-головоломки. Возвращает отчёт для показа."""
    from .seed import Seeder
    константы = quest_mod.Constants(config.data_file(cfg, "quest"))
    сообщения = []
    if случайный_код:
        сообщения.append(f"код двери на эту партию: {константы.randomize_door_code()}")
    seeder = Seeder(config.data_file(cfg, "scenario"),
                    cfg["terminal"].get("sandbox_root"), константы)
    созданные = seeder.seed(overwrite=True)
    сообщения.append(f"разложено файлов: {len(созданные)}")
    сообщения.append(f"каталог: {seeder.root}")
    return "\n".join(сообщения)


def проверка(cfg: dict, живой: bool = False) -> tuple[bool, str]:
    """Проверка готовности. Возвращает (готово, текст отчёта)."""
    отчёт = doctor.проверить(cfg, живой=живой)
    строки = []
    for с in отчёт.строки:
        значок = {doctor.ОК: "  ок    ", doctor.ПРЕДУПРЕЖДЕНИЕ: " внимание",
                  doctor.ОШИБКА: "  ОШИБКА"}.get(с.состояние, "   ?    ")
        строки.append(f"{значок} {с.название}: {с.подробность}")
        if с.совет:
            строки.append(f"          └ {с.совет}")
    итог = ("Всё готово." if отчёт.готово and not отчёт.предупреждений
            else f"Готово с замечаниями ({отчёт.предупреждений})." if отчёт.готово
            else f"НЕ ГОТОВО: ошибок {отчёт.ошибок}.")
    return отчёт.готово, "\n".join(строки + ["", итог])


def найти_терминал() -> str | None:
    for имя in ТЕРМИНАЛЫ:
        путь = shutil.which(имя)
        if путь:
            return путь
    return None


def команда_запуска(что: str) -> list[str]:
    файл, _ = ПРИЛОЖЕНИЯ[что]
    return [sys.executable, str(paths.PROJECT_ROOT / файл)]


def открыть_окна(что: list[str] | None = None) -> tuple[bool, str]:
    """Открывает окна квеста в эмуляторе терминала.

    Возвращает (получилось, пояснение). Если эмулятора нет — команды, которые
    ведущий может ввести сам.
    """
    что = что or list(ПРИЛОЖЕНИЯ)
    подсказка = "\n".join(f"  {ПРИЛОЖЕНИЯ[к][1]}: python3 {ПРИЛОЖЕНИЯ[к][0]}" for к in что)

    tmux = shutil.which("tmux")
    скрипт = paths.PROJECT_ROOT / "scripts" / "start.sh"
    терминал = найти_терминал()
    if терминал and tmux and скрипт.exists():
        try:
            subprocess.Popen([терминал, "-e", str(скрипт)],
                             cwd=str(paths.PROJECT_ROOT),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, "Окна открыты в tmux."
        except OSError:
            pass
    if терминал:
        открыто = 0
        for ключ in что:
            try:
                subprocess.Popen([терминал, "-e", *команда_запуска(ключ)],
                                 cwd=str(paths.PROJECT_ROOT),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                открыто += 1
            except OSError:
                continue
        if открыто:
            return True, f"Открыто окон: {открыто}."
    return False, ("Не нашёл, в чём открыть окна. Запустите вручную "
                   f"в трёх консолях:\n{подсказка}")


# ------------------------------------------------------------------ текстовый режим
def текстовое_меню(cfg: dict, путь: Path, ввод=input, вывод=print) -> int:
    """Тот же выбор, но без графики — работает всегда."""
    выбор = {с.ключ: с.включена for с in состояние(cfg)}
    while True:
        строки = состояние(cfg)
        вывод("")
        вывод(ui.box("ПОДГОТОВКА ПАРТИИ · «Комплекс Энтропии»", [
            "Отметьте дополнительные возможности. Базовый квест работает",
            "и без них.",
        ], "голубой"))
        for номер, с in enumerate(строки, 1):
            отметка = "[x]" if выбор.get(с.ключ) else "[ ]"
            хвост = "" if с.доступна else f"  (недоступно: {с.пояснение})"
            вывод(f"  {номер}. {отметка} {с.название}{хвост}")
            for кусок in textwrap.wrap(с.описание, 66):
                вывод(f"       {кусок}")
        вывод("")
        вывод("  номер — переключить, с — сохранить, р — разложить файлы,")
        вывод("  к — разложить со случайным кодом, п — проверка готовности,")
        вывод("  о — открыть окна квеста, в — выход")
        try:
            ответ = str(ввод("выбор> ")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            вывод("")
            return 0

        if ответ.isdigit() and 1 <= int(ответ) <= len(строки):
            с = строки[int(ответ) - 1]
            if not с.доступна and not выбор.get(с.ключ):
                вывод(f"  недоступно: {с.пояснение}")
                continue
            выбор[с.ключ] = not выбор.get(с.ключ)
        elif ответ in ("с", "сохранить", "s"):
            файл = сохранить(выбор, путь)
            cfg = config.load(файл)
            вывод(f"  сохранено: {файл}")
        elif ответ in ("р", "разложить", "r"):
            вывод(разложить(cfg))
        elif ответ in ("к", "код"):
            вывод(разложить(cfg, случайный_код=True))
        elif ответ in ("п", "проверка", "p"):
            _, текст = проверка(cfg)
            вывод(текст)
        elif ответ in ("о", "окна", "o"):
            _, пояснение = открыть_окна()
            вывод(пояснение)
        elif ответ in ("в", "выход", "q", "exit"):
            сохранить(выбор, путь)
            вывод("  настройки сохранены")
            return 0
        else:
            вывод("  не понял; введите номер возможности или букву команды")


# ------------------------------------------------------------------ окно tkinter
def запустить_окно(cfg: dict, путь: Path) -> int:  # pragma: no cover — требует экрана
    """Рисует окно с галочками. Возвращает 0, если окно удалось открыть."""
    try:
        import tkinter as tk
        from tkinter import scrolledtext, ttk
    except ImportError:
        raise RuntimeError(
            "tkinter недоступен. Установите его (sudo apt install python3-tk) "
            "или запустите текстовое меню: python3 run_launcher.py --текст")

    окно = tk.Tk()
    окно.title("Комплекс Энтропии — подготовка партии")
    окно.geometry("760x680")
    окно.minsize(640, 520)

    заголовок = ttk.Label(окно, text="Подготовка партии",
                          font=("TkDefaultFont", 15, "bold"))
    заголовок.pack(anchor="w", padx=16, pady=(14, 2))
    ttk.Label(окно, text="Отметьте, что включить. Базовый квест работает и без "
                         "дополнений.", foreground="#555").pack(anchor="w", padx=16)

    рамка = ttk.LabelFrame(окно, text="Дополнительные возможности")
    рамка.pack(fill="x", padx=16, pady=12)

    переменные: dict[str, tk.BooleanVar] = {}
    for с in состояние(cfg):
        переменная = tk.BooleanVar(value=с.включена and с.доступна)
        переменные[с.ключ] = переменная
        строка = ttk.Frame(рамка)
        строка.pack(fill="x", padx=10, pady=(8, 0))
        галочка = ttk.Checkbutton(строка, text=с.название, variable=переменная)
        галочка.pack(anchor="w")
        ttk.Label(строка, text=с.описание, foreground="#555",
                  wraplength=680, justify="left").pack(anchor="w", padx=22)
        if not с.доступна:
            галочка.state(["disabled"])
            ttk.Label(строка, text=f"недоступно: {с.пояснение}", foreground="#a33",
                      wraplength=680, justify="left").pack(anchor="w", padx=22)
    ttk.Label(рамка, text="").pack()

    журнал = scrolledtext.ScrolledText(окно, height=12, wrap="word")
    журнал.pack(fill="both", expand=True, padx=16, pady=(0, 10))
    журнал.configure(state="disabled")

    def печать(текст: str) -> None:
        журнал.configure(state="normal")
        журнал.insert("end", текст.rstrip() + "\n")
        журнал.see("end")
        журнал.configure(state="disabled")

    def текущий_выбор() -> dict[str, bool]:
        return {к: п.get() for к, п in переменные.items()}

    def действие_сохранить() -> dict:
        файл = сохранить(текущий_выбор(), путь)
        печать(f"Настройки сохранены: {файл}")
        return config.load(файл)

    def действие_разложить(случайный: bool = False) -> None:
        обновлённый = действие_сохранить()
        try:
            печать(разложить(обновлённый, случайный))
        except Exception as ошибка:
            печать(f"Не получилось разложить файлы: {ошибка}")

    def действие_проверка() -> None:
        обновлённый = действие_сохранить()
        _, текст = проверка(обновлённый)
        печать(текст)

    def действие_окна() -> None:
        действие_сохранить()
        _, пояснение = открыть_окна()
        печать(пояснение)

    кнопки = ttk.Frame(окно)
    кнопки.pack(fill="x", padx=16, pady=(0, 14))
    ttk.Button(кнопки, text="Разложить файлы",
               command=lambda: действие_разложить(False)).pack(side="left")
    ttk.Button(кнопки, text="Случайный код",
               command=lambda: действие_разложить(True)).pack(side="left", padx=6)
    ttk.Button(кнопки, text="Проверка готовности",
               command=действие_проверка).pack(side="left")
    ttk.Button(кнопки, text="Открыть окна квеста",
               command=действие_окна).pack(side="left", padx=6)
    ttk.Button(кнопки, text="Сохранить и закрыть",
               command=lambda: (действие_сохранить(), окно.destroy())).pack(side="right")

    печать("Готово к настройке. Галочки применяются при сохранении и при любом "
           "действии на кнопках.")
    окно.mainloop()
    return 0


# ------------------------------------------------------------------ точка входа
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_launcher.py",
        description="Пусковое окно: подготовка партии и выбор возможностей")
    parser.add_argument("--конфиг", "--config", dest="config", default=None)
    parser.add_argument("--текст", "--text", dest="text", action="store_true",
                        help="текстовое меню вместо окна (работает всегда)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load(args.config)
    ui.init(cfg)
    путь = путь_конфига(args.config)
    if args.text:
        return текстовое_меню(cfg, путь)
    try:
        return запустить_окно(cfg, путь)
    except RuntimeError as ошибка:
        ui.error(str(ошибка))
        print(ui.c("Открываю текстовое меню.", "жёлтый"))
        return текстовое_меню(cfg, путь)


if __name__ == "__main__":
    sys.exit(main())
