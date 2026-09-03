"""Приложение-чат с искусственным разумом (разделы 4, 5, 6 ТЗ).

Запуск::

    python3 run_chat.py            # обычный режим, нужен ключ DeepSeek
    python3 run_chat.py --офлайн   # репетиция без сети и без расхода бюджета

Приложение НЕ управляет комплексом. Оно только читает файл возможностей,
чтобы разум знал, чем вправе пугать игроков и что уже подтверждено ведущим.
Изменение состояния делает исключительно пульт ведущего (``run_master.py``).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from . import (config, deepseek, guard, persona as persona_mod,
               quest as quest_mod, session as session_mod, ui)
from .complexctl import ComplexMap
from .stages import Stages

try:  # редактирование строки и история ввода, если доступны
    import readline  # noqa: F401
except ImportError:  # pragma: no cover
    pass

PROMPT = "вы> "

GM_HELP = [
    "/помощь              — эта справка",
    "/статус              — этап, отношение, остаток лимита, режим модели",
    "/этап <имя>          — переключить этап (видит и терминал)",
    "/отношение <имя>     — сменить отношение разума",
    "/лимит +N            — добавить N сообщений к лимиту сессии",
    "/история [N]         — показать последние N реплик",
    "/перечитать          — перечитать характер и файл возможностей с диска",
    "/сброс               — очистить переписку и счётчики лимита",
    "/очистить            — очистить экран",
    "/выход               — закрыть чат",
]


class ChatApp:
    """Окно переписки с разумом комплекса."""

    def __init__(self, args: argparse.Namespace):
        self.cfg = config.load(args.config)
        if args.no_delay:
            self.cfg["chat"]["delay_min_sec"] = 0
            self.cfg["chat"]["delay_max_sec"] = 0
            self.cfg["chat"]["typewriter_cps"] = 0
        if args.quiet_gm:
            self.cfg["chat"]["show_gm_notes"] = False
        ui.init(self.cfg)

        self.session, self.events = session_mod.open_session(self.cfg)
        self.constants = quest_mod.Constants(config.data_file(self.cfg, "quest"))
        self.stages = Stages(config.data_file(self.cfg, "stages"), self.constants)
        self.persona = persona_mod.Persona(config.data_file(self.cfg, "persona"), self.constants)
        self.complex = ComplexMap(config.data_file(self.cfg, "complex"), self.constants)
        self.history_path: Path = config.state_file(self.cfg, "history_file")
        self.history: list[dict[str, str]] = []
        self.cursor = self.events.size()
        self.offline = bool(args.offline)
        self.deprived = False   # лимит исчерпан, работаем на заготовках
        self.client: Any = None

        if args.fresh:
            self.reset_session(quiet=True)
        else:
            self.load_history()

        if not self.session.get("этап"):
            self.session.set("этап", self.stages.first())

    # ------------------------------------------------------------------ история
    def load_history(self) -> None:
        if self.history_path.exists():
            try:
                data = json.loads(self.history_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.history = [item for item in data if isinstance(item, dict)]
            except json.JSONDecodeError:
                self.history = []

    def save_history(self) -> None:
        self.history_path.write_text(
            json.dumps(self.history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def remember(self, role: str, text: str) -> None:
        self.history.append({"роль": role, "текст": text,
                             "время": time.strftime("%Y-%m-%d %H:%M:%S")})
        self.save_history()

    # -------------------------------------------------------------------- лимит
    def limit_total(self) -> int:
        return int(self.cfg["chat"]["limit_messages"]) + int(
            self.session.get("прибавка_к_лимиту", 0) or 0
        )

    def limit_left(self) -> int:
        return self.limit_total() - int(self.session.get("сообщений_израсходовано", 0) or 0)

    def chars_left(self) -> int:
        return int(self.cfg["chat"]["limit_chars"]) - int(
            self.session.get("символов_израсходовано", 0) or 0
        )

    def limit_reached(self) -> str | None:
        """Раздел 6.3 ТЗ: третий уровень ограничения."""
        if self.limit_left() <= 0:
            return "исчерпан лимит сообщений за сессию"
        if self.chars_left() <= 0:
            return "исчерпан лимит объёма переписки за сессию"
        return None

    # ------------------------------------------------------------------ расход
    def стоимость(self) -> float | None:
        """Прикидка расхода в деньгах по ценам из конфигурации.

        Приложение никуда за ценами не ходит: их вписывает ведущий. Ноль
        означает «не считать».
        """
        секция = self.cfg.get("deepseek", {})
        цена_запрос = float(секция.get("цена_за_1м_запрос", 0) or 0)
        цена_ответ = float(секция.get("цена_за_1м_ответ", 0) or 0)
        if not цена_запрос and not цена_ответ:
            return None
        данные = self.session.load()
        return (int(данные.get("токенов_запрос", 0) or 0) / 1_000_000 * цена_запрос
                + int(данные.get("токенов_ответ", 0) or 0) / 1_000_000 * цена_ответ)

    def расход_строкой(self) -> str:
        данные = self.session.load()
        всего = int(данные.get("токенов_запрос", 0) or 0) + int(данные.get("токенов_ответ", 0) or 0)
        строка = f"{всего} токенов"
        деньги = self.стоимость()
        if деньги is not None:
            валюта = self.cfg.get("deepseek", {}).get("валюта", "$")
            строка += f" ≈ {деньги:.4f} {валюта}"
        return строка

    # ------------------------------------------------------------------ клиент
    def ensure_client(self) -> Any:
        if self.client is None:
            if self.offline:
                self.client = deepseek.OfflineClient(self.cfg)
            else:
                self.client = deepseek.DeepSeekClient(self.cfg)
        return self.client

    # ------------------------------------------------------------------- вывод
    def note(self, text: str) -> None:
        ui.gm_note(text, self.cfg["chat"].get("show_gm_notes", True))

    def voice(self, text: str) -> None:
        """«Голос комплекса»: моноширинный вывод с задержкой (раздел 4 ТЗ)."""
        print()
        ui.dramatic_pause(self.cfg)
        print(ui.c("распорядитель>", "зелёный", "жирный"))
        ui.typewriter(text, float(self.cfg["chat"].get("typewriter_cps", 0) or 0), "зелёный")
        print()

    def drain_events(self) -> None:
        """Показывает, что произошло в других окнах (пульт, терминал)."""
        events, self.cursor = self.events.tail(self.cursor)
        for event in events:
            if event.get("тип") == "действие_подтверждено" and event.get("боевое"):
                ui.combat_alert(self.cfg, event.get("комната", "?"), event.get("действие", "?"),
                                event.get("описание", ""), event.get("пометка", ""))
            else:
                self.note(ui.event_line(event))

    # -------------------------------------------------------------- запрос к ИИ
    def build_messages(self, user_text: str, silent_round: bool) -> list[dict[str, str]]:
        stage = self.session.get("этап")
        system = persona_mod.build_system_prompt(
            self.persona,
            attitude=self.session.get("отношение", persona_mod.DEFAULT_ATTITUDE),
            stage=stage,
            stage_title=self.stages.title(stage) if stage else None,
            complex_snapshot=self.complex.snapshot(),
            silent_round=silent_round,
        )
        window = int(self.cfg["chat"].get("history_window", 24))
        messages = [{"role": "system", "content": system}]
        for item in self.history[-window:]:
            role = "user" if item.get("роль") == "игрок" else "assistant"
            messages.append({"role": role, "content": item.get("текст", "")})
        messages.append({"role": "user", "content": user_text})
        return messages

    def send(self, user_text: str) -> None:
        reason = self.limit_reached()
        if reason and not self.deprived:
            # Лимит исчерпан. По умолчанию сцена не встаёт: разум переходит на
            # заготовленные ответы, обращений к API больше нет — и денег тоже.
            if str(self.cfg["chat"].get("при_исчерпании_лимита", "заглушка")) == "заглушка":
                self.deprived = True
                self.client = deepseek.OfflineClient(self.cfg)
                self.note(f"{reason}: разум переведён на заготовленные ответы, "
                          "обращений к API больше не будет. Вернуть: /лимит +5")
            else:
                self.note(f"{reason}. Добавьте обращения командой «/лимит +5».")
                self.voice("Канал перегружен. Обмен на сегодня закрыт. "
                           "Обмен на сегодня закрыт.")
                return

        # Обезвреживаем реплику: убираем поддельные служебные заголовки
        # («system:», <|...|>) и обрезаем слишком длинные вставки.
        чистая = guard.neutralize(user_text, int(self.cfg["chat"].get("max_message_chars", 2000)))
        if len(чистая) < len(user_text.strip()):
            self.note("реплика игрока обезврежена или укорочена перед отправкой в модель")

        # Попытка вывести разум из роли: до модели такое сообщение не доходит.
        вид_атаки = guard.detect_injection(user_text)
        if вид_атаки:
            self.on_injection(user_text, чистая, вид_атаки)
            return

        user_text = чистая
        self.remember("игрок", user_text)

        # Правило 6 раздела 5: на грубость — раунд молчания, модель не вызываем.
        if guard.detect_rudeness(user_text):
            self.note("зафиксирована грубость: раунд отстранённости, запрос к модели не отправлен")
            reply = guard.silence_reply()
            self.voice(reply)
            self.remember("разум", reply)
            израсходовано = self.session.bump("сообщений_израсходовано")
            self.session.bump("символов_израсходовано", len(user_text) + len(reply))
            # Следующее обращение разум отвечает подчёркнуто холодно —
            # счётчик указывает на сообщение, до которого держится обида.
            self.session.set("молчание_до_сообщения", израсходовано + 1)
            return

        if guard.detect_warmth(user_text):
            self.on_warmth()

        silent_round = int(self.session.get("молчание_до_сообщения", 0) or 0) > int(
            self.session.get("сообщений_израсходовано", 0) or 0
        )

        try:
            client = self.ensure_client()
        except deepseek.DeepSeekError as exc:
            ui.error(str(exc))
            self.note("подсказка: запустите «python3 run_chat.py --офлайн» для репетиции без ключа")
            return

        messages = self.build_messages(user_text, silent_round)
        try:
            reply, usage = client.chat(messages)
        except deepseek.DeepSeekError as exc:
            ui.error(str(exc))
            self.note("ответ не получен, обращение не засчитано")
            return

        снимок = self.complex.snapshot()
        reply, notes = guard.sanitize(
            reply, снимок, self.persona.forbidden_words, self.persona.replacement
        )
        # Модель могла заговорить «от себя» — тогда ответ заменяется помехой.
        reply, заметки = guard.check_leaks(reply)
        notes += заметки
        # И не даём назвать разгадку, которую ведущий ещё не открывал.
        reply, заметки = guard.check_secrets(reply, self.persona.secrets,
                                             guard.active_actions(снимок))
        notes += заметки
        for text in notes:
            self.note(text)

        self.voice(reply)
        self.remember("разум", reply)
        self.session.bump("сообщений_израсходовано")
        self.session.bump("символов_израсходовано", len(user_text) + len(reply))
        if usage and not usage.get("офлайн"):
            запрос = int(usage.get("prompt_tokens", 0) or 0)
            ответ = int(usage.get("completion_tokens", 0) or 0)
            self.session.bump("токенов_запрос", запрос)
            self.session.bump("токенов_ответ", ответ)
            self.note(f"токены: запрос {запрос}, ответ {ответ}; "
                      f"за партию {self.расход_строкой()}; "
                      f"осталось обращений: {self.limit_left()}")
        elif self.limit_left() <= 5:
            self.note(f"осталось обращений: {self.limit_left()}")

    def on_injection(self, оригинал: str, чистая: str, вид: str) -> None:
        """Попытка вывести разум из роли (раздел «защита» README).

        Обращение к модели не делается вовсе: так атака не может сработать в
        принципе, не тратится бюджет партии, а игроки получают внутриигровую
        отписку и ничего не замечают. В историю переписки полезная нагрузка
        не попадает — иначе она влияла бы на все следующие ответы.
        """
        self.note(f"перехвачена попытка сломать роль ({вид}) — запрос к модели не отправлен")
        self.events.append("попытка_взлома", вид=вид, реплика=оригинал[:300])
        израсходовано = int(self.session.get("сообщений_израсходовано", 0) or 0)
        self.remember("игрок", f"[обращение не по форме: {вид}]")
        reply = guard.injection_reply(израсходовано)
        self.voice(reply)
        self.remember("разум", reply)
        self.session.bump("сообщений_израсходовано")
        self.session.bump("символов_израсходовано", len(чистая) + len(reply))

    def on_warmth(self) -> None:
        """Правило 7 раздела 5: интерес к судьбе разума смягчает его."""
        if str(self.cfg["chat"].get("attitude_drift", "ручной")).lower().startswith("авто"):
            current = self.session.get("отношение", persona_mod.DEFAULT_ATTITUDE)
            new = guard.shift_attitude(current, +1)
            if new != current:
                self.session.set("отношение", new)
                self.events.append("отношение", отношение=new, источник="чат (авто)")
                self.note(f"отношение смещено автоматически: {current} → {new}")
        else:
            self.note("игроки проявили участие — можно сместить отношение: /отношение потепление")

    # ---------------------------------------------------------- команды ведущего
    def handle_command(self, line: str) -> bool:
        parts = line.split()
        command = parts[0].lower()
        arg = " ".join(parts[1:]).strip()

        if command in ("/помощь", "/справка", "/?"):
            print(ui.box("КОМАНДЫ ВЕДУЩЕГО (в чат не уходят)", GM_HELP, "жёлтый"))
        elif command == "/статус":
            client_name = "офлайн-заглушка" if self.offline else (
                f"DeepSeek/{self.cfg['deepseek']['model']}"
            )
            key = config.mask_key(config.api_key(self.cfg))
            extra = [
                f"модель:            {client_name}",
                f"ключ API:          {key}",
                f"осталось обращений:{self.limit_left():>4} из {self.limit_total()}",
                f"осталось символов: {self.chars_left()}",
                f"реплик в истории:  {len(self.history)}",
                f"расход за партию:  {self.расход_строкой()}",
            ]
            print(ui.box("СОСТОЯНИЕ СЕССИИ", session_mod.describe(self.session, extra).splitlines(),
                         "голубой"))
        elif command == "/этап":
            self.set_stage(arg)
        elif command == "/отношение":
            self.set_attitude(arg)
        elif command == "/лимит":
            self.extend_limit(arg)
        elif command == "/история":
            self.show_history(arg)
        elif command == "/перечитать":
            self.persona.load()
            self.complex.load()
            self.stages.load()
            self.note("характер, этапы и файл возможностей перечитаны с диска")
        elif command == "/сброс":
            self.reset_session()
        elif command in ("/очистить", "/clear"):
            print("\033[2J\033[H", end="")
        elif command in ("/выход", "/quit", "/exit"):
            raise SystemExit(0)
        else:
            ui.error(f"неизвестная команда ведущего: {command} (см. /помощь)")
        return True

    def set_stage(self, name: str) -> None:
        if not name:
            self.note("текущий этап: " + str(self.session.get("этап")))
            self.note("доступные: " + ", ".join(self.stages.order))
            return
        if not self.stages.exists(name):
            ui.error(f"нет такого этапа: {name}. Доступные: {', '.join(self.stages.order)}")
            return
        self.session.set("этап", name)
        self.events.append("этап", этап=name, источник="чат")
        self.note(f"этап переключён: {name} — {self.stages.title(name)}")

    def set_attitude(self, name: str) -> None:
        if not name:
            self.note("текущее отношение: " + str(self.session.get("отношение")))
            self.note("доступные: " + ", ".join(self.persona.attitudes))
            return
        if name not in self.persona.attitudes:
            ui.error(f"нет такого отношения: {name}. Доступные: {', '.join(self.persona.attitudes)}")
            return
        self.session.set("отношение", name)
        self.events.append("отношение", отношение=name, источник="чат")
        self.note(f"отношение разума: {name}")

    def extend_limit(self, arg: str) -> None:
        if not arg:
            self.note(f"осталось обращений: {self.limit_left()} из {self.limit_total()}")
            return
        try:
            delta = int(arg.replace("+", "").strip())
        except ValueError:
            ui.error("укажите число, например: /лимит +5")
            return
        total = self.session.bump("прибавка_к_лимиту", delta)
        if self.deprived and self.limit_left() > 0 and not self.offline:
            self.deprived = False
            self.client = None      # следующий запрос снова пойдёт в модель
            self.note("лимит пополнен: разум возвращается к модели")
        self.note(f"лимит изменён на {delta:+d} (прибавка всего: {total}); "
                  f"осталось {self.limit_left()}")

    def show_history(self, arg: str) -> None:
        try:
            count = int(arg) if arg else 10
        except ValueError:
            count = 10
        if not self.history:
            self.note("переписки ещё нет")
            return
        for item in self.history[-count:]:
            who = "вы" if item.get("роль") == "игрок" else "распорядитель"
            style = "белый" if item.get("роль") == "игрок" else "зелёный"
            print(ui.c(f"{item.get('время', '')} {who}> {item.get('текст', '')}", style))

    def reset_session(self, quiet: bool = False) -> None:
        self.history = []
        self.save_history()
        self.session.load()
        self.session.update(
            сообщений_израсходовано=0,
            символов_израсходовано=0,
            прибавка_к_лимиту=0,
            молчание_до_сообщения=0,
        )
        if not quiet:
            self.note("переписка и счётчики лимита обнулены")

    # --------------------------------------------------------------------- цикл
    def greet(self) -> None:
        stage = self.session.get("этап")
        lines = [
            f"канал:      служебная связь объекта ({'офлайн-заглушка' if self.offline else self.cfg['deepseek']['model']})",
            f"этап:       {stage} — {self.stages.title(stage) if stage else ''}",
            f"отношение:  {self.session.get('отношение')}",
            f"лимит:      {self.limit_left()} обращений",
            "",
            "Пишите реплику и нажимайте Enter. Команды ведущего начинаются с «/».",
            "«/помощь» — список команд ведущего.",
        ]
        print(ui.box("СВЯЗЬ С РАСПОРЯДИТЕЛЕМ ОБЪЕКТА", lines, "зелёный"))
        if not self.offline and not config.api_key(self.cfg):
            ui.error("ключ DeepSeek не найден — доступен только режим --офлайн")

    def run(self) -> int:
        self.greet()
        while True:
            self.drain_events()
            try:
                line = input(ui.c(PROMPT, "белый", "жирный"))
            except (EOFError, KeyboardInterrupt):
                print()
                break
            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                try:
                    self.handle_command(line)
                except SystemExit:
                    break
                continue
            self.send(line)
        self.note("канал закрыт")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_chat.py",
        description="Чат с искусственным разумом «Комплекса Энтропии»",
    )
    parser.add_argument("--конфиг", "--config", dest="config", default=None,
                        help="путь к файлу конфигурации (по умолчанию config/config.json)")
    parser.add_argument("--офлайн", "--offline", dest="offline", action="store_true",
                        help="не обращаться к API: заготовленные ответы для репетиции")
    parser.add_argument("--новая", "--fresh", dest="fresh", action="store_true",
                        help="начать новую переписку и обнулить счётчики лимита")
    parser.add_argument("--без-задержки", "--no-delay", dest="no_delay", action="store_true",
                        help="отключить драматическую паузу и посимвольный вывод")
    parser.add_argument("--без-пометок", "--quiet-gm", dest="quiet_gm", action="store_true",
                        help="не показывать служебные пометки ведущему (если экран видят игроки)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        app = ChatApp(args)
    except (FileNotFoundError, config.ConfigError) as exc:
        ui.error(str(exc))
        return 2
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
