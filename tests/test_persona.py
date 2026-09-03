"""Системная настройка модели (разделы 5 и 6.1 ТЗ)."""

import unittest

from questkit import config, persona as persona_mod
from questkit.world import CONFIRM_WORD, ComplexMap

from .helpers import QuestTestCase


class TestPersona(QuestTestCase):
    def setUp(self):
        super().setUp()
        cfg = self.load_config()
        self.persona = persona_mod.Persona(config.data_file(cfg, "persona"))
        self.cmap = ComplexMap(config.data_file(cfg, "world"))

    def build(self, **kwargs) -> str:
        kwargs.setdefault("complex_snapshot", self.cmap.snapshot())
        return persona_mod.build_system_prompt(self.persona, **kwargs)

    def test_в_настройке_есть_все_правила_характера(self):
        prompt = self.build()
        for rule in self.persona.data["правила"]:
            self.assertIn(rule, prompt)

    def test_запрет_называть_организацию(self):
        prompt = self.build()
        self.assertIn("ЗАПРЕЩЁННЫЕ СЛОВА", prompt)
        self.assertIn("энтропия", prompt.lower())  # перечислено как запрет

    def test_отношение_меняет_настройку(self):
        hostile = self.build(attitude="враждебное")
        warm = self.build(attitude="потепление")
        self.assertIn("враждебное", hostile)
        self.assertNotIn("ТЕКУЩЕЕ ОТНОШЕНИЕ К ИГРОКАМ: потепление", hostile)
        self.assertIn("ТЕКУЩЕЕ ОТНОШЕНИЕ К ИГРОКАМ: потепление", warm)

    def test_неизвестное_отношение_откатывается_к_исходному(self):
        prompt = self.build(attitude="ехидное")
        self.assertIn(persona_mod.DEFAULT_ATTITUDE, prompt)

    def test_намёки_только_текущего_этапа(self):
        prompt = self.build(stage="архив")
        self.assertIn("Носитель, названный схемой, схемой не является", prompt)
        self.assertNotIn("Маховик снят со штока", prompt)  # намёк этапа «выход»

    def test_неприменённые_действия_только_как_угроза(self):
        prompt = self.build(stage="коридор_3")
        self.assertIn("НИ ОДНО ДЕЙСТВИЕ КОМПЛЕКСА НЕ ПРИМЕНЕНО", prompt)
        self.assertIn("газовая_атака", prompt)

    def test_подтверждённое_действие_переходит_в_свершившиеся(self):
        self.cmap.apply_action("коридор_3", "газовая_атака", CONFIRM_WORD)
        prompt = self.build(stage="коридор_3")
        self.assertIn("УЖЕ ПРИМЕНЕНО И ПОДТВЕРЖДЕНО", prompt)
        self.assertIn("коридор_3: газовая_атака", prompt.split("УЖЕ ПРИМЕНЕНО")[1])

    def test_раунд_молчания_добавляет_указание(self):
        self.assertIn("ГРУБОЙ", self.build(silent_round=True))
        self.assertNotIn("ГРУБОЙ", self.build(silent_round=False))


if __name__ == "__main__":
    unittest.main()
