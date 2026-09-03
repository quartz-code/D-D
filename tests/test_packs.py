"""Пакеты содержимого: движок отдельно, квесты отдельно."""

import json
import unittest

from questkit import config, launcher, pack as pack_mod, paths
from questkit.persona import Persona
from questkit.seed import Seeder
from questkit.stages import Stages
from questkit.world import ComplexMap

from .helpers import QuestTestCase


class TestМанифест(QuestTestCase):
    def test_читает_надписи_квеста(self):
        манифест = pack_mod.load(self.load_config())
        self.assertEqual(манифест.name, "Комплекс Энтропии")
        self.assertEqual(манифест.language, "ru")
        self.assertEqual(манифест.надпись("terminal", "prompt"), "12-К")

    def test_без_манифеста_берутся_умолчания(self):
        манифест = pack_mod.Манифест(self.tmp / "нет-такого.json")
        self.assertEqual(манифест.name, pack_mod.УМОЛЧАНИЯ["name"])
        self.assertTrue(манифест.надпись("chat", "speaker"))

    def test_битый_манифест_не_роняет_запуск(self):
        файл = self.tmp / "pack.json"
        файл.write_text("{не json", encoding="utf-8")
        self.assertEqual(pack_mod.Манифест(файл).name, pack_mod.УМОЛЧАНИЯ["name"])

    def test_недостающие_надписи_дополняются(self):
        файл = self.tmp / "pack.json"
        файл.write_text(json.dumps({"name": "Свой квест"}, ensure_ascii=False), encoding="utf-8")
        манифест = pack_mod.Манифест(файл)
        self.assertEqual(манифест.name, "Свой квест")
        self.assertTrue(манифест.надпись("terminal", "title"), "надпись взята из умолчаний")


class TestВсеПакетыИсправны(unittest.TestCase):
    """Каждый пакет в репозитории должен читаться движком."""

    def пакеты(self):
        места = []
        for каталог in (paths.TEMPLATES_DIR, paths.EXAMPLES_DIR):
            места += [м for м in sorted(каталог.iterdir()) if (м / "pack.json").exists()]
        return места

    def test_пакеты_найдены(self):
        self.assertGreaterEqual(len(self.пакеты()), 2)

    def test_каждый_пакет_полон_и_читается(self):
        for место in self.пакеты():
            with self.subTest(пакет=место.name):
                манифест = pack_mod.Манифест(место / "pack.json")
                self.assertTrue(манифест.name)
                self.assertIn(манифест.language, ("ru", "en"))
                world = ComplexMap(место / "world.json")
                self.assertTrue(world.rooms, "в мире нет ни одной комнаты")
                stages = Stages(место / "stages.json")
                self.assertTrue(stages.order, "не задан порядок этапов")
                persona = Persona(место / "persona.json")
                self.assertTrue(persona.attitudes, "не заданы ступени отношения")
                for файл in место.glob("layout*.json"):
                    self.assertTrue(Seeder(файл).files, f"{файл.name}: пустая раскладка")

    def test_каждая_сценарная_команда_находит_заготовку(self):
        for место in self.пакеты():
            with self.subTest(пакет=место.name):
                stages = Stages(место / "stages.json")
                for имя, данные in stages.stages.items():
                    for запись in данные.get("сценарные_команды", []):
                        файл = запись.get("файл")
                        if файл:
                            self.assertTrue((место / "canned" / файл).exists(),
                                            f"{имя}: нет заготовки {файл}")

    def test_в_пакетах_не_осталось_незакрытых_ссылок(self):
        from questkit.constants import Constants
        for место in self.пакеты():
            with self.subTest(пакет=место.name):
                константы = Constants(место / "constants.json")
                for файл in list(место.glob("*.json")) + list((место / "canned").glob("*.txt")):
                    if файл.name == "constants.json":
                        continue
                    содержимое = (json.loads(файл.read_text(encoding="utf-8"))
                                  if файл.suffix == ".json" else файл.read_text(encoding="utf-8"))
                    self.assertEqual(константы.missing(содержимое), set(), файл.name)


class TestДвижокБезКвеста(unittest.TestCase):
    """В коде движка не должно остаться содержимого конкретного квеста."""

    СЛЕДЫ = ("Энтропи", "12-К", "распорядител", "коридор_3", "лаборатория_Б",
             "газовая_атака", "4718")

    def test_в_модулях_нет_квестовых_строк(self):
        for файл in sorted((paths.PROJECT_ROOT / "questkit").glob("*.py")):
            текст = файл.read_text(encoding="utf-8")
            for след in self.СЛЕДЫ:
                self.assertNotIn(след, текст, f"{файл.name}: осталось «{след}»")


class TestВыборПакета(QuestTestCase):
    def test_находит_шаблоны_и_примеры(self):
        пакеты = launcher.найти_пакеты()
        self.assertTrue(any(п.это_шаблон for п in пакеты), "не найден ни один шаблон")
        self.assertTrue(any(not п.это_шаблон for п in пакеты), "не найден ни один пример")

    def test_шаблоны_идут_первыми(self):
        пакеты = launcher.найти_пакеты()
        первый_пример = next(i for i, п in enumerate(пакеты) if not п.это_шаблон)
        self.assertTrue(all(п.это_шаблон for п in пакеты[:первый_пример]))

    def test_выбор_записывается_в_настройки(self):
        путь = self.tmp / "config.json"
        пакеты = launcher.найти_пакеты()
        launcher.выбрать_пакет(пакеты[-1], путь)
        cfg = config.load(путь)
        self.assertEqual(cfg["content"], пакеты[-1].ссылка)
        self.assertEqual(pack_mod.load(cfg).name, пакеты[-1].название)

    def test_смена_пакета_не_трогает_остальные_настройки(self):
        путь = self.tmp / "config.json"
        путь.write_text(json.dumps({"deepseek": {"api_key": "мой-ключ"}}), encoding="utf-8")
        launcher.выбрать_пакет(launcher.найти_пакеты()[0], путь)
        self.assertEqual(json.loads(путь.read_text(encoding="utf-8"))["deepseek"]["api_key"],
                         "мой-ключ")

    def test_движок_играет_любой_пакет(self):
        """Главная проверка шаблонности: код не привязан к «Энтропии»."""
        for пакет in launcher.найти_пакеты():
            with self.subTest(пакет=пакет.ссылка):
                cfg = config.load(self.config_path)
                cfg["content"] = str(пакет.путь)
                stages = Stages(config.data_file(cfg, "stages"))
                манифест = pack_mod.load(cfg)
                self.assertTrue(stages.help_text(stages.first()))
                self.assertTrue(манифест.надпись("terminal", "prompt"))


if __name__ == "__main__":
    unittest.main()


class TestСвойПакетНеТеряется(QuestTestCase):
    """Ведущий со своим квестом не должен быть молча переключён на чужой."""

    def test_свой_пакет_остаётся_в_списке(self):
        cfg = self.load_config()          # content указывает на временную копию
        пакеты = launcher.список_пакетов(cfg)
        self.assertEqual(пакеты[0].ссылка, str(self.data),
                         "свой пакет обязан быть первым в списке")

    def test_свой_пакет_не_подменяется_при_сохранении(self):
        путь = self.config_path
        было = json.loads(путь.read_text(encoding="utf-8"))["content"]
        launcher.сохранить({"озвучка": False}, путь)
        стало = json.loads(путь.read_text(encoding="utf-8"))["content"]
        self.assertEqual(было, стало)

    def test_каталог_без_манифеста_тоже_виден(self):
        свой = self.tmp / "мой-квест"
        свой.mkdir()
        cfg = self.load_config()
        cfg["content"] = str(свой)
        self.assertEqual(launcher.список_пакетов(cfg)[0].ссылка, str(свой))
