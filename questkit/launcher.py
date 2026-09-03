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

from . import (config, doctor, features, pack as pack_mod, paths,
               constants as constants_mod, ui)
from . import i18n
from .i18n import t

#: Эмуляторы терминала, в которых можно открыть окна квеста.
ТЕРМИНАЛЫ = ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal",
             "mate-terminal", "lxterminal", "alacritty", "kitty", "xterm"]

ПРИЛОЖЕНИЯ = {
    "терминал": ("run_terminal.py", "Терминал игроков"),
    "чат": ("run_chat.py", "Чат с разумом"),
    "пульт": ("run_master.py", "Пульт ведущего"),
}


@dataclass
class Пакет:
    """Пакет содержимого, найденный в templates/ или examples/."""

    путь: Path
    название: str
    язык: str
    описание: str
    это_шаблон: bool

    @property
    def ссылка(self) -> str:
        """Путь для настройки «content» — относительный, если внутри проекта."""
        try:
            return str(self.путь.relative_to(paths.PROJECT_ROOT))
        except ValueError:
            return str(self.путь)


def найти_пакеты() -> list[Пакет]:
    """Все пакеты содержимого: сначала шаблоны, потом готовые примеры."""
    найденные: list[Пакет] = []
    for каталог, это_шаблон in ((paths.TEMPLATES_DIR, True), (paths.EXAMPLES_DIR, False)):
        if not каталог.is_dir():
            continue
        for место in sorted(каталог.iterdir()):
            if not (место / "pack.json").exists():
                continue
            манифест = pack_mod.Манифест(место / "pack.json")
            найденные.append(Пакет(место, манифест.name, манифест.language,
                                   манифест.description, это_шаблон))
    return найденные


def список_пакетов(cfg: dict) -> list[Пакет]:
    """Пакеты для выбора, включая тот, что уже выбран в настройках.

    Ведущий, скопировавший шаблон в свою папку, играет пакет за пределами
    templates/ и examples/. Он обязан остаться в списке — иначе окно молча
    переключило бы его на чужой квест.
    """
    найденные = найти_пакеты()
    текущий = str(cfg.get("content") or "")
    if текущий and not any(п.ссылка == текущий for п in найденные):
        место = paths.resolve(текущий)
        if (место / "pack.json").exists() or место.is_dir():
            манифест = pack_mod.Манифест(место / "pack.json")
            найденные.insert(0, Пакет(место, манифест.name, манифест.language,
                                      манифест.description, False))
    return найденные


def подпись_пакета(пакет: Пакет) -> str:
    вид = t("launcher.pack_kind.template" if пакет.это_шаблон
            else "launcher.pack_kind.example")
    return f"[{вид} · {пакет.язык}] {пакет.название}  —  {пакет.ссылка}"


def выбрать_пакет(пакет: "Пакет | str", путь: str | Path | None = None) -> Path:
    """Записывает выбранный пакет в настройки."""
    ссылка = пакет.ссылка if isinstance(пакет, Пакет) else str(пакет)
    файл = paths.resolve(путь) if путь else путь_конфига()
    данные: dict = {}
    if файл.exists():
        try:
            данные = json.loads(файл.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            данные = {}
    данные["content"] = ссылка
    файл.parent.mkdir(parents=True, exist_ok=True)
    файл.write_text(json.dumps(данные, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return файл


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
    константы = constants_mod.Constants(config.data_file(cfg, "constants"))
    сообщения = []
    if случайный_код:
        новый = константы.randomize_door_code()
        сообщения.append(t("launcher.random_code", код=новый, code=новый))
    seeder = Seeder(config.data_file(cfg, "layout"),
                    cfg["terminal"].get("sandbox_root"), константы)
    созданные = seeder.seed(overwrite=True)
    сообщения.append(t("launcher.seeded", число=len(созданные), count=len(созданные)))
    сообщения.append(t("launcher.seed_dir", путь=seeder.root, path=seeder.root))
    return "\n".join(сообщения)


def проверка(cfg: dict, живой: bool = False) -> tuple[bool, str]:
    """Проверка готовности. Возвращает (готово, текст отчёта)."""
    отчёт = doctor.проверить(cfg, живой=живой)
    строки = []
    for с in отчёт.строки:
        значок = {doctor.ОК: t("doctor.mark.ok"),
                  doctor.ПРЕДУПРЕЖДЕНИЕ: t("doctor.mark.warning"),
                  doctor.ОШИБКА: t("doctor.mark.error")}.get(с.состояние, "   ?    ")
        строки.append(f"{значок} {с.название}: {с.подробность}")
        if с.совет:
            строки.append(f"          └ {с.совет}")
    итог = (t("doctor.verdict.ready") if отчёт.готово and not отчёт.предупреждений
            else t("doctor.verdict.warnings", число=отчёт.предупреждений,
                   count=отчёт.предупреждений) if отчёт.готово
            else t("doctor.verdict.not_ready", число=отчёт.ошибок, count=отчёт.ошибок))
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
            return True, t("launcher.windows.tmux")
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
            return True, t("launcher.windows.opened", число=открыто, count=открыто)
    return False, t("launcher.windows.manual", команды=подсказка, commands=подсказка)


# ------------------------------------------------------------------ текстовый режим
def текстовое_меню(cfg: dict, путь: Path, ввод=input, вывод=print) -> int:
    """Тот же выбор, но без графики — работает всегда."""
    выбор = {с.ключ: с.включена for с in состояние(cfg)}
    while True:
        строки = состояние(cfg)
        вывод("")
        активный = pack_mod.load(cfg)
        вывод(ui.box(t("launcher.menu.title"), [
            f'{t("launcher.menu.quest"):<8}{активный.name}',
            f'{t("launcher.menu.pack"):<8}{cfg.get("content")}',
            "",
            t("launcher.menu.hint"),
        ], "голубой"))
        for номер, с in enumerate(строки, 1):
            отметка = "[x]" if выбор.get(с.ключ) else "[ ]"
            хвост = "" if с.доступна else f"  (недоступно: {с.пояснение})"
            вывод(f"  {номер}. {отметка} {с.название}{хвост}")
            for кусок in textwrap.wrap(с.описание, 66):
                вывод(f"       {кусок}")
        вывод("")
        вывод(t("launcher.menu.keys1"))
        вывод(t("launcher.menu.keys2"))
        вывод(t("launcher.menu.keys3"))
        вывод(t("launcher.menu.keys4"))
        try:
            ответ = str(ввод(t("launcher.menu.prompt"))).strip().lower()
        except (EOFError, KeyboardInterrupt):
            вывод("")
            return 0

        if ответ.isdigit() and 1 <= int(ответ) <= len(строки):
            с = строки[int(ответ) - 1]
            if not с.доступна and not выбор.get(с.ключ):
                вывод(t("launcher.menu.unavailable", причина=с.пояснение, reason=с.пояснение))
                continue
            выбор[с.ключ] = not выбор.get(с.ключ)
        elif ответ in ("с", "сохранить", "s"):
            файл = сохранить(выбор, путь)
            cfg = config.load(файл)
            вывод(t("launcher.menu.saved", файл=файл, file=файл))
        elif ответ in ("р", "разложить", "r"):
            вывод(разложить(cfg))
        elif ответ in ("к", "код"):
            вывод(разложить(cfg, случайный_код=True))
        elif ответ in ("п", "проверка", "p"):
            _, текст = проверка(cfg)
            вывод(текст)
        elif ответ in ("и", "квест", "пакет"):
            пакеты = список_пакетов(cfg)
            if not пакеты:
                вывод(t("launcher.menu.no_packs"))
                continue
            for номер, п in enumerate(пакеты, 1):
                отметка = (t("launcher.menu.now")
                           if п.ссылка == str(cfg.get("content", "")) else "")
                вывод(f"  {номер}. {подпись_пакета(п)}{отметка}")
            try:
                выбранный = str(ввод(t("launcher.menu.which_pack"))).strip()
            except (EOFError, KeyboardInterrupt):
                continue
            if выбранный.isdigit() and 1 <= int(выбранный) <= len(пакеты):
                файл = выбрать_пакет(пакеты[int(выбранный) - 1], путь)
                cfg = config.load(файл)
                выбор = {с.ключ: с.включена for с in состояние(cfg)}
                вывод(t("launcher.quest_now", название=pack_mod.load(cfg).name, name=pack_mod.load(cfg).name))
            else:
                вывод(t("launcher.menu.bad_number"))
        elif ответ in ("о", "окна", "o"):
            _, пояснение = открыть_окна()
            вывод(пояснение)
        elif ответ in ("в", "выход", "q", "exit"):
            сохранить(выбор, путь)
            вывод(t("launcher.menu.settings_saved"))
            return 0
        else:
            вывод(t("launcher.menu.confused"))


# ------------------------------------------------------------------ окно tkinter
def запустить_окно(cfg: dict, путь: Path) -> int:  # pragma: no cover — требует экрана
    """Рисует окно с галочками. Возвращает 0, если окно удалось открыть."""
    try:
        import tkinter as tk
        from tkinter import scrolledtext, ttk
    except ImportError:
        raise RuntimeError(t("launcher.no_tkinter"))

    окно = tk.Tk()
    окно.title(t("launcher.window.title", квест=pack_mod.load(cfg).name,
                 quest=pack_mod.load(cfg).name))
    окно.geometry("760x680")
    окно.minsize(640, 520)

    заголовок = ttk.Label(окно, text=t("launcher.window.header"),
                          font=("TkDefaultFont", 15, "bold"))
    заголовок.pack(anchor="w", padx=16, pady=(14, 2))
    ttk.Label(окно, text=t("launcher.window.subtitle"),
              foreground="#555").pack(anchor="w", padx=16)

    выбор_пакета = ttk.LabelFrame(окно, text=t("launcher.window.pack_frame"))
    выбор_пакета.pack(fill="x", padx=16, pady=(12, 0))
    пакеты = список_пакетов(cfg)
    текущий = str(cfg.get("content", ""))
    подписи = [подпись_пакета(п) for п in пакеты]
    переменная_пакета = tk.StringVar(
        value=next((п for п, с in zip(подписи, пакеты) if с.ссылка == текущий),
                   подписи[0] if подписи else текущий))
    поле = ttk.Combobox(выбор_пакета, values=подписи, textvariable=переменная_пакета,
                        state="readonly", width=70)
    поле.pack(anchor="w", padx=10, pady=8)
    ttk.Label(выбор_пакета, text=t("launcher.window.pack_hint"), foreground="#555",
              wraplength=680, justify="left").pack(anchor="w", padx=10, pady=(0, 8))

    рамка = ttk.LabelFrame(окно, text=t("launcher.window.features_frame"))
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
            ttk.Label(строка, text=t("launcher.window.unavailable", причина=с.пояснение,
                                     reason=с.пояснение), foreground="#a33",
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

    def выбранный_пакет() -> "Пакет | None":
        подпись = переменная_пакета.get()
        for п, с in zip(подписи, пакеты):
            if п == подпись:
                return с
        return None

    def действие_сохранить() -> dict:
        пакет = выбранный_пакет()
        if пакет is not None and пакет.ссылка != str(config.load(путь).get("content", "")):
            выбрать_пакет(пакет, путь)
            печать(t("launcher.window.quest_set", название=пакет.название,
                     путь=пакет.ссылка, name=пакет.название, path=пакет.ссылка))
        файл = сохранить(текущий_выбор(), путь)
        печать(t("launcher.window.saved", файл=файл, file=файл))
        return config.load(файл)

    def действие_разложить(случайный: bool = False) -> None:
        обновлённый = действие_сохранить()
        try:
            печать(разложить(обновлённый, случайный))
        except Exception as ошибка:
            печать(t("launcher.window.seed_failed", ошибка=ошибка, error=ошибка))

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
    ttk.Button(кнопки, text=t("launcher.window.btn_seed"),
               command=lambda: действие_разложить(False)).pack(side="left")
    ttk.Button(кнопки, text=t("launcher.window.btn_code"),
               command=lambda: действие_разложить(True)).pack(side="left", padx=6)
    ttk.Button(кнопки, text=t("launcher.window.btn_check"),
               command=действие_проверка).pack(side="left")
    ttk.Button(кнопки, text=t("launcher.window.btn_windows"),
               command=действие_окна).pack(side="left", padx=6)
    ttk.Button(кнопки, text=t("launcher.window.btn_save"),
               command=lambda: (действие_сохранить(), окно.destroy())).pack(side="right")

    печать(t("launcher.window.ready"))
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
    i18n.init(cfg)
    ui.init(cfg)
    путь = путь_конфига(args.config)
    if args.text:
        return текстовое_меню(cfg, путь)
    try:
        return запустить_окно(cfg, путь)
    except RuntimeError as ошибка:
        ui.error(str(ошибка))
        print(ui.c(t("launcher.fallback_text"), "жёлтый"))
        return текстовое_меню(cfg, путь)


if __name__ == "__main__":
    sys.exit(main())
