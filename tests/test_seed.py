"""Генератор файловой системы-головоломки (раздел 2 ТЗ)."""

import base64
import gzip
import json
import subprocess
import tarfile
import unittest
import zipfile
from pathlib import Path

from entropy import config
from entropy.seed import MARKER, Seeder

from .helpers import QuestTestCase


class TestSeeder(QuestTestCase):
    def setUp(self):
        super().setUp()
        self.seeder = Seeder(config.data_file(self.load_config(), "scenario"), self.root)

    def test_раскладка_и_проверка(self):
        созданные = self.seeder.seed()
        self.assertTrue(созданные)
        ok, bad = self.seeder.verify()
        self.assertEqual(bad, [])
        self.assertEqual(len(ok), len(self.seeder.files))
        self.assertTrue((self.root / MARKER).exists())

    def test_повторная_раскладка_для_новой_партии(self):
        """Раздел 2 ТЗ: важна возможность собрать раскладку заново."""
        self.seeder.seed()
        (self.root / "архив" / "опись.txt").write_text("испорчено игроками", encoding="utf-8")
        (self.root / "мусор.txt").write_text("следы прошлой партии", encoding="utf-8")
        self.seeder.seed(overwrite=True)
        ok, bad = self.seeder.verify()
        self.assertEqual(bad, [])
        self.assertFalse((self.root / "мусор.txt").exists())

    def test_настоящие_сигнатуры_форматов(self):
        """Переименованные файлы должны опознаваться утилитой file."""
        self.seeder.seed()
        self.assertEqual((self.root / "архив" / "схема_секции.dat").read_bytes()[:8],
                         b"\x89PNG\r\n\x1a\n")
        self.assertEqual((self.root / "архив" / "опись.txt").read_bytes()[:2], b"\x1f\x8b")
        self.assertEqual((self.root / "архив" / "вложение.log").read_bytes()[:4], b"PK\x03\x04")
        self.assertTrue(tarfile.is_tarfile(self.root / "серверная" / "резерв.tar"))

    def test_головоломки_решаются_штатными_средствами(self):
        self.seeder.seed()
        # gzip под чужим именем
        with gzip.open(self.root / "архив" / "опись.txt", "rt", encoding="utf-8") as fh:
            self.assertIn("ОПИСЬ НОСИТЕЛЕЙ", fh.read())
        # base64
        текст = base64.b64decode((self.root / "архив" / "протокол_5.b64").read_text()).decode()
        self.assertIn("Энтропия", текст)  # то, что разум отрицает
        # zip
        with zipfile.ZipFile(self.root / "архив" / "вложение.log") as архив:
            self.assertIn("докладная.txt", архив.namelist())
        # tar
        with tarfile.open(self.root / "серверная" / "резерв.tar") as архив:
            self.assertIn("допуск_лаборатории.txt", архив.getnames())
        # построчный реверс: rev вернёт исходный текст
        строки = (self.root / "лаборатория_Б" / "код_внешней_двери.txt").read_text(
            encoding="utf-8").splitlines()
        self.assertIn("Код внешней гермодвери: 4718", [s[::-1] for s in строки])
        # перестановка строк: tac вернёт исходный порядок
        маршрут = (self.root / "коридор_3" / "маршрут_обхода.txt").read_text(
            encoding="utf-8").splitlines()
        self.assertTrue(маршрут[-1].startswith("МАРШРУТ ОБХОДА"))

    def test_код_двери_виден_внутри_картинки(self):
        """Запасной путь: strings по PNG показывает заметку чертёжника."""
        self.seeder.seed()
        данные = (self.root / "архив" / "схема_секции.dat").read_bytes()
        self.assertIn("четыре разряда".encode("utf-8"), данные)

    def test_права_доступа_выставляются(self):
        self.seeder.seed()
        дело = self.root / "архив" / "личное_дело_К.txt"
        self.assertEqual(oct(дело.stat().st_mode & 0o777), "0o0")

    def test_xor_разбирается_обратно(self):
        """Тип xor в наборе есть, хотя базовый сценарий его не использует."""
        сценарий = self.tmp / "xor.json"
        сценарий.write_text(json.dumps({
            "корень": str(self.tmp / "xor-корень"),
            "файлы": [{"путь": "тайна.bin", "тип": "xor", "ключ": 42,
                       "строки": ["код 4718"]}],
        }, ensure_ascii=False), encoding="utf-8")
        seeder = Seeder(сценарий)
        seeder.seed()
        сырые = (Path(seeder.root) / "тайна.bin").read_bytes()
        self.assertEqual(bytes(b ^ 42 for b in сырые).decode("utf-8").strip(), "код 4718")

    def test_шпаргалка_содержит_разгадки(self):
        текст = self.seeder.cheatsheet()
        self.assertIn("схема_секции.dat", текст)
        self.assertIn("4718", текст)
        self.assertIn("chmod", текст)

    # ---------------------------------------------------------- защита очистки
    def test_очистка_требует_подтверждения(self):
        self.seeder.seed()
        self.assertFalse(self.seeder.wipe(confirmed=False))
        self.assertTrue(self.root.exists())
        self.assertTrue(self.seeder.wipe(confirmed=True))
        self.assertFalse(self.root.exists())

    def test_без_маркера_ничего_не_удаляется(self):
        """Защита от «run_seed.py очистить --корень ~» по ошибке."""
        чужой = self.tmp / "чужой-каталог"
        (чужой / "важное").mkdir(parents=True)
        (чужой / "важное" / "файл.txt").write_text("не трогать", encoding="utf-8")
        seeder = Seeder(config.data_file(self.load_config(), "scenario"), чужой)
        self.assertFalse(seeder.wipe(confirmed=True))
        self.assertTrue((чужой / "важное" / "файл.txt").exists())

    def test_нельзя_удалить_домашний_каталог(self):
        seeder = Seeder(config.data_file(self.load_config(), "scenario"), Path.home())
        self.assertFalse(seeder.wipe(confirmed=True))
        self.assertTrue(Path.home().exists())

    def test_неизвестный_тип_файла_не_роняет_раскладку(self):
        сценарий = self.tmp / "странный.json"
        сценарий.write_text(json.dumps({
            "корень": str(self.tmp / "странный-корень"),
            "файлы": [
                {"путь": "хороший.txt", "тип": "текст", "строки": ["всё в порядке"]},
                {"путь": "плохой.bin", "тип": "голограмма", "строки": ["?"]},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        seeder = Seeder(сценарий)
        созданные = seeder.seed()
        self.assertEqual(len(созданные), 1)
        self.assertTrue((Path(seeder.root) / "хороший.txt").exists())


class TestSeedCli(QuestTestCase):
    """Проверка запуска через командную строку."""

    def test_разложить_проверить_очистить(self):
        сценарий = config.data_file(self.load_config(), "scenario")
        общее = ["python3", "-m", "entropy.seed", "--сценарий", str(сценарий),
                 "--корень", str(self.root)]
        for команда, ожидаемый_код in (("разложить", 0), ("проверить", 0)):
            готово = subprocess.run(общее[:3] + [команда] + общее[3:],
                                    capture_output=True, text=True)
            self.assertEqual(готово.returncode, ожидаемый_код, готово.stderr)
        отказ = subprocess.run(общее[:3] + ["очистить"] + общее[3:],
                               capture_output=True, text=True)
        self.assertEqual(отказ.returncode, 1)
        self.assertTrue(self.root.exists())
        успех = subprocess.run(общее[:3] + ["очистить"] + общее[3:] + ["--да"],
                               capture_output=True, text=True)
        self.assertEqual(успех.returncode, 0)
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()


class TestКороткаяРаскладка(QuestTestCase):
    """Второй сценарий: генератор должен быть пригоден не только для одного."""

    def сеятель(self):
        сценарий = self.data / "scenario" / "short.json"
        if not сценарий.exists():
            import shutil as sh
            sh.copy(Path(__file__).resolve().parent.parent / "data" / "scenario" / "short.json",
                    сценарий)
        return Seeder(сценарий, self.root, self.constants())

    def test_раскладывается_и_проверяется(self):
        seeder = self.сеятель()
        созданные = seeder.seed()
        self.assertEqual(len(созданные), 9)
        ok, bad = seeder.verify()
        self.assertEqual(bad, [])

    def test_ключевые_файлы_этапов_на_месте(self):
        """Иначе пришлось бы править ещё и карту этапов."""
        self.сеятель().seed()
        for путь in ("шлюз/журнал_шлюза.log", "архив/схема_секции.dat"):
            self.assertTrue((self.root / путь).exists(), путь)

    def test_головоломки_решаются(self):
        import base64 as b64
        import gzip as gz
        seeder = self.сеятель()
        seeder.seed()
        with gz.open(self.root / "архив" / "опись.txt", "rt", encoding="utf-8") as fh:
            self.assertIn("ОПИСЬ НОСИТЕЛЕЙ", fh.read())
        текст = b64.b64decode((self.root / "архив" / "протокол_5.b64").read_text()).decode()
        self.assertIn("Энтропия", текст)
        строки = (self.root / "серверная" / "код_внешней_двери.txt").read_text(
            encoding="utf-8").splitlines()
        код = self.constants()["код_двери"]
        self.assertTrue(any(код in с[::-1] for с in строки))

    def test_константы_подставлены(self):
        """В файлах игроков не должно остаться «{{код_двери}}»."""
        seeder = self.сеятель()
        seeder.seed()
        текстовые = {"текст", "записка", "журнал", "реверс", "перестановка_строк"}
        проверено = 0
        for запись in seeder.files:
            if запись.get("тип", "текст") not in текстовые:
                continue     # gzip, zip, tar и png читать как текст бессмысленно
            файл = self.root / запись["путь"]
            self.assertNotIn("{{", файл.read_text(encoding="utf-8"), запись["путь"])
            проверено += 1
        self.assertGreater(проверено, 0)
