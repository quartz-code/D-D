"""Конфигурация и хранение ключа API (раздел 9.6 ТЗ)."""

import json
import os
import unittest

from questkit import config

from .helpers import QuestTestCase


class TestConfig(QuestTestCase):
    def test_умолчания_доступны_без_файла(self):
        cfg = config.load(self.tmp / "нет-такого.json")
        self.assertEqual(cfg["deepseek"]["model"], "deepseek-chat")
        self.assertFalse(cfg["_конфиг_найден"])

    def test_файл_перекрывает_только_свои_ключи(self):
        cfg = self.load_config()
        self.assertEqual(cfg["chat"]["delay_min_sec"], 0)          # из файла
        self.assertEqual(cfg["chat"]["limit_messages"],
                         config.DEFAULTS["chat"]["limit_messages"])  # из умолчаний

    def test_битый_json_даёт_понятную_ошибку(self):
        broken = self.tmp / "битый.json"
        broken.write_text("{не json", encoding="utf-8")
        with self.assertRaises(config.ConfigError):
            config.load(broken)

    def test_ключ_из_переменной_окружения_важнее_файла(self):
        path = self.tmp / "с-ключом.json"
        path.write_text(json.dumps({"deepseek": {"api_key": "из-файла",
                                                 "api_key_env": "ТЕСТ_КЛЮЧ"}}), encoding="utf-8")
        cfg = config.load(path)
        self.assertEqual(config.api_key(cfg), "из-файла")
        os.environ["ТЕСТ_КЛЮЧ"] = "из-окружения"
        self.addCleanup(os.environ.pop, "ТЕСТ_КЛЮЧ", None)
        self.assertEqual(config.api_key(cfg), "из-окружения")

    def test_ключ_не_показывается_целиком(self):
        masked = config.mask_key("sk-abcdef1234567890")
        self.assertNotIn("abcdef1234", masked)
        self.assertTrue(masked.endswith("7890"))
        self.assertEqual(config.mask_key(""), "(не задан)")

    def test_ключа_нет_в_исходном_коде(self):
        """Ключ не должен быть захардкожен нигде в пакете."""
        from questkit import paths
        for path in (paths.PROJECT_ROOT / "entropy").glob("*.py"):
            self.assertNotIn("sk-", path.read_text(encoding="utf-8"),
                             f"похоже на ключ в {path.name}")


if __name__ == "__main__":
    unittest.main()
