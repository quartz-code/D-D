"""Озвучка реплик разума.

Настоящего синтезатора в проверочном окружении нет, поэтому запуск процесса
подменяется: проверяется, что команда собрана правильно и что отсутствие
синтезатора ничего не ломает.
"""

import subprocess
import unittest
from unittest import mock

from questkit import features, voice

from .helpers import QuestTestCase
from .test_chat import ChatTestCase


class TestПоискДвижка(QuestTestCase):
    def test_находит_первый_доступный(self):
        with mock.patch.object(voice.shutil, "which",
                               side_effect=lambda имя: "/usr/bin/espeak" if имя == "espeak" else None):
            self.assertEqual(voice.найти_движок(), ("espeak", "/usr/bin/espeak"))

    def test_предпочтительный_движок_вперёд(self):
        with mock.patch.object(voice.shutil, "which", side_effect=lambda имя: f"/usr/bin/{имя}"):
            self.assertEqual(voice.найти_движок("spd-say")[0], "spd-say")

    def test_ничего_не_найдено(self):
        with mock.patch.object(voice.shutil, "which", return_value=None):
            self.assertIsNone(voice.найти_движок())


class TestПодготовкаТекста(unittest.TestCase):
    def test_рамки_и_точки_не_произносятся(self):
        текст = voice.подготовить_текст("ВВОД КОДА ......... 4718 ────────")
        self.assertEqual(текст, "ВВОД КОДА 4718")

    def test_длинная_реплика_обрезается(self):
        self.assertEqual(len(voice.подготовить_текст("а" * 5000, предел=100)), 100)

    def test_пустая_реплика(self):
        self.assertEqual(voice.подготовить_текст("──── ..."), "")


class TestКоманда(unittest.TestCase):
    def test_espeak(self):
        команда = voice.собрать_команду("espeak-ng", "/usr/bin/espeak-ng", "Смена принята",
                                        скорость=140, высота=20)
        self.assertEqual(команда, ["/usr/bin/espeak-ng", "-v", "ru", "-s", "140",
                                   "-p", "20", "--", "Смена принята"])

    def test_spd_say_переводит_скорость_в_свой_диапазон(self):
        команда = voice.собрать_команду("spd-say", "/usr/bin/spd-say", "текст", скорость=250)
        self.assertIn("50", команда)

    def test_текст_передаётся_отдельным_аргументом(self):
        """Иначе реплика с кавычками или ; ушла бы в оболочку как команда."""
        опасный = "текст; rm -rf /"
        команда = voice.собрать_команду("espeak-ng", "/usr/bin/espeak-ng", опасный)
        self.assertIn(опасный, команда)


class TestГолос(QuestTestCase):
    def голос(self, cfg=None):
        cfg = cfg or self.load_config()
        with mock.patch.object(voice.shutil, "which",
                               side_effect=lambda имя: "/usr/bin/espeak-ng"
                               if имя == "espeak-ng" else None):
            return voice.Голос(cfg)

    def test_произносит_через_отдельный_процесс(self):
        г = self.голос()
        self.assertTrue(г.доступен)
        with mock.patch.object(subprocess, "Popen") as запуск:
            self.assertTrue(г.произнести("Предъявите пропуск"))
        команда = запуск.call_args[0][0]
        self.assertEqual(команда[0], "/usr/bin/espeak-ng")
        self.assertIn("Предъявите пропуск", команда)

    def test_без_синтезатора_ничего_не_происходит(self):
        with mock.patch.object(voice.shutil, "which", return_value=None):
            г = voice.Голос(self.load_config())
        self.assertFalse(г.доступен)
        with mock.patch.object(subprocess, "Popen",
                               side_effect=AssertionError("не должно запускаться")):
            self.assertFalse(г.произнести("Предъявите пропуск"))

    def test_сбой_запуска_не_роняет_игру(self):
        г = self.голос()
        with mock.patch.object(subprocess, "Popen", side_effect=OSError("нет прав")):
            self.assertFalse(г.произнести("текст"))

    def test_новая_реплика_обрывает_прежнюю(self):
        г = self.голос()
        процесс = mock.Mock()
        процесс.poll.return_value = None
        with mock.patch.object(subprocess, "Popen", return_value=процесс):
            г.произнести("первая")
            г.произнести("вторая")
        процесс.terminate.assert_called()

    def test_настройки_голоса_учитываются(self):
        cfg = self.load_config()
        cfg["voice"].update({"скорость": 120, "высота": 10, "голос": "ru+m3"})
        г = self.голос(cfg)
        with mock.patch.object(subprocess, "Popen") as запуск:
            г.произнести("текст")
        команда = запуск.call_args[0][0]
        self.assertIn("120", команда)
        self.assertIn("ru+m3", команда)


class TestОзвучкаВЧате(ChatTestCase):
    def test_по_умолчанию_выключена(self):
        self.assertIsNone(self.make_app().голос)

    def test_включается_настройкой_если_синтезатор_есть(self):
        import json
        данные = json.loads(self.config_path.read_text(encoding="utf-8"))
        данные[features.РАЗДЕЛ] = {"озвучка": True}
        self.config_path.write_text(json.dumps(данные, ensure_ascii=False), encoding="utf-8")
        with mock.patch.object(voice.shutil, "which", return_value="/usr/bin/espeak-ng"):
            app = self.make_app()
        self.assertIsNotNone(app.голос)

    def test_включена_но_синтезатора_нет_игра_идёт_молча(self):
        import json
        данные = json.loads(self.config_path.read_text(encoding="utf-8"))
        данные[features.РАЗДЕЛ] = {"озвучка": True}
        self.config_path.write_text(json.dumps(данные, ensure_ascii=False), encoding="utf-8")
        with mock.patch.object(voice.shutil, "which", return_value=None):
            app = self.make_app()
        self.assertIsNone(app.голос)
        вывод = self.capture(app.send, "Здравствуйте.")
        self.assertIn("распорядитель>", вывод, "переписка обязана работать без звука")

    def test_реплика_разума_произносится(self):
        app = self.make_app(reply="Предъявите пропуск установленного образца.")
        with mock.patch.object(voice.shutil, "which", return_value="/usr/bin/espeak-ng"):
            with mock.patch.object(subprocess, "Popen") as запуск:
                self.capture(app.toggle_voice, "вкл")
                self.capture(app.send, "Здравствуйте.")
        произнесённое = " ".join(" ".join(в[0][0]) for в in запуск.call_args_list)
        self.assertIn("Предъявите пропуск", произнесённое)

    def test_переключение_командой_ведущего(self):
        app = self.make_app()
        with mock.patch.object(voice.shutil, "which", return_value="/usr/bin/espeak-ng"):
            with mock.patch.object(subprocess, "Popen"):
                self.capture(app.toggle_voice, "вкл")
                self.assertIsNotNone(app.голос)
                self.capture(app.toggle_voice, "выкл")
                self.assertIsNone(app.голос)

    def test_включение_без_синтезатора_объясняет_причину(self):
        app = self.make_app()
        with mock.patch.object(voice.shutil, "which", return_value=None):
            вывод = self.capture(app.toggle_voice, "вкл")
        self.assertIn("espeak", вывод)
        self.assertIsNone(app.голос)


if __name__ == "__main__":
    unittest.main()
