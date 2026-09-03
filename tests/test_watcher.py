"""Живое оповещение о событиях."""

import io
import time
import unittest
from contextlib import redirect_stdout

from entropy import config, features
from entropy.complexctl import CONFIRM_WORD, ComplexMap
from entropy.session import EventLog
from entropy.watcher import Наблюдатель

from .helpers import QuestTestCase
from .test_terminal import TerminalTestCase


class TestНаблюдатель(QuestTestCase):
    def журнал(self) -> EventLog:
        return EventLog(self.tmp / "события.jsonl")

    def test_ловит_события_появившиеся_после_запуска(self):
        журнал = self.журнал()
        пойманные = []
        with Наблюдатель(журнал, пойманные.append, интервал=0.05):
            журнал.append("этап", этап="архив")
            крайний_срок = time.time() + 5
            while not пойманные and time.time() < крайний_срок:
                time.sleep(0.02)
        self.assertEqual(len(пойманные), 1)
        self.assertEqual(пойманные[0]["этап"], "архив")

    def test_старые_события_не_показываются(self):
        """Иначе при запуске окна вываливалась бы вся прошлая партия."""
        журнал = self.журнал()
        журнал.append("этап", этап="шлюз")
        пойманные = []
        наблюдатель = Наблюдатель(журнал, пойманные.append, интервал=0.05)
        наблюдатель.проверить()
        self.assertEqual(пойманные, [])

    def test_разбор_по_требованию_без_потока(self):
        журнал = self.журнал()
        пойманные = []
        наблюдатель = Наблюдатель(журнал, пойманные.append)
        журнал.append("отношение", отношение="потепление")
        self.assertEqual(len(наблюдатель.проверить()), 1)
        self.assertEqual(наблюдатель.проверить(), [], "повторно те же не выдаются")

    def test_ошибка_обработчика_не_роняет_поток(self):
        журнал = self.журнал()
        сбои = []

        def падучий(событие):
            сбои.append(событие)
            raise RuntimeError("что-то пошло не так")

        with Наблюдатель(журнал, падучий, интервал=0.05):
            журнал.append("этап", этап="архив")
            крайний_срок = time.time() + 5
            while not сбои and time.time() < крайний_срок:
                time.sleep(0.02)
        self.assertTrue(сбои, "обработчик должен был вызваться")

    def test_остановка_завершает_поток(self):
        наблюдатель = Наблюдатель(self.журнал(), lambda с: None, интервал=0.05)
        наблюдатель.запустить()
        поток = наблюдатель._поток
        наблюдатель.остановить()
        self.assertIsNone(наблюдатель._поток)
        self.assertFalse(поток.is_alive())

    def test_повторный_запуск_не_плодит_потоки(self):
        наблюдатель = Наблюдатель(self.журнал(), lambda с: None, интервал=0.05)
        наблюдатель.запустить()
        первый = наблюдатель._поток
        наблюдатель.запустить()
        self.assertIs(наблюдатель._поток, первый)
        наблюдатель.остановить()


class TestЖивоеОповещениеВТерминале(TerminalTestCase):
    def test_включено_по_умолчанию(self):
        self.assertIsNotNone(self.app.watcher)

    def test_выключается_настройкой(self):
        from entropy.terminal import TerminalApp, build_parser
        import json
        данные = json.loads(self.config_path.read_text(encoding="utf-8"))
        данные[features.РАЗДЕЛ] = {"живое_оповещение": False}
        self.config_path.write_text(json.dumps(данные, ensure_ascii=False), encoding="utf-8")
        app = TerminalApp(build_parser().parse_args(["--конфиг", str(self.config_path)]))
        self.assertIsNone(app.watcher)

    def test_сигнал_приходит_и_с_наблюдателем_и_без(self):
        """Событие из соседнего окна показывается в обоих режимах."""
        for живое in (True, False):
            with self.subTest(живое=живое):
                app = self.make_app()
                if not живое:
                    app.watcher = None
                cmap = ComplexMap(config.data_file(app.cfg, "complex"))
                cmap.reset(CONFIRM_WORD)
                событие = cmap.apply_action("коридор_3", "газовая_атака", CONFIRM_WORD)
                app.events.append_event(событие)
                вывод = self.capture(app.drain_events)
                self.assertIn("БОЕВАЯ СИТУАЦИЯ", вывод)

    def test_фоновый_поток_печатает_сигнал(self):
        app = self.make_app()
        self.assertIsNotNone(app.watcher)
        cmap = ComplexMap(config.data_file(app.cfg, "complex"))
        cmap.reset(CONFIRM_WORD)
        событие = cmap.apply_action("лаборатория_Б", "открытие_клетки", CONFIRM_WORD)
        буфер = io.StringIO()
        with redirect_stdout(буфер):
            app.watcher.интервал = 0.05
            app.watcher.запустить()
            app.events.append_event(событие)
            крайний_срок = time.time() + 5
            while "БОЕВАЯ СИТУАЦИЯ" not in буфер.getvalue() and time.time() < крайний_срок:
                time.sleep(0.02)
            app.watcher.остановить()
        self.assertIn("БОЕВАЯ СИТУАЦИЯ", буфер.getvalue())
        self.assertIn("открытие_клетки", буфер.getvalue())


if __name__ == "__main__":
    unittest.main()
