"""Файл возможностей и подтверждение событий (разделы 6.2 и 7 ТЗ)."""

import json
import unittest

from questkit import config
from questkit.world import (CONFIRM_WORD, ComplexMap, ConfirmationRequired,
                                UnknownAction, UnknownRoom)

from .helpers import QuestTestCase


class TestComplexMap(QuestTestCase):
    def setUp(self):
        super().setUp()
        self.cmap = ComplexMap(config.data_file(self.load_config(), "world"))

    def test_минимальный_формат_из_тз(self):
        """Формат из ТЗ (комнаты на верхнем уровне) должен читаться как есть."""
        path = self.tmp / "минимальный.json"
        path.write_text(json.dumps({
            "коридор_3": {"действия": ["газовая_атака", "блокировка_двери"],
                          "состояние": "неактивно"}
        }, ensure_ascii=False), encoding="utf-8")
        cmap = ComplexMap(path)
        self.assertEqual(list(cmap.rooms), ["коридор_3"])
        self.assertIn("газовая_атака", cmap.actions("коридор_3"))
        self.assertEqual(cmap.state("коридор_3"), "неактивно")

    def test_без_подтверждения_ничего_не_меняется(self):
        before = self.cmap.path.read_text(encoding="utf-8")
        for bad in ("", "да ладно", "yes", "нет", None):
            with self.assertRaises(ConfirmationRequired):
                self.cmap.apply_action("коридор_3", "газовая_атака", bad)
        self.assertEqual(self.cmap.path.read_text(encoding="utf-8"), before)
        self.assertEqual(self.cmap.state("коридор_3"), "неактивно")

    def test_подтверждение_применяет_и_пишет_на_диск(self):
        event = self.cmap.apply_action("коридор_3", "газовая_атака", CONFIRM_WORD,
                                       note="проверка")
        self.assertEqual(event["тип"], "действие_подтверждено")
        self.assertTrue(event["боевое"])
        self.assertEqual(self.cmap.state("коридор_3"), "активно")
        # состояние переживает перечитывание файла другим окном
        again = ComplexMap(self.cmap.path)
        self.assertIn("газовая_атака", again.active_actions("коридор_3"))
        self.assertEqual(again.room("коридор_3")["история"][-1]["результат"], "применено")

    def test_подтверждение_нечувствительно_к_регистру(self):
        self.cmap.apply_action("коридор_3", "газовая_атака", "да")
        self.assertEqual(self.cmap.state("коридор_3"), "активно")

    def test_откат_возвращает_неактивно(self):
        self.cmap.apply_action("коридор_3", "газовая_атака", CONFIRM_WORD)
        self.cmap.apply_action("коридор_3", "блокировка_двери", CONFIRM_WORD)
        self.cmap.revert_action("коридор_3", "газовая_атака", CONFIRM_WORD)
        self.assertEqual(self.cmap.active_actions("коридор_3"), ["блокировка_двери"])
        self.assertEqual(self.cmap.state("коридор_3"), "активно")
        self.cmap.revert_action("коридор_3", "блокировка_двери", CONFIRM_WORD)
        self.assertEqual(self.cmap.state("коридор_3"), "неактивно")

    def test_откат_и_сброс_тоже_требуют_подтверждения(self):
        self.cmap.apply_action("коридор_3", "газовая_атака", CONFIRM_WORD)
        with self.assertRaises(ConfirmationRequired):
            self.cmap.revert_action("коридор_3", "газовая_атака", "нет")
        with self.assertRaises(ConfirmationRequired):
            self.cmap.reset("нет")
        self.assertEqual(self.cmap.state("коридор_3"), "активно")

    def test_сброс_очищает_все_комнаты(self):
        self.cmap.apply_action("коридор_3", "газовая_атака", CONFIRM_WORD)
        self.cmap.apply_action("шлюз", "блокировка_двери", CONFIRM_WORD)
        self.cmap.reset(CONFIRM_WORD)
        self.assertEqual(self.cmap.all_active(), [])

    def test_неизвестные_комнаты_и_действия(self):
        with self.assertRaises(UnknownRoom):
            self.cmap.apply_action("подвал", "газовая_атака", CONFIRM_WORD)
        with self.assertRaises(UnknownAction):
            self.cmap.apply_action("коридор_3", "ядерный_удар", CONFIRM_WORD)

    def test_снимок_нельзя_испортить_снаружи(self):
        """Чат работает со снимком: его правка не должна менять файл."""
        snapshot = self.cmap.snapshot()
        snapshot["комнаты"]["коридор_3"]["состояние"] = "активно"
        snapshot["комнаты"]["коридор_3"]["активные_действия"] = ["газовая_атака"]
        self.assertEqual(ComplexMap(self.cmap.path).state("коридор_3"), "неактивно")

    def test_боевые_и_небоевые_действия_различаются(self):
        self.assertTrue(self.cmap.is_combat("газовая_атака"))
        self.assertFalse(self.cmap.is_combat("выдача_кода"))


if __name__ == "__main__":
    unittest.main()


class TestПакетыВРепозитории(unittest.TestCase):
    """Файлы мира в пакетах должны быть чистыми шаблонами.

    Приложение пишет состояние партии прямо в них (так задано в ТЗ), поэтому
    после прогонов туда легко попадают «активно», история и отметки времени —
    и следующий ведущий получит квест с уже применённым действием.
    """

    def test_ни_один_пакет_не_содержит_следов_партий(self):
        import json
        from questkit import paths
        проверено = 0
        for каталог in (paths.TEMPLATES_DIR, paths.EXAMPLES_DIR):
            for файл in каталог.glob("*/world.json"):
                from questkit import schema
                данные = json.loads(файл.read_text(encoding="utf-8"))
                for имя, комната in schema.поле(данные, "комнаты", {}).items():
                    self.assertEqual(schema.канон_состояния(
                        schema.поле(комната, "состояние")), "неактивно",
                        f"{файл.parent.name}/{имя}")
                    for поле in ("активные_действия", "история", "обновлено"):
                        for написание in schema.имена(поле):
                            self.assertNotIn(написание, комната,
                                             f"{файл.parent.name}/{имя}: осталось «{написание}»")
                проверено += 1
        self.assertGreater(проверено, 0, "не найдено ни одного пакета")
