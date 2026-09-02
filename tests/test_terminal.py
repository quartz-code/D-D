"""Терминал-приложение (разделы 3, 4, 8 ТЗ)."""

import io
import unittest
from contextlib import redirect_stdout

from entropy import config
from entropy.complexctl import CONFIRM_WORD, ComplexMap
from entropy.seed import Seeder
from entropy.terminal import TerminalApp, build_parser

from .helpers import QuestTestCase


class TerminalTestCase(QuestTestCase):
    def setUp(self):
        super().setUp()
        Seeder(config.data_file(self.load_config(), "scenario"), self.root).seed()
        self.app = self.make_app()

    def make_app(self, *extra: str) -> TerminalApp:
        args = build_parser().parse_args(["--конфиг", str(self.config_path), *extra])
        return TerminalApp(args)

    @staticmethod
    def capture(func, *args, **kwargs) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            func(*args, **kwargs)
        return buffer.getvalue()


class TestTerminal(TerminalTestCase):
    def test_старт_с_первого_этапа_и_в_корне_квеста(self):
        self.assertEqual(self.app.stage, "шлюз")
        self.assertEqual(self.app.cwd, self.root)

    def test_справка_меняется_вместе_с_этапом(self):
        gate = self.capture(self.app.builtin, "помощь")
        self.app.set_stage("архив")
        archive = self.capture(self.app.builtin, "помощь")
        self.assertIn("шлюз --опрос", gate)
        self.assertNotIn("шлюз --опрос", archive)
        self.assertIn("base64 -d", archive)

    def test_настоящая_команда_выполняется(self):
        вывод = self.capture(self.app.run_real, "ls")
        # вывод дочернего процесса идёт напрямую в консоль, проверяем код возврата
        self.assertTrue(self.app.run_real("test -f ЧИТАТЬ_ПЕРВЫМ.txt"))
        self.assertFalse(self.app.run_real("test -f нет-такого-файла"))

    def test_переход_по_каталогам(self):
        self.app.change_dir("cd шлюз")
        self.assertEqual(self.app.cwd.name, "шлюз")
        self.app.change_dir("cd ..")
        self.assertEqual(self.app.cwd, self.root)
        вывод = self.capture(self.app.change_dir, "cd нет_такого_каталога")
        self.assertIn("нет такого каталога", вывод)

    def test_cd_не_выпускает_за_периметр_если_включено(self):
        self.app.cfg["terminal"]["restrict_to_root"] = True
        вывод = self.capture(self.app.change_dir, "cd /etc")
        self.assertIn("заблокирован", вывод)
        self.assertEqual(self.app.cwd, self.root)

    def test_сценарная_команда_подставляет_заготовку(self):
        self.app.set_stage("коридор_3")
        entry = self.app.stages.scripted(self.app.stage, "вентиляция --статус")
        вывод = self.capture(self.app.run_scripted, entry)
        self.assertIn("ВЕНТИЛЯЦИОННЫЙ УЗЕЛ К-3", вывод)
        self.assertIn("заготовки", вывод)  # пометка ведущему

    def test_опасные_команды_блокируются(self):
        for опасная in ("rm -rf /", "mkfs.ext4 /dev/sda1", "shutdown -h now",
                        "dd if=/dev/zero of=/dev/sda"):
            self.assertTrue(self.app.is_blocked(опасная), опасная)
        for обычная in ("rm файл.txt", "rm -rf ./временное", "ls -la", "cat опись.txt"):
            self.assertFalse(self.app.is_blocked(обычная), обычная)

    def test_режим_без_выполнения(self):
        app = self.make_app("--без-выполнения")
        вывод = self.capture(app.run_real, "ls")
        self.assertIn("ОТКАЗАНО", вывод)

    def test_автопереход_этапа_по_нужному_файлу(self):
        вывод = self.capture(self.app.maybe_advance, "cat шлюз/журнал_шлюза.log", True)
        self.assertEqual(self.app.stage, "архив")
        self.assertIn("ЭТАП: архив", вывод)

    def test_этап_виден_соседнему_окну(self):
        self.app.set_stage("серверная")
        соседнее = self.make_app()
        self.assertEqual(соседнее.stage, "серверная")

    def test_боевой_сигнал_приходит_из_соседнего_окна(self):
        """Раздел 8 ТЗ: подтверждение на пульте — сигнал в окне терминала."""
        cmap = ComplexMap(config.data_file(self.app.cfg, "complex"))
        событие = cmap.apply_action("лаборатория_Б", "открытие_клетки", CONFIRM_WORD)
        self.app.events.append_event(событие)
        вывод = self.capture(self.app.drain_events)
        self.assertIn("БОЕВАЯ СИТУАЦИЯ", вывод)
        self.assertIn("открытие_клетки", вывод)
        self.assertIn("ОТЛОЖИТЕ НОУТБУК", вывод)

    def test_небоевое_действие_не_поднимает_тревогу(self):
        cmap = ComplexMap(config.data_file(self.app.cfg, "complex"))
        событие = cmap.apply_action("серверная", "выдача_кода", CONFIRM_WORD)
        self.app.events.append_event(событие)
        вывод = self.capture(self.app.drain_events)
        self.assertNotIn("БОЕВАЯ СИТУАЦИЯ", вывод)

    def test_команда_связи_объясняет_как_позвать_разум(self):
        вывод = self.capture(self.app.builtin, "связь")
        self.assertIn("run_chat.py", вывод)

    def test_выход_завершает_работу(self):
        with self.assertRaises(SystemExit):
            self.app.builtin("выход")

    def test_локаль_для_дочерних_команд_utf8(self):
        """Иначе rev зависает на русском тексте в локали POSIX."""
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"LC_ALL": "", "LC_CTYPE": "POSIX", "LANG": "POSIX"},
                             clear=False):
            env = self.app.child_env()
            self.assertEqual(env["LC_ALL"], "C.UTF-8")

        # уже настроенную UTF-8-локаль ведущего не трогаем
        with mock.patch.dict(os.environ, {"LC_ALL": "ru_RU.UTF-8"}, clear=False):
            self.assertEqual(self.app.child_env()["LC_ALL"], "ru_RU.UTF-8")

        # и не вмешиваемся вовсе, если ведущий обнулил настройку
        self.app.cfg["terminal"]["locale"] = ""
        with mock.patch.dict(os.environ, {"LC_ALL": "", "LC_CTYPE": "POSIX"}, clear=False):
            self.assertEqual(self.app.child_env().get("LC_ALL"), "")


if __name__ == "__main__":
    unittest.main()
