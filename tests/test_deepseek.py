"""Клиент DeepSeek: форма запроса и разбор ответов (раздел 4 ТЗ).

Сеть не используется: urlopen подменяется. Проверяется то, что можно проверить
без ключа — адрес, заголовки, тело запроса, разбор ответа и понятность ошибок.
"""

import io
import json
import unittest
import urllib.error
from unittest import mock

from entropy import config, deepseek

from .helpers import QuestTestCase


def ответ_апи(текст: str = "Предъявите пропуск установленного образца."):
    тело = json.dumps({
        "choices": [{"message": {"role": "assistant", "content": текст}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 40},
    }).encode("utf-8")
    поток = io.BytesIO(тело)
    поток.__enter__ = lambda self=поток: self
    поток.__exit__ = lambda *args: False
    return поток


class TestDeepSeekClient(QuestTestCase):
    def make_client(self, **правки) -> deepseek.DeepSeekClient:
        cfg = self.load_config()
        cfg["deepseek"].update({"api_key": "ключ-для-теста"}, **правки)
        return deepseek.DeepSeekClient(cfg)

    def test_без_ключа_клиент_не_создаётся(self):
        cfg = self.load_config()
        cfg["deepseek"]["api_key"] = ""
        with mock.patch.dict("os.environ", {"DEEPSEEK_API_KEY": ""}, clear=False):
            with self.assertRaises(deepseek.DeepSeekError) as ошибка:
                deepseek.DeepSeekClient(cfg)
        self.assertIn("ключ API не задан", str(ошибка.exception))

    def test_запрос_уходит_по_нужному_адресу_с_ключом(self):
        client = self.make_client()
        with mock.patch("urllib.request.urlopen", return_value=ответ_апи()) as вызов:
            текст, usage = client.chat([{"role": "user", "content": "Кто вы?"}])
        запрос = вызов.call_args[0][0]
        self.assertEqual(запрос.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(запрос.get_header("Authorization"), "Bearer ключ-для-теста")
        self.assertEqual(запрос.method, "POST")
        тело = json.loads(запрос.data.decode("utf-8"))
        self.assertEqual(тело["model"], "deepseek-chat")
        self.assertEqual(тело["messages"][0]["content"], "Кто вы?")
        self.assertFalse(тело["stream"])
        self.assertEqual(текст, "Предъявите пропуск установленного образца.")
        self.assertEqual(usage["prompt_tokens"], 120)

    def test_русский_текст_уходит_в_utf8(self):
        client = self.make_client()
        with mock.patch("urllib.request.urlopen", return_value=ответ_апи()) as вызов:
            client.chat([{"role": "user", "content": "Здравствуйте, распорядитель"}])
        тело = вызов.call_args[0][0].data
        self.assertIn("Здравствуйте", тело.decode("utf-8"))

    def test_настройки_модели_передаются(self):
        client = self.make_client(model="deepseek-reasoner", temperature=0.4, max_tokens=123)
        with mock.patch("urllib.request.urlopen", return_value=ответ_апи()) as вызов:
            client.chat([{"role": "user", "content": "?"}])
        тело = json.loads(вызов.call_args[0][0].data.decode("utf-8"))
        self.assertEqual(тело["model"], "deepseek-reasoner")
        self.assertEqual(тело["temperature"], 0.4)
        self.assertEqual(тело["max_tokens"], 123)

    def test_ошибки_апи_объясняются_по_русски(self):
        client = self.make_client()
        случаи = {401: "проверьте ключ", 402: "исчерпан баланс", 429: "слишком часто"}
        for код, подсказка in случаи.items():
            ошибка = urllib.error.HTTPError("url", код, "err", {}, io.BytesIO(b"{}"))
            with mock.patch("urllib.request.urlopen", side_effect=ошибка):
                with self.assertRaises(deepseek.DeepSeekError) as поймано:
                    client.chat([{"role": "user", "content": "?"}])
            self.assertIn(подсказка, str(поймано.exception))

    def test_нет_связи_объясняется_понятно(self):
        client = self.make_client()
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("сеть недоступна")):
            with self.assertRaises(deepseek.DeepSeekError) as поймано:
                client.chat([{"role": "user", "content": "?"}])
        self.assertIn("нет связи", str(поймано.exception))

    def test_неожиданный_ответ_не_роняет_приложение(self):
        client = self.make_client()
        пустой = io.BytesIO(b'{"choices": []}')
        пустой.__enter__ = lambda self=пустой: self
        пустой.__exit__ = lambda *args: False
        with mock.patch("urllib.request.urlopen", return_value=пустой):
            with self.assertRaises(deepseek.DeepSeekError):
                client.chat([{"role": "user", "content": "?"}])

    def test_ключ_не_попадает_в_текст_ошибки(self):
        client = self.make_client()
        ошибка = urllib.error.HTTPError("url", 401, "err", {}, io.BytesIO(b"{}"))
        with mock.patch("urllib.request.urlopen", side_effect=ошибка):
            with self.assertRaises(deepseek.DeepSeekError) as поймано:
                client.chat([{"role": "user", "content": "?"}])
        self.assertNotIn("ключ-для-теста", str(поймано.exception))


class TestOfflineClient(QuestTestCase):
    def test_заглушка_отвечает_без_сети(self):
        client = deepseek.OfflineClient(self.load_config())
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("заглушка не должна ходить в сеть")):
            текст, usage = client.chat([{"role": "user", "content": "Кто вы?"}])
        self.assertTrue(текст)
        self.assertTrue(usage.get("офлайн"))

    def test_выбор_клиента(self):
        cfg = self.load_config()
        self.assertIsInstance(deepseek.make_client(cfg, offline=True), deepseek.OfflineClient)


if __name__ == "__main__":
    unittest.main()


class TestПовторы(QuestTestCase):
    """Одна помеха в сети не должна стоить игрокам реплики."""

    def клиент(self, **правки):
        cfg = self.load_config()
        cfg["deepseek"].update({"api_key": "ключ", "retries": 2, "retry_pause_sec": 0}, **правки)
        return deepseek.DeepSeekClient(cfg)

    def test_перегрузка_сервиса_повторяется(self):
        client = self.клиент()
        перегрузка = urllib.error.HTTPError("url", 429, "too many", {}, io.BytesIO(b"{}"))
        ответы = [перегрузка, перегрузка, ответ_апи("наконец-то")]
        with mock.patch("urllib.request.urlopen", side_effect=ответы) as вызов:
            with mock.patch("time.sleep"):
                текст, _ = client.chat([{"role": "user", "content": "?"}])
        self.assertEqual(текст, "наконец-то")
        self.assertEqual(вызов.call_count, 3)

    def test_обрыв_связи_повторяется(self):
        client = self.клиент()
        обрыв = urllib.error.URLError("сеть недоступна")
        with mock.patch("urllib.request.urlopen", side_effect=[обрыв, ответ_апи()]) as вызов:
            with mock.patch("time.sleep"):
                client.chat([{"role": "user", "content": "?"}])
        self.assertEqual(вызов.call_count, 2)

    def test_неверный_ключ_не_повторяется(self):
        """Повтор этого не исправит — только потратит время партии."""
        client = self.клиент()
        отказ = urllib.error.HTTPError("url", 401, "unauthorized", {}, io.BytesIO(b"{}"))
        with mock.patch("urllib.request.urlopen", side_effect=отказ) as вызов:
            with mock.patch("time.sleep"):
                with self.assertRaises(deepseek.DeepSeekError):
                    client.chat([{"role": "user", "content": "?"}])
        self.assertEqual(вызов.call_count, 1)

    def test_повторы_не_бесконечны(self):
        client = self.клиент(retries=2)
        перегрузка = urllib.error.HTTPError("url", 503, "unavailable", {}, io.BytesIO(b"{}"))
        with mock.patch("urllib.request.urlopen", side_effect=перегрузка) as вызов:
            with mock.patch("time.sleep"):
                with self.assertRaises(deepseek.DeepSeekError):
                    client.chat([{"role": "user", "content": "?"}])
        self.assertEqual(вызов.call_count, 3, "первая попытка плюс два повтора")

    def test_пауза_между_попытками_растёт(self):
        client = self.клиент(retry_pause_sec=1.0)
        перегрузка = urllib.error.HTTPError("url", 500, "boom", {}, io.BytesIO(b"{}"))
        with mock.patch("urllib.request.urlopen", side_effect=перегрузка):
            with mock.patch("time.sleep") as пауза:
                with self.assertRaises(deepseek.DeepSeekError):
                    client.chat([{"role": "user", "content": "?"}])
        self.assertEqual([c.args[0] for c in пауза.call_args_list], [1.0, 2.0])
