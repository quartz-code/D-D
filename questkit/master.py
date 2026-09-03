"""Пульт ведущего (разделы 6.2, 7 и 8 ТЗ).

Единственное место, где состояние комплекса действительно меняется. Разум в
чате может сколько угодно грозить газом — газ «включает» ведущий здесь, явно
подтвердив событие. После подтверждения приложение подаёт боевой сигнал и
пишет событие в журнал, который видят остальные окна.

Примеры::

    python3 run_master.py                                   # интерактивный пульт
    python3 run_master.py комнаты
    python3 run_master.py подтвердить первая_комната блокировка_двери --да
    python3 run_master.py этап серверная
    python3 run_master.py журнал 20
"""

from __future__ import annotations

import argparse
import sys

from . import (config, doctor, features, guard, journal as journal_mod,
               persona as persona_mod, constants as constants_mod,
               session as session_mod, ui)
from .world import ComplexMap, ConfirmationRequired, CONFIRM_WORD, summary
from .stages import Stages

try:
    import readline  # noqa: F401
except ImportError:  # pragma: no cover
    pass

HELP = [
    "комнаты                          — список комнат и их состояние",
    "действия <комната>               — что можно применить в комнате",
    "подтвердить <комната> <действие> — ПРИМЕНИТЬ действие (спросит подтверждение)",
    "откат <комната> <действие>       — отменить применённое действие",
    "сброс                            — вернуть все комнаты в «неактивно»",
    "этап [имя|дальше]                — текущий этап партии (видят все окна)",
    "отношение [имя]                  — отношение разума к игрокам",
    "статус                           — сводка по партии",
    "журнал [N]                       — последние N событий",
    "проверка [--живой]               — всё ли готово к партии",
    "отчёт [файл]                     — собрать отчёт о партии в Markdown",
    "дополнения                       — какие необязательные возможности включены",
    "помощь                           — эта справка",
    "выход                            — закрыть пульт",
]


class MasterConsole:
    """Логика пульта, общая для интерактивного и разового запуска."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        ui.init(cfg)
        self.session, self.events = session_mod.open_session(cfg)
        self.constants = constants_mod.Constants(config.data_file(cfg, "constants"))
        self.complex = ComplexMap(config.data_file(cfg, "world"), self.constants)
        self.stages = Stages(config.data_file(cfg, "stages"), self.constants)
        self.persona = persona_mod.Persona(config.data_file(cfg, "persona"), self.constants)
        if not self.session.get("этап"):
            self.session.set("этап", self.stages.first())

    # ------------------------------------------------------------------ команды
    def cmd_rooms(self) -> int:
        self.complex.load()
        print(ui.box("ВОЗМОЖНОСТИ КОМПЛЕКСА", summary(self.complex).splitlines(), "жёлтый"))
        return 0

    def cmd_actions(self, room: str) -> int:
        self.complex.load()
        try:
            actions = self.complex.actions(room)
        except KeyError:
            ui.error(f"нет такой комнаты: {room}. Доступные: {', '.join(self.complex.rooms)}")
            return 1
        lines = []
        active = set(self.complex.active_actions(room))
        for action in actions:
            meta = self.complex.describe_action(action)
            mark = "●" if action in active else "○"
            lines.append(f"{mark} {action}")
            if meta.get("описание"):
                lines.append(f"    {meta['описание']}")
            if meta.get("последствие"):
                lines.append(f"    последствие: {meta['последствие']}")
            lines.append(f"    боевое: {'да' if self.complex.is_combat(action) else 'нет'}")
        print(ui.box(f"КОМНАТА: {room}", lines, "жёлтый"))
        return 0

    def cmd_confirm(self, room: str, action: str, note: str = "", auto_yes: bool = False) -> int:
        """Раздел 6.2 ТЗ: применение только по явному подтверждению ведущего."""
        self.complex.load()
        try:
            self.complex._check(room, action)
        except KeyError as exc:
            ui.error(f"нет такой комнаты или действия: {exc}")
            return 1

        meta = self.complex.describe_action(action)
        lines = [
            f"комната:      {room}",
            f"действие:     {action}",
            f"описание:     {meta.get('описание', '—')}",
            f"последствие:  {meta.get('последствие', '—')}",
            f"боевое:       {'ДА — будет подан боевой сигнал' if self.complex.is_combat(action) else 'нет'}",
        ]
        print(ui.box("ПОДТВЕРЖДЕНИЕ СОБЫТИЯ", lines, "жёлтый", "жирный"))

        answer = CONFIRM_WORD if auto_yes else input(
            ui.c(f"Применить? Введите «{CONFIRM_WORD}»: ", "жёлтый", "жирный")
        )
        try:
            event = self.complex.apply_action(room, action, answer, note=note)
        except ConfirmationRequired as exc:
            print(ui.c(f"НЕ ПРИМЕНЕНО: {exc}", "тусклый"))
            return 1

        self.events.append_event(event)
        self.session.set("боевая_готовность", bool(event.get("боевое")))
        if event.get("боевое"):
            ui.combat_alert(self.cfg, room, action, event.get("описание", ""), note)
        else:
            print(ui.c(f"Применено (не боевое): {room} / {action}", "зелёный", "жирный"))
        return 0

    def cmd_revert(self, room: str, action: str, auto_yes: bool = False) -> int:
        self.complex.load()
        answer = CONFIRM_WORD if auto_yes else input(
            ui.c(f"Отменить {room}/{action}? Введите «{CONFIRM_WORD}»: ", "жёлтый")
        )
        try:
            event = self.complex.revert_action(room, action, answer)
        except ConfirmationRequired as exc:
            print(ui.c(f"НЕ ОТМЕНЕНО: {exc}", "тусклый"))
            return 1
        except KeyError as exc:
            ui.error(f"нет такой комнаты или действия: {exc}")
            return 1
        self.events.append_event(event)
        if not self.complex.all_active():
            self.session.set("боевая_готовность", False)
        print(ui.c(f"Отменено: {room} / {action}", "зелёный"))
        return 0

    def cmd_reset(self, auto_yes: bool = False) -> int:
        answer = CONFIRM_WORD if auto_yes else input(
            ui.c(f"Сбросить состояние ВСЕХ комнат? Введите «{CONFIRM_WORD}»: ", "жёлтый")
        )
        try:
            count = self.complex.reset(answer)
        except ConfirmationRequired as exc:
            print(ui.c(f"НЕ СБРОШЕНО: {exc}", "тусклый"))
            return 1
        self.session.set("боевая_готовность", False)
        self.events.append("сброс_комплекса", комнат=count)
        print(ui.c(f"Состояние комплекса сброшено (затронуто комнат: {count})", "зелёный"))
        return 0

    def cmd_stage(self, name: str = "") -> int:
        if not name:
            print(f"текущий этап: {self.session.get('этап')}")
            for stage in self.stages.order:
                mark = "▶" if stage == self.session.get("этап") else " "
                print(f"{mark} {stage:<16} {self.stages.title(stage)}")
            return 0
        if name in ("дальше", "next"):
            target = self.stages.next_in_order(self.session.get("этап"))
            if not target:
                print("это последний этап")
                return 1
            name = target
        if not self.stages.exists(name):
            ui.error(f"нет такого этапа: {name}. Доступные: {', '.join(self.stages.order)}")
            return 1
        self.session.set("этап", name)
        self.events.append("этап", этап=name, источник="пульт")
        info = self.stages.info(name)
        ui.stage_banner(name, info.get("название", name), info.get("описание", ""))
        if info.get("подсказка_мастеру"):
            ui.gm_note(info["подсказка_мастеру"])
        return 0

    def cmd_attitude(self, name: str = "") -> int:
        if not name:
            print(f"текущее отношение: {self.session.get('отношение')}")
            print("доступные: " + ", ".join(self.persona.attitudes))
            return 0
        if name in ("теплее", "холоднее"):
            current = self.session.get("отношение", persona_mod.DEFAULT_ATTITUDE)
            name = guard.shift_attitude(current, 1 if name == "теплее" else -1)
        if name not in self.persona.attitudes:
            ui.error(f"нет такого отношения: {name}. Доступные: {', '.join(self.persona.attitudes)}")
            return 1
        self.session.set("отношение", name)
        self.events.append("отношение", отношение=name, источник="пульт")
        block = self.persona.data.get("отношение", {}).get(name, {})
        print(ui.c(f"Отношение разума: {name}", "зелёный", "жирный"))
        if block.get("тон"):
            print(f"  тон: {block['тон']}")
        return 0

    def cmd_status(self) -> int:
        self.complex.load()
        active = self.complex.all_active()
        extra = [
            f"файл возможностей: {self.complex.path}",
            f"применённых мер:   {len(active)}",
        ]
        print(ui.box("СВОДКА ПАРТИИ", session_mod.describe(self.session, extra).splitlines(),
                     "жёлтый"))
        if active:
            for room, action in active:
                print(f"  ● {room}: {action}")
        return 0

    def cmd_report(self, путь: str = "") -> int:
        """Отчёт о партии из журнала терминала, переписки и событий."""
        if путь:
            файл = journal_mod.сохранить(self.cfg, путь)
            print(ui.c(f"отчёт сохранён: {файл}", "зелёный"))
        else:
            print(journal_mod.собрать(self.cfg))
        return 0

    def cmd_doctor(self, живой: bool = False) -> int:
        """Проверка готовности к партии (модуль questkit/doctor.py)."""
        отчёт = doctor.проверить(self.cfg, живой=живой)
        doctor.напечатать(отчёт)
        return 0 if отчёт.готово else 1

    def cmd_log(self, count: str = "15") -> int:
        try:
            limit = int(count)
        except (TypeError, ValueError):
            limit = 15
        events = self.events.all()[-limit:]
        if not events:
            print("журнал пуст")
            return 0
        print(ui.box("ЖУРНАЛ СОБЫТИЙ", [ui.event_line(e) for e in events], "жёлтый"))
        return 0

    # ---------------------------------------------------------------- диспетчер
    def dispatch(self, words: list[str], *, auto_yes: bool = False, note: str = "") -> int:
        if not words:
            return self.cmd_status()
        head, rest = words[0].lower(), words[1:]
        if head in ("помощь", "справка", "?", "help"):
            print(ui.box("ПУЛЬТ ВЕДУЩЕГО", HELP, "жёлтый"))
            return 0
        if head in ("комнаты", "возможности", "rooms"):
            return self.cmd_rooms()
        if head in ("действия", "actions"):
            if not rest:
                ui.error("укажите комнату: действия <комната>")
                return 1
            return self.cmd_actions(rest[0])
        if head in ("подтвердить", "событие", "применить"):
            if len(rest) < 2:
                ui.error("использование: подтвердить <комната> <действие> [пометка]")
                return 1
            return self.cmd_confirm(rest[0], rest[1], note or " ".join(rest[2:]), auto_yes)
        if head in ("откат", "отменить"):
            if len(rest) < 2:
                ui.error("использование: откат <комната> <действие>")
                return 1
            return self.cmd_revert(rest[0], rest[1], auto_yes)
        if head == "сброс":
            return self.cmd_reset(auto_yes)
        if head == "этап":
            return self.cmd_stage(rest[0] if rest else "")
        if head == "отношение":
            return self.cmd_attitude(rest[0] if rest else "")
        if head == "статус":
            return self.cmd_status()
        if head == "журнал":
            return self.cmd_log(rest[0] if rest else "15")
        if head in ("отчёт", "отчет"):
            return self.cmd_report(rest[0] if rest else "")
        if head in ("дополнения", "возможности_квеста"):
            print(ui.box("ДОПОЛНИТЕЛЬНЫЕ ВОЗМОЖНОСТИ",
                         features.описание_состояния(self.cfg)
                         + ["", "Изменить: python3 run_launcher.py"], "жёлтый"))
            return 0
        if head in ("проверка", "готовность"):
            живой = any(a in ("--живой", "--live") for a in rest)
            return self.cmd_doctor(живой)
        if head in ("выход", "exit", "quit"):
            # В интерактивном пульте выход перехватывает цикл; здесь — чтобы
            # команда из справки не выглядела неизвестной при разовом запуске.
            return 0
        ui.error(f"неизвестная команда: {head} (см. «помощь»)")
        return 1

    def run_interactive(self) -> int:
        lines = [
            "Пульт ведущего. Игрокам это окно не показывают.",
            "",
            "Действия комплекса применяются ТОЛЬКО отсюда и только после",
            f"явного подтверждения словом «{CONFIRM_WORD}».",
            "",
            "«помощь» — список команд, «выход» — закрыть пульт.",
        ]
        print(ui.box("КОМПЛЕКС объект-7 · ПУЛЬТ ВЕДУЩЕГО", lines, "жёлтый", "жирный"))
        self.cmd_status()
        while True:
            try:
                line = input(ui.c("пульт> ", "жёлтый", "жирный")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line.split()[0].lower() in ("выход", "exit", "quit"):
                break
            try:
                self.dispatch(line.split())
            except (EOFError, KeyboardInterrupt):
                print()
                continue
        print(ui.c("пульт закрыт", "тусклый"))
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_master.py",
        description="Пульт ведущего: подтверждение событий комплекса",
        epilog="без аргументов запускается интерактивный пульт",
    )
    parser.add_argument("слова", nargs="*", help="команда пульта, например: подтвердить первая_комната блокировка_двери")
    parser.add_argument("--конфиг", "--config", dest="config", default=None,
                        help="путь к файлу конфигурации")
    parser.add_argument("--да", "--yes", dest="yes", action="store_true",
                        help="подтвердить событие без вопроса (для разового запуска)")
    parser.add_argument("--живой", "--live", dest="live", action="store_true",
                        help="в команде «проверка» — сделать пробный запрос к модели")
    parser.add_argument("--пометка", "--note", dest="note", default="",
                        help="пометка к событию для журнала")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = config.load(args.config)
        console = MasterConsole(cfg)
    except (FileNotFoundError, config.ConfigError) as exc:
        ui.error(str(exc))
        return 2
    if args.слова:
        слова = list(args.слова)
        if args.live and слова[0] in ("проверка", "готовность"):
            слова.append("--живой")
        return console.dispatch(слова, auto_yes=args.yes, note=args.note)
    return console.run_interactive()


if __name__ == "__main__":
    sys.exit(main())
