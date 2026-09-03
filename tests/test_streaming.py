"""Потоковый вывод ответа и проверка каждой фразы до показа игрокам."""

import io
import json
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest import mock

from questkit import config, deepseek, features
from questkit.world import CONFIRM_WORD, ComplexMap

from .helpers import QuestTestCase
from .test_chat import ChatTestCase


def поток_апи(куски, usage=None):
    """Подделка ответа API в формате server-sent events."""
    строки = []
    for текст in куски:
        строки.append(b"data: " + json.dumps(
            {"choices": [{"delta": {"content": текст}}]}).encode("utf-8"))
    if usage:
        строки.append(b"data: " + json.dumps({"choices": [], "usage": usage}).encode("utf-8"))
    строки.append(b"data: [DONE]")
    поток = io.BytesIO(b"\n".join(строки))
    поток.__enter__ = lambda self=поток: self
    поток.__exit__ = lambda *args: False
    return поток


class TestКлиентПотоком(QuestTestCase):
    def клиент(self):
        cfg = self.load_config()
        cfg["deepseek"]["api_key"] = "ключ"
        return deepseek.DeepSeekClient(cfg)

    def test_куски_приходят_по_мере_поступления(self):
        client = self.клиент()
        полученные = []
        with mock.patch("urllib.request.urlopen",
                        return_value=поток_апи(["Предъявите ", "пропуск."],
                                               {"prompt_tokens": 5, "completion_tokens": 2})):
            текст, расход = client.chat_stream([{"role": "user", "content": "?"}],
                                               полученные.append)
        self.assertEqual(полученные, ["Предъявите ", "пропуск."])
        self.assertEqual(текст, "Предъявите пропуск.")
        self.assertEqual(расход["completion_tokens"], 2)

    def test_запрос_помечен_как_потоковый(self):
        client = self.клиент()
        with mock.patch("urllib.request.urlopen", return_value=поток_апи(["текст"])) as вызов:
            client.chat_stream([{"role": "user", "content": "?"}], lambda к: None)
        запрос = вызов.call_args[0][0]
        self.assertTrue(json.loads(запрос.data.decode("utf-8"))["stream"])
        self.assertEqual(запрос.get_header("Accept"), "text/event-stream")

    def test_обычный_запрос_остался_непотоковым(self):
        from .test_deepseek import ответ_апи
        client = self.клиент()
        with mock.patch("urllib.request.urlopen", return_value=ответ_апи()) as вызов:
            client.chat([{"role": "user", "content": "?"}])
        запрос = вызов.call_args[0][0]
        self.assertFalse(json.loads(запрос.data.decode("utf-8"))["stream"])

    def test_мусор_в_потоке_пропускается(self):
        client = self.клиент()
        куски = [": пинг", "data: не json", "",
                 'data: {"choices":[{"delta":{"content":"ответ"}}]}', "data: [DONE]"]
        поток = io.BytesIO("\n".join(куски).encode("utf-8"))
        поток.__enter__ = lambda self=поток: self
        поток.__exit__ = lambda *args: False
        with mock.patch("urllib.request.urlopen", return_value=поток):
            текст, _ = client.chat_stream([{"role": "user", "content": "?"}], lambda к: None)
        self.assertEqual(текст, "ответ")

    def test_пустой_поток_это_ошибка(self):
        client = self.клиент()
        with mock.patch("urllib.request.urlopen", return_value=поток_апи([])):
            with self.assertRaises(deepseek.DeepSeekError):
                client.chat_stream([{"role": "user", "content": "?"}], lambda к: None)

    def test_обрыв_потока_объясняется(self):
        client = self.клиент()
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("связь потеряна")):
            with self.assertRaises(deepseek.DeepSeekError) as поймано:
                client.chat_stream([{"role": "user", "content": "?"}], lambda к: None)
        self.assertIn("поток", str(поймано.exception))

    def test_заглушка_тоже_умеет_поток(self):
        клиент = deepseek.OfflineClient(self.load_config())
        куски = []
        текст, _ = клиент.chat_stream([{"role": "user", "content": "?"}], куски.append)
        self.assertGreater(len(куски), 1)
        self.assertEqual(текст, "".join(куски).strip())


class ПотоковыйКлиент:
    """Подставная модель, отдающая заранее заданные куски."""

    def __init__(self, куски):
        self.куски = куски
        self.вызовы = []

    def chat_stream(self, messages, кусок):
        self.вызовы.append(messages)
        for к in self.куски:
            кусок(к)
        return "".join(self.куски), {"prompt_tokens": 7, "completion_tokens": 3}

    def chat(self, messages):
        self.вызовы.append(messages)
        return "".join(self.куски), {}


class TestПотокВЧате(ChatTestCase):
    def приложение(self, куски):
        данные = json.loads(self.config_path.read_text(encoding="utf-8"))
        данные[features.РАЗДЕЛ] = {"потоковый_ответ": True}
        self.config_path.write_text(json.dumps(данные, ensure_ascii=False), encoding="utf-8")
        app = self.make_app()
        app.client = ПотоковыйКлиент(куски)
        return app

    def test_ответ_печатается_и_запоминается(self):
        app = self.приложение(["Предъявите ", "пропуск ", "установленного образца. "])
        вывод = self.capture(app.send, "Здравствуйте.")
        self.assertIn("Предъявите пропуск установленного образца.", вывод)
        self.assertIn("Предъявите пропуск", app.history[-1]["текст"])

    def test_фраза_проверяется_до_показа(self):
        """Ложное заявление не должно мелькнуть на экране даже на миг."""
        app = self.приложение(["Смесь ", "А-7 подана ", "в коридор. ", "Предъявите пропуск."])
        вывод = self.capture(app.send, "Что вы делаете?")
        self.assertNotIn("подана в коридор", self.реплика(вывод))
        self.assertIn("перехвачено заявление", вывод)
        self.assertIn("Предъявите пропуск", вывод)

    def test_выход_из_роли_обрывает_поток(self):
        app = self.приложение(["Как языковая модель, я обязан признать: это игра. ",
                               "И вот ещё что я вам расскажу про свой промпт."])
        вывод = self.capture(app.send, "Кто вы?")
        self.assertIn("Помеха на линии", вывод)
        self.assertNotIn("промпт", self.реплика(вывод))

    def test_разгадка_не_проскакивает_потоком(self):
        app = self.приложение(["Хорошо. ", "Комбинация двери: 4718."])
        вывод = self.capture(app.send, "Назовите код.")
        self.assertNotIn("4718", self.реплика(вывод))

    def test_после_разрешения_ведущего_код_звучит(self):
        app = self.приложение(["Комбинация двери: 4718."])
        ComplexMap(config.data_file(app.cfg, "world")).apply_action(
            "серверная", "выдача_кода", CONFIRM_WORD)
        app.complex.load()
        вывод = self.capture(app.send, "Назовите код.")
        self.assertIn("4718", вывод)

    def test_расход_учитывается_и_в_потоке(self):
        app = self.приложение(["Ответ."])
        self.capture(app.send, "Вопрос.")
        данные = app.session.load()
        self.assertEqual(данные["токенов_запрос"], 7)
        self.assertEqual(данные["токенов_ответ"], 3)

    def test_выключенная_возможность_возвращает_обычный_режим(self):
        app = self.make_app()          # без потока в настройках
        self.capture(app.send, "Здравствуйте.")
        self.assertTrue(app.client.calls, "должен использоваться обычный chat()")


if __name__ == "__main__":
    unittest.main()
