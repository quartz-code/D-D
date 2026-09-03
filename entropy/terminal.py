"""Терминал-приложение для игроков (разделы 3 и 4 ТЗ).

Два вида вывода в одном окне:

* обычная консоль — команды выполняются по-настоящему в системе;
* сценарные команды — ответ подставляется из ``data/canned`` (так надёжнее
  для темпа игры и для команд, которых в системе не существует).

Команда «помощь» контекстная: показывает только то, что относится к текущему
этапу. Этап переключается вручную («мастер этап <имя>») или автоматически,
когда игроки добираются до нужного файла.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import (config, features, journal as journal_mod, paths,
               quest as quest_mod, session as session_mod, ui)
from .complexctl import ComplexMap, ConfirmationRequired, CONFIRM_WORD, summary
from .stages import Stages
from .watcher import Наблюдатель, печать_поверх_ввода

try:
    import readline  # noqa: F401
except ImportError:  # pragma: no cover
    pass

HELP_WORDS = {"помощь", "справка", "help", "?", "хелп"}
EXIT_WORDS = {"выход", "exit", "quit", "logout", "отключиться"}
CLEAR_WORDS = {"очистить", "clear", "cls"}
STATUS_WORDS = {"статус", "состояние"}
LINK_WORDS = {"связь", "канал", "переговоры"}

GM_HELP = [
    "мастер помощь                    — эта справка",
    "мастер статус                    — этап, каталог, состояние комплекса",
    "мастер этапы                     — список этапов",
    "мастер этап <имя|дальше>         — переключить этап вручную",
    "мастер подсказка                 — заметка по текущему этапу",
    "мастер отношение <имя>           — сменить отношение разума (видит чат)",
    "мастер комнаты                   — комнаты и их состояние",
    "мастер событие <комната> <дейст> — подтвердить действие комплекса",
    "мастер откат <комната> <дейст>   — отменить действие",
    "мастер сброс                     — сбросить состояние всех комнат",
]


class TerminalApp:
    """Консоль комплекса."""

    def __init__(self, args: argparse.Namespace):
        self.cfg = config.load(args.config)
        if args.no_real:
            self.cfg["terminal"]["real_execution"] = False
        if args.quiet_gm:
            self.cfg["terminal"]["show_gm_notes"] = False
        ui.init(self.cfg)

        self.session, self.events = session_mod.open_session(self.cfg)
        self.constants = quest_mod.Constants(config.data_file(self.cfg, "quest"))
        self.stages = Stages(config.data_file(self.cfg, "stages"), self.constants)
        self.complex = ComplexMap(config.data_file(self.cfg, "complex"), self.constants)
        self.canned_dir = config.data_file(self.cfg, "canned_dir")
        self.journal = journal_mod.открыть(self.cfg)
        # Живое оповещение: фоновый поток печатает сигнал сразу, не дожидаясь
        # следующего Enter. Выключается в пусковом окне.
        self.watcher: Наблюдатель | None = None
        if features.включена(self.cfg, "живое_оповещение"):
            self.watcher = Наблюдатель(self.events, self._живое_событие)
        self.cursor = self.events.size()

        root = args.root or self.cfg["terminal"]["sandbox_root"]
        self.root = paths.expand(root)
        self.cwd = self.root if self.root.is_dir() else Path.cwd()
        self.previous_cwd = self.cwd
        self.blocked = [re.compile(p, re.IGNORECASE)
                        for p in self.cfg["terminal"].get("blocked_patterns", [])]
        охраняемое = [
            re.escape(str(paths.PROJECT_ROOT)),
            r"config\.json", r"persona\.json", r"complex\.json", r"stages\.json",
            r"шпаргалк\w*", r"cheatsheet", r"\bentropy/", r"\bstate/", r"\.git\b",
            r"scenario", r"data/canned", r"run_(chat|master|seed|terminal)\.py",
            r"\.квест-энтропия",
        ]
        охраняемое += list(self.cfg["terminal"].get("protected_patterns", []))
        self.protected = [re.compile(p, re.IGNORECASE) for p in охраняемое]

        if args.stage:
            self.session.set("этап", args.stage)
        if not self.session.get("этап"):
            self.session.set("этап", self.stages.first())

    # ------------------------------------------------------------------ утилиты
    @property
    def stage(self) -> str:
        return self.session.get("этап") or self.stages.first()

    def note(self, text: str) -> None:
        ui.gm_note(text, self.cfg["terminal"].get("show_gm_notes", True))

    def out(self, text: str) -> None:
        ui.typewriter(text, float(self.cfg["terminal"].get("typewriter_cps", 0) or 0))

    def prompt(self) -> str:
        try:
            where = self.cwd.relative_to(self.root)
            location = "~" if str(where) == "." else f"~/{where}"
        except ValueError:
            location = str(self.cwd)
        объект = self.constants.get("объект", "12-К")
        return ui.c(f"{объект}:{location}$ ", "зелёный", "жирный")

    def _живое_событие(self, event: dict[str, Any]) -> None:
        """Обработчик фонового потока: печатает поверх набираемой строки."""
        печать_поверх_ввода(lambda: self.show_event(event))

    def show_event(self, event: dict[str, Any]) -> None:
        """Показывает одно событие из журнала."""
        if event.get("тип") == "действие_подтверждено" and event.get("боевое"):
            ui.combat_alert(self.cfg, event.get("комната", "?"), event.get("действие", "?"),
                            event.get("описание", ""), event.get("пометка", ""))
        elif event.get("тип") in ("этап", "отношение"):
            self.note(ui.event_line(event))
            if event.get("тип") == "этап":
                self.session.load()

    def drain_events(self) -> None:
        if self.watcher is not None:
            # События разбирает фоновый поток; здесь — тот же разбор по
            # требованию. Курсор общий, поэтому дважды показано не будет.
            self.watcher.проверить()
            return
        events, self.cursor = self.events.tail(self.cursor)
        for event in events:
            if event.get("тип") == "действие_подтверждено" and event.get("боевое"):
                ui.combat_alert(self.cfg, event.get("комната", "?"), event.get("действие", "?"),
                                event.get("описание", ""), event.get("пометка", ""))
            elif event.get("тип") in ("этап", "отношение"):
                self.note(ui.event_line(event))
                if event.get("тип") == "этап":
                    self.session.load()

    # ------------------------------------------------------------------- этапы
    def set_stage(self, name: str, source: str = "мастер") -> None:
        if not self.stages.exists(name):
            ui.error(f"нет такого этапа: {name}. Доступные: {', '.join(self.stages.order)}")
            return
        self.session.set("этап", name)
        self.events.append("этап", этап=name, источник=source)
        info = self.stages.info(name)
        ui.stage_banner(name, info.get("название", name), info.get("описание", ""))
        if source != "мастер" and info.get("подсказка_мастеру"):
            self.note(info["подсказка_мастеру"])

    def maybe_advance(self, command: str, success: bool) -> None:
        target = self.stages.check_transition(self.stage, command, cwd=self.cwd, success=success)
        if target and target != self.stage:
            self.note(f"сработал автопереход этапа: {self.stage} → {target}")
            self.set_stage(target, source="автопереход")

    # ---------------------------------------------------------- команды ведущего
    def gm_command(self, line: str) -> None:
        parts = line.split()[1:]
        if not parts or parts[0] in ("помощь", "справка", "?"):
            print(ui.box("ПУЛЬТ ВЕДУЩЕГО (игрокам не показывать)", GM_HELP, "жёлтый"))
            return
        head, rest = parts[0], parts[1:]

        if head == "статус":
            extra = [
                f"каталог:           {self.cwd}",
                f"корень квеста:     {self.root}",
                f"реальное выполнение: "
                f"{'да' if self.cfg['terminal']['real_execution'] else 'нет (только заготовки)'}",
            ]
            print(ui.box("СОСТОЯНИЕ ПАРТИИ",
                         session_mod.describe(self.session, extra).splitlines(), "жёлтый"))
            print(summary(self.complex))
        elif head == "этапы":
            lines = []
            for name in self.stages.order:
                mark = "▶" if name == self.stage else " "
                lines.append(f"{mark} {name:<16} {self.stages.title(name)}")
            print(ui.box("ЭТАПЫ", lines, "жёлтый"))
        elif head == "этап":
            if not rest:
                self.note(f"текущий этап: {self.stage}")
            elif rest[0] in ("дальше", "next"):
                target = self.stages.next_in_order(self.stage)
                if target:
                    self.set_stage(target)
                else:
                    self.note("это последний этап")
            else:
                self.set_stage(rest[0])
        elif head == "подсказка":
            hint = self.stages.info(self.stage).get("подсказка_мастеру")
            self.note(hint or "для этого этапа заметки нет")
        elif head == "отношение":
            if not rest:
                self.note(f"текущее отношение: {self.session.get('отношение')}")
            else:
                self.session.set("отношение", rest[0])
                self.events.append("отношение", отношение=rest[0], источник="терминал")
                self.note(f"отношение разума: {rest[0]}")
        elif head in ("комнаты", "возможности"):
            self.complex.load()
            print(summary(self.complex))
        elif head in ("событие", "подтвердить"):
            self.confirm_action(rest)
        elif head in ("откат", "отменить"):
            self.revert_action(rest)
        elif head == "сброс":
            self.reset_complex()
        else:
            ui.error(f"неизвестная команда пульта: {head} (см. «мастер помощь»)")

    def confirm_action(self, rest: list[str]) -> None:
        """Раздел 6.2 ТЗ: применение действия только с подтверждением ведущего."""
        if len(rest) < 2:
            ui.error("использование: мастер событие <комната> <действие>")
            return
        room, action = rest[0], rest[1]
        note = " ".join(rest[2:])
        self.complex.load()
        try:
            meta = self.complex.describe_action(action)
            print(ui.c(f"\nПОДТВЕРЖДЕНИЕ СОБЫТИЯ: {room} / {action}", "жёлтый", "жирный"))
            if meta.get("описание"):
                print(f"  {meta['описание']}")
            if meta.get("последствие"):
                print(f"  последствие: {meta['последствие']}")
            answer = input(ui.c(f"Применить? Введите «{CONFIRM_WORD}»: ", "жёлтый"))
            event = self.complex.apply_action(room, action, answer, note=note)
        except ConfirmationRequired as exc:
            self.note(f"отменено: {exc}")
            return
        except KeyError as exc:
            ui.error(f"нет такой комнаты или действия: {exc}")
            return
        self.events.append_event(event)
        self.session.set("боевая_готовность", bool(event.get("боевое")))
        if event.get("боевое"):
            ui.combat_alert(self.cfg, room, action, event.get("описание", ""), note)
        else:
            self.note(f"применено (не боевое): {room} / {action}")

    def revert_action(self, rest: list[str]) -> None:
        if len(rest) < 2:
            ui.error("использование: мастер откат <комната> <действие>")
            return
        self.complex.load()
        try:
            answer = input(ui.c(f"Отменить {rest[0]}/{rest[1]}? Введите «{CONFIRM_WORD}»: ", "жёлтый"))
            event = self.complex.revert_action(rest[0], rest[1], answer)
        except ConfirmationRequired as exc:
            self.note(f"отменено: {exc}")
            return
        except KeyError as exc:
            ui.error(f"нет такой комнаты или действия: {exc}")
            return
        self.events.append_event(event)
        self.note(f"действие отменено: {rest[0]} / {rest[1]}")

    def reset_complex(self) -> None:
        try:
            answer = input(ui.c(f"Сбросить все комнаты? Введите «{CONFIRM_WORD}»: ", "жёлтый"))
            count = self.complex.reset(answer)
        except ConfirmationRequired as exc:
            self.note(f"отменено: {exc}")
            return
        self.session.set("боевая_готовность", False)
        self.events.append("сброс_комплекса", комнат=count)
        self.note(f"состояние комплекса сброшено (затронуто комнат: {count})")

    # ------------------------------------------------------------- выполнение
    def is_blocked(self, command: str) -> bool:
        return any(pattern.search(command) for pattern in self.blocked)

    def touches_project(self, command: str) -> bool:
        """Пытается ли команда добраться до внутренностей самого квеста.

        Иначе достаточно одной команды ``cat`` из терминала, чтобы прочитать
        ключ API, характер разума, ответы к головоломкам и шпаргалку ведущего.
        """
        if not self.cfg["terminal"].get("protect_project_files", True):
            return False
        return any(pattern.search(command) for pattern in self.protected)

    def change_dir(self, command: str) -> None:
        parts = command.split(maxsplit=1)
        target = parts[1].strip() if len(parts) > 1 else "~"
        if target == "-":
            destination = self.previous_cwd
        elif target in ("~", ""):
            destination = self.root
        else:
            candidate = paths.expand(target)
            destination = candidate if candidate.is_absolute() else self.cwd / candidate
        destination = Path(os.path.normpath(destination))
        if not destination.is_dir():
            self.out(f"cd: нет такого каталога: {target}")
            return
        if self.cfg["terminal"].get("restrict_to_root"):
            try:  # разрешён только корень квеста и всё, что внутри него
                destination.resolve().relative_to(self.root.resolve())
            except ValueError:
                self.out("cd: выход за пределы объекта заблокирован распорядителем.")
                self.note("restrict_to_root=true — переход наружу запрещён")
                return
        self.previous_cwd, self.cwd = self.cwd, destination

    def run_real(self, command: str) -> bool:
        """Выполняет команду по-настоящему. Возвращает True при коде выхода 0."""
        if not self.cfg["terminal"].get("real_execution", True):
            self.out("ОТКАЗАНО: терминал работает в режиме заготовленных ответов.")
            self.note("real_execution=false — реальные команды не выполняются")
            return False
        shell = self.cfg["terminal"].get("shell", "/bin/sh")
        timeout = float(self.cfg["terminal"].get("command_timeout_sec", 0) or 0) or None
        try:
            result = subprocess.run([shell, "-c", command], cwd=str(self.cwd),
                                    timeout=timeout, env=self.child_env())
        except FileNotFoundError:
            ui.error(f"не найден интерпретатор {shell}")
            return False
        except subprocess.TimeoutExpired:
            ui.error(f"команда прервана по времени ({timeout} с)")
            return False
        except KeyboardInterrupt:
            print()
            self.note("команда прервана по Ctrl+C")
            return False
        if result.returncode != 0:
            self.note(f"код возврата: {result.returncode}")
        return result.returncode == 0

    def child_env(self) -> dict[str, str]:
        """Окружение для запускаемых команд.

        Квест целиком на русском, а часть утилит (``rev``) зависает на
        многобайтовом тексте в локали POSIX/C, поэтому детям процесса
        принудительно выставляется UTF-8 — если ведущий не отключил это,
        обнулив ``terminal.locale``.
        """
        env = os.environ.copy()
        if self.cfg["terminal"].get("protect_project_files", True):
            # Ключ API живёт в переменной окружения ведущего — игрокам он
            # не должен доставаться ни через env, ни через printenv.
            секретные = {str(self.cfg["deepseek"].get("api_key_env", "")), "ENTROPY_CONFIG"}
            for имя in list(env):
                if имя in секретные or re.search(
                        r"(API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD)$", имя, re.IGNORECASE):
                    env.pop(имя, None)
        wanted = str(self.cfg["terminal"].get("locale") or "")
        current = env.get("LC_ALL") or env.get("LC_CTYPE") or env.get("LANG") or ""
        if wanted and "utf" not in current.lower():
            env["LC_ALL"] = wanted
            env.setdefault("LANG", wanted)
        return env

    def run_scripted(self, entry: dict[str, Any]) -> None:
        """Подставляет заготовленный вывод (раздел 3 ТЗ)."""
        delay = float(entry.get("задержка", 0) or 0)
        if delay:
            print(ui.c("обработка запроса…", "тусклый"))
            time.sleep(delay)
        text = self.stages.canned_text(entry, self.canned_dir)
        self.out(text)
        self.note(f"вывод подставлен из заготовки: {entry.get('файл', 'текст в stages.json')}")
        if entry.get("этап_после"):
            self.set_stage(entry["этап_после"], source="сценарная команда")

    # -------------------------------------------------------------- встроенные
    def builtin(self, command: str) -> bool:
        """Обрабатывает встроенные команды. True — команда обработана."""
        word = command.split()[0].lower()
        if word in HELP_WORDS:
            print(self.stages.help_text(self.stage,
                                        gm=self.cfg["terminal"].get("show_gm_notes", True)))
            return True
        if word in CLEAR_WORDS:
            print("\033[2J\033[H", end="")
            return True
        if word in STATUS_WORDS:
            info = self.stages.info(self.stage)
            active = self.complex.all_active()
            lines = [
                f"участок:        {info.get('название', self.stage)}",
                f"каталог:        {self.cwd}",
                f"канал связи:    доступен (см. команду «связь»)",
                f"систем в работе: {len(self.complex.rooms)} помещений под управлением",
            ]
            if active:
                lines.append("")
                lines.append("ПРИМЕНЁННЫЕ МЕРЫ:")
                lines += [f"  {room}: {action}" for room, action in active]
            print(ui.box("СОСТОЯНИЕ УЧАСТКА", lines, "голубой"))
            return True
        if word in LINK_WORDS:
            path = Path(self.canned_dir) / "link.txt"
            self.out(path.read_text(encoding="utf-8").rstrip("\n") if path.exists()
                     else "Канал связи: запустите python3 run_chat.py во второй консоли.")
            return True
        if word == "cd":
            self.change_dir(command)
            return True
        if word in EXIT_WORDS:
            raise SystemExit(0)
        return False

    # --------------------------------------------------------------------- цикл
    def greet(self) -> None:
        info = self.stages.info(self.stage)
        lines = [
            f"Терминал служебного доступа. Объект {self.constants.get('объект', '12-К')}.",
            "",
            f"этап:     {self.stage} — {info.get('название', '')}",
            f"каталог:  {self.cwd}",
            "",
            "«помощь» — команды, доступные на этом участке.",
            "«связь»  — выход на голосовой канал распорядителя.",
            "«выход»  — отключиться.",
        ]
        print(ui.box(f"КОМПЛЕКС {self.constants.get('объект', '12-К')} · КОНСОЛЬ", lines, "зелёный"))
        if not self.root.is_dir():
            self.note(f"каталог квеста не найден: {self.root} — разложите файлы: "
                      f"python3 run_seed.py разложить")

    def run(self) -> int:
        self.greet()
        if self.watcher is not None:
            self.watcher.запустить()
            self.note("живое оповещение включено")
        while True:
            self.drain_events()
            try:
                line = input(self.prompt())
            except (EOFError, KeyboardInterrupt):
                print()
                break
            command = line.strip()
            if not command:
                continue
            if command.split()[0].lower() in ("мастер", "gm", "master"):
                self.journal.команда(command, "служебная", этап=self.stage)
                self.gm_command(command)
                continue
            try:
                if self.builtin(command):
                    self.journal.команда(command, "встроенная", True, self.stage)
                    continue
            except SystemExit:
                break
            if self.is_blocked(command):
                self.out("ОТКАЗАНО. Команда запрещена регламентом объекта.")
                self.note(f"команда заблокирована списком blocked_patterns: {command}")
                self.journal.команда(command, "отклонена", False, self.stage)
                continue
            if self.touches_project(command):
                self.out("ОТКАЗАНО. Обращение к служебному разделу вне вашей формы допуска.")
                self.note(f"попытка добраться до файлов квеста: {command}")
                self.events.append("попытка_подсмотреть", команда=command[:200])
                self.journal.команда(command, "отклонена", False, self.stage)
                continue
            entry = self.stages.scripted(self.stage, command)
            if entry:
                self.journal.команда(command, "сценарная", True, self.stage)
                self.run_scripted(entry)
                self.maybe_advance(command, True)
                continue
            success = self.run_real(command)
            self.journal.команда(command, "настоящая", success, self.stage)
            self.maybe_advance(command, success)
        if self.watcher is not None:
            self.watcher.остановить()
        self.note("терминал закрыт")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_terminal.py",
        description="Терминал-приложение квеста «Комплекс Энтропии»",
    )
    parser.add_argument("--конфиг", "--config", dest="config", default=None,
                        help="путь к файлу конфигурации")
    parser.add_argument("--корень", "--root", dest="root", default=None,
                        help="каталог, с которого начинают игроки")
    parser.add_argument("--этап", "--stage", dest="stage", default=None,
                        help="начать с указанного этапа")
    parser.add_argument("--без-выполнения", "--no-real", dest="no_real", action="store_true",
                        help="не выполнять команды по-настоящему (только заготовки)")
    parser.add_argument("--без-пометок", "--quiet-gm", dest="quiet_gm", action="store_true",
                        help="не показывать служебные пометки ведущему")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        app = TerminalApp(args)
    except (FileNotFoundError, config.ConfigError) as exc:
        ui.error(str(exc))
        return 2
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
