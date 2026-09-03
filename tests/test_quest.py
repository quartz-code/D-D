"""Константы квеста: одно значение — и оно расходится по всем файлам."""

import json
import unittest

from entropy import config
from entropy.complexctl import ComplexMap
from entropy.persona import Persona
from entropy.quest import Constants
from entropy.seed import Seeder
from entropy.stages import Stages

from .helpers import QuestTestCase


class TestКонстанты(QuestTestCase):
    def test_подстановка_в_строках_и_вложенных_данных(self):
        c = self.constants()
        self.assertEqual(c.substitute("код {{код_двери}}"), f"код {c['код_двери']}")
        отрисовано = c.render({"а": ["{{объект}}"], "б": {"в": "{{смесь}}"}})
        self.assertEqual(отрисовано, {"а": [c["объект"]], "б": {"в": c["смесь"]}})

    def test_неизвестная_ссылка_остаётся_видимой(self):
        c = self.constants()
        self.assertEqual(c.substitute("{{нет_такого}}"), "{{нет_такого}}")
        self.assertEqual(c.missing("{{нет_такого}} {{объект}}"), {"нет_такого"})

    def test_нигде_не_осталось_незакрытых_ссылок(self):
        """Иначе игрок увидит в файле «{{код_двери}}» вместо кода."""
        c = self.constants()
        cfg = self.load_config()
        for имя in ("complex", "stages", "persona", "scenario"):
            данные = json.loads(config.data_file(cfg, имя).read_text(encoding="utf-8"))
            self.assertEqual(c.missing(данные), set(), f"в {имя} есть ссылка без значения")
        for файл in config.data_file(cfg, "canned_dir").glob("*.txt"):
            self.assertEqual(c.missing(файл.read_text(encoding="utf-8")), set(), файл.name)

    def test_пустой_набор_ничего_не_ломает(self):
        пустой = Constants.empty()
        self.assertEqual(пустой.substitute("код {{код_двери}}"), "код {{код_двери}}")

    def test_подстановка_включена_по_умолчанию(self):
        """Забыть передать константы нельзя: шаблон уехал бы к игрокам."""
        cfg = self.load_config()
        текст = Stages(config.data_file(cfg, "stages")).canned_text(
            {"файл": "exit_open.txt"}, config.data_file(cfg, "canned_dir"))
        self.assertNotIn("{{", текст)


class TestСменаКода(QuestTestCase):
    """Меняем код в одном файле — он обязан поменяться везде."""

    НОВЫЙ = "9042"

    def setUp(self):
        super().setUp()
        self.c = self.constants()
        self.старый = self.c["код_двери"]
        self.c.set("код_двери", self.НОВЫЙ)
        self.cfg = self.load_config()

    def test_команда_двери_принимает_новый_код(self):
        stages = Stages(config.data_file(self.cfg, "stages"), self.c)
        открыто = stages.scripted("выход", f"дверь --код {self.НОВЫЙ}")
        self.assertEqual(открыто.get("файл"), "exit_open.txt")
        отказ = stages.scripted("выход", f"дверь --код {self.старый}")
        self.assertEqual(отказ.get("файл"), "exit_denied.txt", "старый код должен отклоняться")

    def test_заготовка_ответа_показывает_новый_код(self):
        stages = Stages(config.data_file(self.cfg, "stages"), self.c)
        текст = stages.canned_text({"файл": "exit_open.txt"},
                                   config.data_file(self.cfg, "canned_dir"))
        self.assertIn(self.НОВЫЙ, текст)
        self.assertNotIn(self.старый, текст)

    def test_разложенные_файлы_содержат_новый_код(self):
        seeder = Seeder(config.data_file(self.cfg, "scenario"), self.root, self.c)
        seeder.seed()
        # записка с кодом (строки задом наперёд)
        строки = (self.root / "лаборатория_Б" / "код_внешней_двери.txt").read_text(
            encoding="utf-8").splitlines()
        расшифровано = [s[::-1] for s in строки]
        self.assertTrue(any(self.НОВЫЙ in s for s in расшифровано))
        self.assertFalse(any(self.старый in s for s in расшифровано))
        # заметка внутри картинки
        картинка = (self.root / "архив" / "схема_секции.dat").read_bytes()
        self.assertNotIn(self.старый.encode(), картинка)

    def test_картинка_рисует_новый_код(self):
        """Код нарисован пикселями — проверяем, что рисуется именно новый."""
        import struct
        import zlib
        from entropy.pngtext import render_text
        seeder = Seeder(config.data_file(self.cfg, "scenario"), self.root, self.c)
        seeder.seed()
        данные = (self.root / "архив" / "схема_секции.dat").read_bytes()
        поз, idat = 8, b""
        while поз < len(данные):
            длина = struct.unpack(">I", данные[поз:поз + 4])[0]
            тег = данные[поз + 4:поз + 8]
            if тег == b"IHDR":
                ширина, высота = struct.unpack(">II", данные[поз + 8:поз + 16])
            if тег == b"IDAT":
                idat += данные[поз + 8:поз + 8 + длина]
            поз += 12 + длина
        сырые = zlib.decompress(idat)
        пиксели = b"".join(сырые[y * (ширина + 1) + 1:(y + 1) * (ширина + 1)]
                           for y in range(высота))
        надписи = [n for n in seeder.scenario["файлы"]
                   if n["путь"].endswith("схема_секции.dat")][0]["надписи"]
        self.assertIn(self.НОВЫЙ, " ".join(надписи))
        ожидаемая, _, _ = render_text(надписи, scale=6)
        self.assertEqual(ширина, ожидаемая, "картинка перерисована под новый код")

    def test_разум_прячет_новый_код(self):
        from entropy import guard
        persona = Persona(config.data_file(self.cfg, "persona"), self.c)
        текст, заметки = guard.check_secrets(f"Комбинация: {self.НОВЫЙ}.", persona.secrets, set())
        self.assertNotIn(self.НОВЫЙ, текст)
        self.assertTrue(заметки)

    def test_шпаргалка_ведущего_с_новым_кодом(self):
        seeder = Seeder(config.data_file(self.cfg, "scenario"), self.root, self.c)
        self.assertIn(self.НОВЫЙ, seeder.cheatsheet())

    def test_случайный_код_сохраняется_и_расходится(self):
        новый = self.c.randomize_door_code()
        self.assertEqual(len(новый), 4)
        self.assertTrue(новый.isdigit())
        перечитанный = Constants(self.c.path)
        self.assertEqual(перечитанный["код_двери"], новый)
        stages = Stages(config.data_file(self.cfg, "stages"), перечитанный)
        self.assertIsNotNone(stages.scripted("выход", f"дверь --код {новый}"))


if __name__ == "__main__":
    unittest.main()
