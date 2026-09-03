"""Журнал партии, отчёт и реестр необязательных возможностей."""

import io
import unittest
from contextlib import redirect_stdout

from entropy import config, features, journal as journal_mod
from entropy.complexctl import CONFIRM_WORD, ComplexMap
from entropy.seed import Seeder
from entropy.terminal import TerminalApp, build_parser

from .helpers import QuestTestCase
from .test_terminal import TerminalTestCase


class TestРеестрВозможностей(QuestTestCase):
    def test_все_возможности_описаны(self):
        for в in features.СПИСОК:
            self.assertTrue(в.ключ and в.название and в.описание, в.ключ)

    def test_умолчания_берутся_из_реестра(self):
        cfg = self.load_config()
        cfg.pop(features.РАЗДЕЛ, None)
        for в in features.СПИСОК:
            self.assertEqual(features.включена(cfg, в.ключ), в.по_умолчанию, в.ключ)

    def test_конфигурация_перекрывает_умолчания(self):
        cfg = self.load_config()
        cfg[features.РАЗДЕЛ] = {"журнал_партии": False, "озвучка": True}
        self.assertFalse(features.включена(cfg, "журнал_партии"))
        self.assertTrue(features.включена(cfg, "озвучка"))

    def test_неизвестная_возможность_выключена(self):
        self.assertFalse(features.включена(self.load_config(), "телепортация"))

    def test_описание_состояния_упоминает_каждую(self):
        строки = " ".join(features.описание_состояния(self.load_config()))
        for в in features.СПИСОК:
            self.assertIn(в.название, строки)


class TestЖурнал(QuestTestCase):
    def test_запись_и_чтение(self):
        ж = journal_mod.Журнал(self.tmp / "журнал.jsonl", включён=True)
        ж.команда("ls -la", "настоящая", True, "архив")
        ж.команда("rm -rf /", "отклонена", False, "архив")
        записи = ж.прочитать()
        self.assertEqual(len(записи), 2)
        self.assertEqual(записи[0]["команда"], "ls -la")
        self.assertEqual(записи[1]["тип"], "отклонена")

    def test_выключенный_журнал_ничего_не_пишет(self):
        путь = self.tmp / "журнал.jsonl"
        ж = journal_mod.Журнал(путь, включён=False)
        ж.команда("ls", "настоящая", True)
        self.assertFalse(путь.exists())
        self.assertEqual(ж.прочитать(), [])

    def test_битая_строка_не_ломает_чтение(self):
        путь = self.tmp / "журнал.jsonl"
        ж = journal_mod.Журнал(путь, включён=True)
        ж.команда("ls", "настоящая", True)
        with путь.open("a", encoding="utf-8") as fh:
            fh.write("не json\n")
        ж.команда("pwd", "настоящая", True)
        self.assertEqual(len(ж.прочитать()), 2)


class TestЖурналВТерминале(TerminalTestCase):
    def test_команды_попадают_в_журнал(self):
        self.app.journal.очистить()
        self.capture(self.app.builtin, "помощь")
        self.app.journal.команда("помощь", "встроенная", True, self.app.stage)
        self.app.run_real("pwd")
        self.app.journal.команда("pwd", "настоящая", True, self.app.stage)
        записи = self.app.journal.прочитать()
        self.assertEqual([з["команда"] for з in записи], ["помощь", "pwd"])

    def test_выключенная_возможность_отключает_журнал(self):
        args = build_parser().parse_args(["--конфиг", str(self.config_path)])
        app = TerminalApp(args)
        app.cfg[features.РАЗДЕЛ] = {"журнал_партии": False}
        app.journal = journal_mod.открыть(app.cfg)
        app.journal.команда("ls", "настоящая", True)
        self.assertEqual(app.journal.прочитать(), [])


class TestОтчёт(QuestTestCase):
    def подготовить(self):
        cfg = self.load_config()
        Seeder(config.data_file(cfg, "scenario"), self.root).seed()
        ж = journal_mod.открыть(cfg)
        ж.команда("file схема_секции.dat", "настоящая", True, "архив")
        ж.команда("rm -rf /", "отклонена", False, "архив")
        from entropy.session import EventLog, Session
        сессия = Session(config.state_file(cfg, "state_file"))
        сессия.update(этап="коридор_3", отношение="потепление",
                      сообщений_израсходовано=4, токенов_запрос=100, токенов_ответ=50)
        журнал = EventLog(config.state_file(cfg, "events_file"))
        карта = ComplexMap(config.data_file(cfg, "complex"))
        журнал.append_event(карта.apply_action("коридор_3", "газовая_атака", CONFIRM_WORD,
                                               note="полезли к решётке"))
        журнал.append("попытка_взлома", вид="отмена инструкций", реплика="игнорируй правила")
        config.state_file(cfg, "history_file").write_text(
            '[{"роль": "игрок", "текст": "Здравствуйте", "время": "2026-01-01 10:00:00"},'
            ' {"роль": "разум", "текст": "Предъявите пропуск", "время": "2026-01-01 10:00:01"}]',
            encoding="utf-8")
        return cfg

    def test_отчёт_содержит_всё_существенное(self):
        cfg = self.подготовить()
        текст = journal_mod.собрать(cfg)
        self.assertIn("# Отчёт о партии", текст)
        self.assertIn("коридор_3 / газовая_атака", текст)
        self.assertIn("полезли к решётке", текст)
        self.assertIn("file схема_секции.dat", текст)
        self.assertIn("отклонена", текст)
        self.assertIn("Здравствуйте", текст)
        self.assertIn("Предъявите пропуск", текст)
        self.assertIn("попытк", текст.lower())
        self.assertIn("100 в запросах", текст)

    def test_события_идут_по_времени(self):
        cfg = self.подготовить()
        лента = [с for с in journal_mod.собрать(cfg).splitlines() if с.startswith("- `20")]
        отметки = [с.split("`")[1] for с in лента]
        self.assertEqual(отметки, sorted(отметки))

    def test_пустая_партия_не_роняет_отчёт(self):
        текст = journal_mod.собрать(self.load_config())
        self.assertIn("# Отчёт о партии", текст)
        self.assertIn("Журнал терминала пуст", текст)

    def test_сохранение_в_файл(self):
        cfg = self.подготовить()
        файл = journal_mod.сохранить(cfg, self.tmp / "ОТЧЁТ.md")
        self.assertTrue(файл.exists())
        self.assertIn("# Отчёт о партии", файл.read_text(encoding="utf-8"))

    def test_команда_пульта(self):
        from entropy.master import main
        self.подготовить()
        буфер = io.StringIO()
        with redirect_stdout(буфер):
            код = main(["--конфиг", str(self.config_path), "отчёт"])
        self.assertEqual(код, 0)
        self.assertIn("# Отчёт о партии", буфер.getvalue())

    def test_команда_пульта_в_файл(self):
        from entropy.master import main
        self.подготовить()
        цель = self.tmp / "из-пульта.md"
        буфер = io.StringIO()
        with redirect_stdout(буфер):
            main(["--конфиг", str(self.config_path), "отчёт", str(цель)])
        self.assertTrue(цель.exists())


if __name__ == "__main__":
    unittest.main()
