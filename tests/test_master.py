"""Пульт ведущего: единственный путь к изменению состояния (разделы 6.2, 8 ТЗ)."""

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from questkit import config
from questkit.world import ComplexMap
from questkit.master import MasterConsole, main

from .helpers import QuestTestCase


class MasterTestCase(QuestTestCase):
    def setUp(self):
        super().setUp()
        self.console = MasterConsole(self.load_config())

    @staticmethod
    def capture(func, *args, **kwargs):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            результат = func(*args, **kwargs)
        return результат, buffer.getvalue()


class TestMaster(MasterTestCase):
    def test_подтверждение_словом_да_применяет_действие(self):
        код, вывод = self.capture(self.console.cmd_confirm, "коридор_3", "газовая_атака",
                                  "пометка", True)
        self.assertEqual(код, 0)
        self.assertIn("БОЕВАЯ СИТУАЦИЯ", вывод)
        self.assertIn("ОТЛОЖИТЕ НОУТБУК", вывод)
        self.assertEqual(self.console.complex.state("коридор_3"), "активно")

    def test_отказ_от_подтверждения_ничего_не_меняет(self):
        with mock.patch("builtins.input", return_value="нет"):
            код, вывод = self.capture(self.console.cmd_confirm, "коридор_3", "газовая_атака")
        self.assertEqual(код, 1)
        self.assertIn("НЕ ПРИМЕНЕНО", вывод)
        self.assertEqual(ComplexMap(self.console.complex.path).state("коридор_3"), "неактивно")

    def test_ввод_да_на_вопрос_применяет(self):
        with mock.patch("builtins.input", return_value="ДА"):
            код, _ = self.capture(self.console.cmd_confirm, "шлюз", "блокировка_двери")
        self.assertEqual(код, 0)
        self.assertEqual(self.console.complex.state("шлюз"), "активно")

    def test_небоевое_действие_без_тревоги(self):
        _, вывод = self.capture(self.console.cmd_confirm, "серверная", "выдача_кода", "", True)
        self.assertNotIn("БОЕВАЯ СИТУАЦИЯ", вывод)
        self.assertIn("не боевое", вывод)

    def test_событие_попадает_в_журнал_для_соседних_окон(self):
        cursor = self.console.events.size()
        self.capture(self.console.cmd_confirm, "лаборатория_Б", "открытие_клетки", "", True)
        события, _ = self.console.events.tail(cursor)
        self.assertEqual(события[-1]["тип"], "действие_подтверждено")
        self.assertTrue(события[-1]["боевое"])

    def test_откат_и_сброс(self):
        self.capture(self.console.cmd_confirm, "коридор_3", "газовая_атака", "", True)
        self.capture(self.console.cmd_revert, "коридор_3", "газовая_атака", True)
        self.assertEqual(self.console.complex.state("коридор_3"), "неактивно")
        self.capture(self.console.cmd_confirm, "архив", "пожарная_тревога", "", True)
        self.capture(self.console.cmd_reset, True)
        self.assertEqual(self.console.complex.all_active(), [])

    def test_несуществующие_комнаты_и_действия(self):
        код, _ = self.capture(self.console.cmd_confirm, "подвал", "потоп", "", True)
        self.assertEqual(код, 1)
        код, _ = self.capture(self.console.cmd_actions, "подвал")
        self.assertEqual(код, 1)

    def test_этап_и_отношение_видны_другим_окнам(self):
        self.capture(self.console.cmd_stage, "серверная")
        self.capture(self.console.cmd_attitude, "потепление")
        self.assertEqual(self.console.session.get("этап"), "серверная")
        self.assertEqual(self.console.session.get("отношение"), "потепление")

    def test_отношение_шагами(self):
        self.capture(self.console.cmd_attitude, "теплее")
        self.assertEqual(self.console.session.get("отношение"), "нейтральное")
        self.capture(self.console.cmd_attitude, "холоднее")
        self.assertEqual(self.console.session.get("отношение"), "настороженное")

    def test_неизвестный_этап_отклоняется(self):
        код, _ = self.capture(self.console.cmd_stage, "чердак")
        self.assertEqual(код, 1)

    def test_разбор_команд_пульта(self):
        код, вывод = self.capture(self.console.dispatch, ["комнаты"])
        self.assertEqual(код, 0)
        self.assertIn("коридор_3", вывод)
        код, _ = self.capture(self.console.dispatch, ["подтвердить", "коридор_3"])
        self.assertEqual(код, 1, "неполная команда должна отклоняться")
        код, _ = self.capture(self.console.dispatch, ["чепуха"])
        self.assertEqual(код, 1)

    def test_разовый_запуск_из_командной_строки(self):
        _, вывод = self.capture(
            main, ["--конфиг", str(self.config_path), "--да",
                   "подтвердить", "коридор_3", "газовая_атака"])
        self.assertIn("БОЕВАЯ СИТУАЦИЯ", вывод)
        self.assertEqual(ComplexMap(self.console.complex.path).state("коридор_3"), "активно")

    def test_разовый_запуск_без_да_не_применяет(self):
        with mock.patch("builtins.input", return_value=""):
            код, _ = self.capture(main, ["--конфиг", str(self.config_path),
                                         "подтвердить", "коридор_3", "газовая_атака"])
        self.assertEqual(код, 1)
        self.assertEqual(ComplexMap(self.console.complex.path).state("коридор_3"), "неактивно")


if __name__ == "__main__":
    unittest.main()


class TestИменаКоманд(MasterTestCase):
    """Имена команд пульта не должны перекрывать друг друга."""

    def test_возможности_это_комнаты_а_дополнения_это_галочки(self):
        _, комнаты = self.capture(self.console.dispatch, ["возможности"])
        self.assertIn("коридор_3", комнаты)
        _, дополнения = self.capture(self.console.dispatch, ["дополнения"])
        self.assertIn("Журнал партии", дополнения)
        self.assertNotIn("коридор_3", дополнения)

    def test_каждая_команда_из_справки_отзывается(self):
        """Опечатка в имени команды не должна выясняться посреди партии."""
        from questkit.master import справка
        for строка in справка():
            имя = строка.split()[0]
            with self.subTest(команда=имя):
                # Команды подтверждения спрашивают ведущего — отвечаем «нет».
                with mock.patch("builtins.input", return_value="нет"):
                    код, вывод = self.capture(self.console.dispatch, [имя])
                self.assertNotIn("неизвестная команда", вывод,
                                 f"команда «{имя}» не отзывается")
