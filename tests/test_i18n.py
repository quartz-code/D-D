"""Двуязычность: ключи данных и язык интерфейса."""

import json
import os
import unittest
from unittest import mock

from questkit import config, features, i18n, paths, schema
from questkit.persona import Persona, build_system_prompt
from questkit.seed import Seeder
from questkit.stages import Stages
from questkit.world import CONFIRM_WORD, ComplexMap

from .helpers import QuestTestCase


class TestКлючиДанных(unittest.TestCase):
    """Пакет можно писать русскими или английскими ключами."""

    def test_синоним_читается_с_обеих_сторон(self):
        self.assertEqual(schema.поле({"комнаты": 1}, "комнаты"), 1)
        self.assertEqual(schema.поле({"rooms": 1}, "комнаты"), 1)
        self.assertEqual(schema.поле({"rooms": 1}, "rooms"), 1)

    def test_умолчание_когда_ключа_нет(self):
        self.assertEqual(schema.поле({}, "комнаты", "—"), "—")
        self.assertFalse(schema.есть({}, "комнаты"))

    def test_язык_словаря_определяется(self):
        self.assertEqual(schema.язык({"комнаты": {}, "действия": []}), "ru")
        self.assertEqual(schema.язык({"rooms": {}, "actions": []}), "en")

    def test_запись_на_языке_словаря(self):
        русский = {"действия": []}
        schema.записать(русский, "состояние", "активно")
        self.assertIn("состояние", русский)
        английский = {"actions": []}
        schema.записать(английский, "состояние", "active")
        self.assertIn("state", английский)

    def test_состояние_приводится_к_канону(self):
        self.assertEqual(schema.канон_состояния("active"), "активно")
        self.assertEqual(schema.канон_состояния("активно"), "активно")

    def test_типы_файлов_на_двух_языках(self):
        self.assertEqual(schema.тип_файла("reversed"), "реверс")
        self.assertEqual(schema.тип_файла("реверс"), "реверс")


class TestАнглийскийПакет(QuestTestCase):
    """Полностью английский пакет должен играться так же, как русский."""

    def пакет(self):
        место = self.tmp / "en-pack"
        (место / "canned").mkdir(parents=True)
        (место / "pack.json").write_text(json.dumps({
            "name": "Test Quest", "language": "en",
            "terminal": {"prompt": "site-7", "title": "SITE-7 CONSOLE"},
            "chat": {"speaker": "warden"}}), encoding="utf-8")
        (место / "constants.json").write_text(json.dumps({"door_code": "7788"}), encoding="utf-8")
        (место / "world.json").write_text(json.dumps({
            "rooms": {"corridor": {"actions": ["gas", "lockdown"], "state": "inactive"}},
            "action_details": {"gas": {"description": "Gas", "combat": True,
                                       "phrases": ["gas", "valve"]},
                               "lockdown": {"description": "Lock", "combat": True}}}),
            encoding="utf-8")
        (место / "stages.json").write_text(json.dumps({
            "order": ["gate", "exit"],
            "always": [{"command": "help", "description": "commands here"}],
            "stages": {
                "gate": {"title": "Airlock", "description": "Way in.",
                         "commands": [{"command": "ls", "description": "list files"}],
                         "scripted": [{"pattern": "^probe$", "file": "probe.txt"}],
                         "transition": {"next": "exit", "on_file_read": ["log.txt"]}},
                "exit": {"title": "Exit", "commands": []}}}), encoding="utf-8")
        (место / "persona.json").write_text(json.dumps({
            "designation": "duty warden",
            "rules": ["Never leave character."],
            "attitude": {"wary": {"description": "Intruders.", "tone": "Dry."}},
            "secrets": [{"value": "{{door_code}}", "unlocked_by": "hint",
                         "replacement": "[classified]"}],
            "hints_by_stage": {"gate": ["Signatures matter more than names."]},
            "hedges": ["Regulations allow it."]}), encoding="utf-8")
        (место / "layout.json").write_text(json.dumps({
            "title": "English layout", "root": str(self.root), "marker": ".quest",
            "directories": ["archive"],
            "files": [
                {"path": "archive/log.txt", "type": "log", "lines": ["day 1"],
                 "solution": "Background."},
                {"path": "archive/note.txt", "type": "reversed",
                 "lines": ["Door code: {{door_code}}"]},
                {"path": "archive/index.txt", "type": "gzip", "lines": ["compressed"]},
                {"path": "archive/map.dat", "type": "png",
                 "captions": ["KOD: {{door_code}}"], "notes": {"Opis": "the map"}}]}),
            encoding="utf-8")
        (место / "canned" / "probe.txt").write_text("PROBE OK, code {{door_code}}\n",
                                                    encoding="utf-8")
        return место

    def test_этапы_и_справка(self):
        место = self.пакет()
        stages = Stages(место / "stages.json")
        self.assertEqual(stages.order, ["gate", "exit"])
        справка = stages.help_text("gate")
        self.assertIn("list files", справка)
        self.assertIn("commands here", справка)

    def test_сценарная_команда_и_константы(self):
        место = self.пакет()
        stages = Stages(место / "stages.json")
        запись = stages.scripted("gate", "probe")
        self.assertEqual(stages.canned_text(запись, место / "canned"), "PROBE OK, code 7788")

    def test_переход_этапа(self):
        место = self.пакет()
        self.assertEqual(Stages(место / "stages.json").check_transition("gate", "cat log.txt"),
                         "exit")

    def test_мир_и_подтверждение(self):
        место = self.пакет()
        world = ComplexMap(место / "world.json")
        self.assertEqual(world.actions("corridor"), ["gas", "lockdown"])
        self.assertTrue(world.is_combat("gas"))
        world.apply_action("corridor", "gas", CONFIRM_WORD)
        self.assertEqual(world.state("corridor"), "активно")
        сохранённое = json.loads((место / "world.json").read_text(encoding="utf-8"))
        self.assertEqual(сохранённое["rooms"]["corridor"]["state"], "active",
                         "в английском пакете состояние должно быть английским")

    def test_характер_и_секреты(self):
        место = self.пакет()
        persona = Persona(место / "persona.json")
        world = ComplexMap(место / "world.json")
        prompt = build_system_prompt(persona, attitude="wary", stage="gate",
                                     complex_snapshot=world.snapshot())
        self.assertIn("duty warden", prompt)
        self.assertIn("Signatures matter", prompt)
        from questkit import guard
        текст, заметки = guard.check_secrets("The code is 7788.", persona.secrets, set())
        self.assertNotIn("7788", текст)
        self.assertTrue(заметки)

    def test_реплики_берутся_из_пакета(self):
        from questkit import guard
        место = self.пакет()
        реплики = guard.Реплики(Persona(место / "persona.json").data)
        self.assertEqual(реплики.уклончивые, ["Regulations allow it."])

    def test_раскладка(self):
        место = self.пакет()
        seeder = Seeder(место / "layout.json")
        созданные = seeder.seed()
        self.assertEqual(len(созданные), 4)
        ok, bad = seeder.verify()
        self.assertEqual(bad, [])
        строки = (self.root / "archive" / "note.txt").read_text(encoding="utf-8").splitlines()
        self.assertIn("Door code: 7788", [с[::-1] for с in строки])
        self.assertEqual((self.root / "archive" / "map.dat").read_bytes()[:4], b"\x89PNG")


class TestЯзыкИнтерфейса(QuestTestCase):
    def tearDown(self):
        i18n.установить("ru")
        super().tearDown() if hasattr(super(), "tearDown") else None

    def test_каталоги_совпадают_по_ключам(self):
        """Забытый перевод — это молча русская строка в английском окне."""
        ru, en = i18n.ключи("ru"), i18n.ключи("en")
        self.assertEqual(ru - en, set(), "нет английского перевода для этих ключей")
        self.assertEqual(en - ru, set(), "нет русского оригинала для этих ключей")

    def test_каталоги_не_пусты(self):
        self.assertGreater(len(i18n.ключи("ru")), 100)

    def test_переключение_языка(self):
        i18n.установить("ru")
        русский = i18n.t("doctor.title")
        i18n.установить("en")
        self.assertNotEqual(i18n.t("doctor.title"), русский)

    def test_подстановки(self):
        i18n.установить("ru")
        self.assertIn("5", i18n.t("launcher.seeded", число=5, count=5))
        i18n.установить("en")
        self.assertIn("5", i18n.t("launcher.seeded", число=5, count=5))

    def test_неизвестный_ключ_возвращается_как_есть(self):
        self.assertEqual(i18n.t("нет.такого"), "нет.такого")

    def test_неизвестный_язык_откатывается_к_русскому(self):
        self.assertEqual(i18n.установить("эльфийский"), "ru")

    def test_авто_по_локали(self):
        with mock.patch.dict(os.environ, {"LC_ALL": "en_US.UTF-8"}, clear=False):
            self.assertEqual(i18n.установить("auto"), "en")
        with mock.patch.dict(os.environ, {"LC_ALL": "ru_RU.UTF-8"}, clear=False):
            self.assertEqual(i18n.установить("auto"), "ru")

    def test_язык_берётся_из_настроек(self):
        cfg = self.load_config()
        cfg["ui"]["language"] = "en"
        self.assertEqual(i18n.init(cfg), "en")

    def test_возможности_переводятся(self):
        i18n.установить("en")
        self.assertEqual(features.СПИСОК[0].название, "Party journal")
        i18n.установить("ru")
        self.assertEqual(features.СПИСОК[0].название, "Журнал партии")

    def test_в_каталогах_нет_пустых_строк(self):
        for язык in ("ru", "en"):
            for ключ, значение in i18n.каталог(язык).items():
                self.assertTrue(значение.strip(), f"{язык}: пустой перевод «{ключ}»")

    def test_подстановки_совпадают_в_переводах(self):
        """Если в русской строке есть {число}, в английской должно быть {count}."""
        import re
        поля = lambda с: set(re.findall(r"\{(\w+)\}", с))
        for ключ in i18n.ключи("ru"):
            русские, английские = поля(i18n.каталог("ru")[ключ]), поля(i18n.каталог("en")[ключ])
            self.assertEqual(len(русские), len(английские),
                             f"{ключ}: разное число подстановок")


if __name__ == "__main__":
    unittest.main()
