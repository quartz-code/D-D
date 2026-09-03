"""Этапы и контекстная справка (разделы 3 и 4 ТЗ)."""

import json
import unittest

from questkit import config
from questkit.stages import Stages

from .helpers import QuestTestCase


class TestStages(QuestTestCase):
    def setUp(self):
        super().setUp()
        self.stages = Stages(config.data_file(self.load_config(), "stages"))

    def test_справка_контекстная_а_не_общая(self):
        """Главное требование раздела 3: команды только текущего этапа."""
        gate = self.stages.help_text("шлюз")
        archive = self.stages.help_text("архив")
        self.assertIn("шлюз --опрос", gate)
        self.assertNotIn("base64 -d", gate)      # это команда архива
        self.assertNotIn("вольер --статус", gate)  # это команда лаборатории
        self.assertIn("base64 -d", archive)
        self.assertNotIn("шлюз --опрос", archive)

    def test_всегда_доступные_команды_есть_на_каждом_этапе(self):
        for stage in self.stages.order:
            text = self.stages.help_text(stage)
            self.assertIn("помощь", text)
            self.assertIn("связь", text)

    def test_подсказка_мастеру_только_для_ведущего(self):
        self.assertNotIn("[мастеру]", self.stages.help_text("архив", gm=False))
        self.assertIn("[мастеру]", self.stages.help_text("архив", gm=True))

    def test_сценарная_команда_находится_по_шаблону(self):
        entry = self.stages.scripted("коридор_3", "вентиляция --статус")
        self.assertIsNotNone(entry)
        text = self.stages.canned_text(entry, config.data_file(self.load_config(), "canned_dir"))
        self.assertIn("ВЕНТИЛЯЦИОННЫЙ УЗЕЛ", text)
        self.assertIsNone(self.stages.scripted("шлюз", "вентиляция --статус"))

    def test_отсутствующая_заготовка_не_роняет_приложение(self):
        text = self.stages.canned_text({"файл": "нет-такого.txt"}, self.tmp)
        self.assertIn("нет файла заготовки", text)

    def test_переход_по_чтению_нужного_файла(self):
        self.assertEqual(self.stages.check_transition("шлюз", "cat журнал_шлюза.log"), "архив")
        self.assertEqual(self.stages.check_transition("шлюз", "less шлюз/журнал_шлюза.log"), "архив")
        self.assertIsNone(self.stages.check_transition("шлюз", "cat инструкция_по_режиму.txt"))
        self.assertIsNone(self.stages.check_transition("шлюз", "ls журнал_шлюза.log"))

    def test_неудачная_команда_не_двигает_этап(self):
        self.assertIsNone(self.stages.check_transition("шлюз", "cat журнал_шлюза.log",
                                                       success=False))

    def test_переход_по_шаблону_команды(self):
        self.assertEqual(self.stages.check_transition("архив", "file схема_секции.dat"),
                         "коридор_3")

    def test_переход_по_подтверждённому_событию(self):
        path = self.tmp / "этапы.json"
        path.write_text(json.dumps({
            "порядок": ["а", "б"],
            "этапы": {"а": {"переход": {"следующий": "б", "при_событии": ["открытие_клетки"]}},
                      "б": {}},
        }, ensure_ascii=False), encoding="utf-8")
        stages = Stages(path)
        событие = {"комната": "лаборатория_Б", "действие": "открытие_клетки"}
        self.assertEqual(stages.transition_on_event("а", событие), "б")
        self.assertIsNone(stages.transition_on_event("а", {"действие": "отключение_света"}))

    def test_последний_этап_никуда_не_ведёт(self):
        self.assertIsNone(self.stages.next_in_order(self.stages.order[-1]))
        self.assertIsNone(self.stages.check_transition("выход", "дверь --статус"))


if __name__ == "__main__":
    unittest.main()
