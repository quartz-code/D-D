"""Общее состояние партии и журнал событий."""

import unittest

from questkit import session as session_mod

from .helpers import QuestTestCase


class TestSession(QuestTestCase):
    def setUp(self):
        super().setUp()
        self.session, self.events = session_mod.open_session(self.load_config())

    def test_состояние_переживает_перезапуск(self):
        self.session.set("этап", "серверная")
        self.session.set("отношение", "потепление")
        другое_окно = session_mod.Session(self.session.path)
        self.assertEqual(другое_окно.get("этап"), "серверная")
        self.assertEqual(другое_окно.get("отношение"), "потепление")

    def test_соседнее_окно_не_затирает_чужие_ключи(self):
        """Два приложения пишут разные ключи одного файла состояния."""
        второе = session_mod.Session(self.session.path)
        self.session.set("этап", "архив")
        второе.set("отношение", "враждебное")
        итог = session_mod.Session(self.session.path)
        self.assertEqual(итог.get("этап"), "архив")
        self.assertEqual(итог.get("отношение"), "враждебное")

    def test_счётчики_лимита(self):
        self.assertEqual(self.session.bump("сообщений_израсходовано"), 1)
        self.assertEqual(self.session.bump("сообщений_израсходовано", 4), 5)

    def test_хвост_журнала_отдаёт_только_новое(self):
        cursor = self.events.size()
        self.events.append("этап", этап="архив", источник="тест")
        новые, cursor = self.events.tail(cursor)
        self.assertEqual(len(новые), 1)
        пусто, cursor = self.events.tail(cursor)
        self.assertEqual(пусто, [])
        self.events.append("отношение", отношение="потепление")
        ещё, _ = self.events.tail(cursor)
        self.assertEqual(len(ещё), 1)
        self.assertEqual(ещё[0]["отношение"], "потепление")

    def test_готовое_событие_пишется_целиком(self):
        событие = {"тип": "действие_подтверждено", "комната": "коридор_3",
                   "действие": "газовая_атака", "боевое": True}
        cursor = self.events.size()
        self.events.append_event(событие)
        записано, _ = self.events.tail(cursor)
        self.assertEqual(записано[0]["тип"], "действие_подтверждено")
        self.assertEqual(записано[0]["комната"], "коридор_3")
        self.assertTrue(записано[0]["боевое"])

    def test_битая_строка_журнала_не_роняет_чтение(self):
        with self.events.path.open("a", encoding="utf-8") as fh:
            fh.write("это не json\n")
        self.events.append("этап", этап="выход")
        события = self.events.all()
        self.assertEqual(события[-1]["этап"], "выход")

    def test_очистка_журнала_сбрасывает_курсор(self):
        self.events.append("этап", этап="архив")
        cursor = self.events.size()
        self.events.clear()
        события, cursor = self.events.tail(cursor)
        self.assertEqual(события, [])
        self.assertEqual(cursor, 0)


if __name__ == "__main__":
    unittest.main()
