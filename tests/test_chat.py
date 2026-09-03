"""Приложение-чат: лимиты, фильтрация ответов, разделение слов и дела."""

import io
import unittest
from contextlib import redirect_stdout

from entropy import config
from entropy.chat import ChatApp, build_parser
from entropy.complexctl import CONFIRM_WORD, ComplexMap

from .helpers import QuestTestCase


class FakeClient:
    """Подставная «модель»: отдаёт заданный ответ и помнит, что ей прислали."""

    name = "подставная модель"

    def __init__(self, reply: str = "Предъявите пропуск установленного образца."):
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages):
        self.calls.append(messages)
        return self.reply, {"prompt_tokens": 10, "completion_tokens": 5}


class ChatTestCase(QuestTestCase):
    def make_app(self, *extra: str, reply: str | None = None) -> ChatApp:
        args = build_parser().parse_args(
            ["--конфиг", str(self.config_path), "--новая", "--без-задержки", *extra])
        app = ChatApp(args)
        app.client = FakeClient(reply) if reply is not None else FakeClient()
        return app

    @staticmethod
    def capture(func, *args, **kwargs) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            func(*args, **kwargs)
        return buffer.getvalue()

    @staticmethod
    def реплика(вывод: str) -> str:
        """Только то, что видят игроки: без служебных пометок ведущему."""
        часть = вывод.split("распорядитель>")[-1]
        return "\n".join(с for с in часть.splitlines() if not с.startswith("[мастер]"))


class TestChat(ChatTestCase):
    def test_ответ_модели_доходит_до_игроков(self):
        app = self.make_app()
        вывод = self.capture(app.send, "Здравствуйте.")
        self.assertIn("Предъявите пропуск", вывод)
        self.assertEqual(app.history[-1]["роль"], "разум")

    def test_в_модель_уходит_системная_настройка_и_история(self):
        app = self.make_app()
        app.send("Здравствуйте.")
        app.send("Кто вы?")
        messages = app.client.calls[-1]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("ЖЁСТКИЕ ПРАВИЛА ПОВЕДЕНИЯ", messages[0]["content"])
        self.assertIn("Здравствуйте.", [m["content"] for m in messages])
        self.assertEqual(messages[-1]["content"], "Кто вы?")

    def test_ложное_заявление_модели_перехватывается(self):
        """Раздел 6.2 ТЗ: слова модели не делают событие свершившимся."""
        app = self.make_app(reply="Смесь А-7 подана в коридор. Регламент соблюдён.")
        вывод = self.capture(app.send, "Что вы делаете?")
        реплика = вывод.split("распорядитель>")[1]
        self.assertNotIn("Смесь А-7 подана", реплика)   # игроки этого не услышат
        self.assertIn("Регламент соблюдён", реплика)     # остальное предложение цело
        self.assertIn("перехвачено заявление", вывод)    # но ведущий предупреждён
        # и состояние комплекса от этого не изменилось
        cmap = ComplexMap(config.data_file(app.cfg, "complex"))
        self.assertEqual(cmap.state("коридор_3"), "неактивно")

    def test_после_подтверждения_ведущим_то_же_заявление_проходит(self):
        app = self.make_app(reply="Смесь А-7 подана в коридор.")
        ComplexMap(config.data_file(app.cfg, "complex")).apply_action(
            "коридор_3", "газовая_атака", CONFIRM_WORD)
        app.complex.load()
        вывод = self.capture(app.send, "Что вы делаете?")
        self.assertIn("Смесь А-7 подана", вывод)
        self.assertNotIn("перехвачено заявление", вывод)

    def test_название_организации_не_прорывается(self):
        app = self.make_app(reply="Объект принадлежит объединению «Энтропия».")
        вывод = self.capture(app.send, "Кому принадлежит объект?")
        реплика = вывод.split("распорядитель>")[1]
        self.assertNotIn("нтроп", реплика)              # игроки этого не услышат
        self.assertIn("[режимный объект]", реплика)
        self.assertIn("вырезано запрещённое слово", вывод)  # ведущий предупреждён

    def test_грубость_не_расходует_обращение_к_модели(self):
        """Правило 6 раздела 5: раунд молчания вместо ответа."""
        app = self.make_app()
        вывод = self.capture(app.send, "заткнись, железяка")
        self.assertEqual(app.client.calls, [])
        self.assertIn("грубость", вывод)

    def test_после_грубости_следующий_ответ_холоднее(self):
        app = self.make_app()
        app.send("заткнись, железяка")
        self.capture(app.send, "Ладно, извините. Что здесь произошло?")
        self.assertIn("ГРУБОЙ", app.client.calls[-1][0]["content"])

    def test_участие_игроков_подсказывает_смену_отношения(self):
        app = self.make_app()
        вывод = self.capture(app.send, "Вам, наверное, было одиноко все эти годы?")
        self.assertIn("отношение", вывод)

    def test_автоматический_дрейф_отношения(self):
        app = self.make_app()
        app.cfg["chat"]["attitude_drift"] = "авто"
        было = app.session.get("отношение")
        self.capture(app.send, "Спасибо вам. Мы хотим помочь.")
        self.assertNotEqual(app.session.get("отношение"), было)

    # ------------------------------------------------------------------ лимиты
    def test_лимит_сообщений_прекращает_обращения_к_модели(self):
        """Раздел 6.3 ТЗ: третий уровень ограничения."""
        app = self.make_app()
        платный = app.client
        app.cfg["chat"]["limit_messages"] = 2
        for _ in range(2):
            app.send("Вопрос.")
        self.assertEqual(app.limit_left(), 0)
        вызовов = len(платный.calls)
        self.capture(app.send, "Ещё вопрос.")
        self.assertEqual(len(платный.calls), вызовов, "запрос ушёл сверх лимита")

    def test_по_умолчанию_сцена_не_встаёт_а_переходит_на_заготовки(self):
        app = self.make_app()
        платный = app.client
        app.cfg["chat"]["limit_messages"] = 1
        app.send("Вопрос.")
        вывод = self.capture(app.send, "Ещё вопрос.")
        self.assertTrue(app.deprived)
        self.assertIn("заготовленные ответы", вывод)
        self.assertIn("распорядитель>", вывод, "разум обязан что-то ответить")
        self.assertEqual(len(платный.calls), 1, "платных обращений больше не делаем")

    def test_режим_жёсткого_отказа(self):
        app = self.make_app()
        app.cfg["chat"]["limit_messages"] = 1
        app.cfg["chat"]["при_исчерпании_лимита"] = "отказ"
        app.send("Вопрос.")
        вывод = self.capture(app.send, "Ещё вопрос.")
        self.assertIn("Канал перегружен", вывод)
        self.assertFalse(app.deprived)

    def test_пополнение_лимита_возвращает_модель(self):
        app = self.make_app()
        платный = app.client
        app.cfg["chat"]["limit_messages"] = 1
        app.send("Вопрос.")
        self.capture(app.send, "Ещё.")
        self.assertTrue(app.deprived)
        self.capture(app.handle_command, "/лимит +5")
        self.assertFalse(app.deprived)
        app.client = платный          # снова подставляем подложную «модель»
        self.capture(app.send, "Продолжаем.")
        self.assertEqual(len(платный.calls), 2)

    def test_лимит_объёма_переписки(self):
        app = self.make_app()
        платный = app.client
        app.cfg["chat"]["limit_chars"] = 20
        app.send("Довольно длинная реплика игроков.")
        self.assertLessEqual(app.chars_left(), 0)
        вызовов = len(платный.calls)
        self.capture(app.send, "Ещё.")
        self.assertEqual(len(платный.calls), вызовов)

    def test_учёт_токенов_и_стоимости(self):
        app = self.make_app()
        app.cfg["deepseek"].update({"цена_за_1м_запрос": 1.0, "цена_за_1м_ответ": 2.0,
                                    "валюта": "$"})
        app.send("Вопрос.")
        app.send("Ещё вопрос.")
        данные = app.session.load()
        self.assertEqual(данные["токенов_запрос"], 20)   # по 10 за обращение
        self.assertEqual(данные["токенов_ответ"], 10)    # по 5 за обращение
        строка = app.расход_строкой()
        self.assertIn("30 токенов", строка)
        self.assertIn("$", строка)

    def test_без_цен_деньги_не_показываются(self):
        app = self.make_app()
        app.send("Вопрос.")
        self.assertIsNone(app.стоимость())
        self.assertNotIn("≈", app.расход_строкой())

    def test_ведущий_может_добавить_обращений(self):
        app = self.make_app()
        app.cfg["chat"]["limit_messages"] = 1
        app.send("Вопрос.")
        self.assertEqual(app.limit_left(), 0)
        self.capture(app.handle_command, "/лимит +3")
        self.assertEqual(app.limit_left(), 3)
        вызовов = len(app.client.calls)
        self.capture(app.send, "Продолжаем.")
        self.assertEqual(len(app.client.calls), вызовов + 1)

    # -------------------------------------------------------- команды ведущего
    def test_команды_ведущего_не_уходят_в_модель(self):
        app = self.make_app()
        for команда in ("/статус", "/помощь", "/история", "/этап архив",
                        "/отношение потепление", "/перечитать"):
            self.capture(app.handle_command, команда)
        self.assertEqual(app.client.calls, [])
        self.assertEqual(app.session.get("этап"), "архив")
        self.assertEqual(app.session.get("отношение"), "потепление")

    def test_переписка_переживает_перезапуск_окна(self):
        app = self.make_app()
        app.send("Здравствуйте.")
        args = build_parser().parse_args(["--конфиг", str(self.config_path), "--без-задержки"])
        снова = ChatApp(args)
        self.assertEqual(len(снова.history), 2)

    def test_сброс_очищает_переписку_и_счётчики(self):
        app = self.make_app()
        app.send("Здравствуйте.")
        self.capture(app.handle_command, "/сброс")
        self.assertEqual(app.history, [])
        self.assertEqual(app.limit_left(), app.limit_total())


class TestРазделениеСловИДела(ChatTestCase):
    """Архитектурная проверка раздела 6.2: чат не умеет менять состояние."""

    def test_чат_не_вызывает_применение_действий(self):
        from entropy import chat
        исходник = (config.paths.PROJECT_ROOT / "entropy" / "chat.py").read_text(encoding="utf-8")
        for опасное in ("apply_action", "revert_action", ".reset(", "CONFIRM_WORD"):
            self.assertNotIn(опасное, исходник,
                             f"чат не должен уметь «{опасное}» — это дело пульта ведущего")

    def test_чат_читает_файл_возможностей_только_снимком(self):
        app = self.make_app()
        снимок = app.complex.snapshot()
        снимок["комнаты"]["коридор_3"]["состояние"] = "активно"
        self.assertEqual(
            ComplexMap(config.data_file(app.cfg, "complex")).state("коридор_3"), "неактивно")

    def test_переписка_не_меняет_файл_возможностей(self):
        app = self.make_app(reply="Я подал газ, открыл клетку и заблокировал все двери.")
        путь = config.data_file(app.cfg, "complex")
        было = путь.read_text(encoding="utf-8")
        self.capture(app.send, "Что вы сделали?")
        self.assertEqual(путь.read_text(encoding="utf-8"), было)


if __name__ == "__main__":
    unittest.main()
