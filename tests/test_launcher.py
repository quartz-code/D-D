"""Пусковое окно: выбор возможностей, подготовка партии, запуск.

Графической подсистемы в проверочном окружении нет, поэтому проверяется вся
логика окна (она вынесена из tkinter в обычные функции) и текстовое меню,
которое работает всегда.
"""

import json
import subprocess
import unittest
from unittest import mock

from questkit import config, features, launcher

from .helpers import QuestTestCase


class Ввод:
    """Подставной ввод: отдаёт заготовленные ответы по одному."""

    def __init__(self, ответы):
        self.ответы = list(ответы)
        self.выдано = []

    def __call__(self, приглашение=""):
        if not self.ответы:
            raise EOFError
        ответ = self.ответы.pop(0)
        self.выдано.append(ответ)
        return ответ


class TestСостояние(QuestTestCase):
    def test_показывает_все_возможности(self):
        строки = launcher.состояние(self.load_config())
        self.assertEqual([с.ключ for с in строки], [в.ключ for в in features.СПИСОК])

    def test_отражает_настройки(self):
        cfg = self.load_config()
        cfg[features.РАЗДЕЛ] = {"журнал_партии": False, "потоковый_ответ": True}
        по_ключу = {с.ключ: с for с in launcher.состояние(cfg)}
        self.assertFalse(по_ключу["журнал_партии"].включена)
        self.assertTrue(по_ключу["потоковый_ответ"].включена)

    def test_недоступная_возможность_помечена(self):
        from questkit import voice
        with mock.patch.object(voice.shutil, "which", return_value=None):
            по_ключу = {с.ключ: с for с in launcher.состояние(self.load_config())}
        self.assertFalse(по_ключу["озвучка"].доступна)
        self.assertIn("espeak", по_ключу["озвучка"].пояснение)


class TestСохранение(QuestTestCase):
    def test_записывает_только_возможности(self):
        путь = self.tmp / "config.json"
        путь.write_text(json.dumps({
            "deepseek": {"api_key": "мой-ключ"},
            "terminal": {"sandbox_root": "/куда-то"},
        }, ensure_ascii=False), encoding="utf-8")
        launcher.сохранить({"озвучка": True, "журнал_партии": False}, путь)
        данные = json.loads(путь.read_text(encoding="utf-8"))
        self.assertEqual(данные["deepseek"]["api_key"], "мой-ключ", "чужие настройки целы")
        self.assertEqual(данные["terminal"]["sandbox_root"], "/куда-то")
        self.assertTrue(данные[features.РАЗДЕЛ]["озвучка"])
        self.assertFalse(данные[features.РАЗДЕЛ]["журнал_партии"])

    def test_создаёт_файл_из_образца(self):
        путь = self.tmp / "нового-нет.json"
        launcher.сохранить({"озвучка": True}, путь)
        данные = json.loads(путь.read_text(encoding="utf-8"))
        self.assertTrue(данные[features.РАЗДЕЛ]["озвучка"])
        self.assertIn("deepseek", данные, "за основу взят образец настроек")

    def test_битый_файл_не_теряет_выбор(self):
        путь = self.tmp / "битый.json"
        путь.write_text("{не json", encoding="utf-8")
        launcher.сохранить({"озвучка": True}, путь)
        self.assertTrue(json.loads(путь.read_text(encoding="utf-8"))[features.РАЗДЕЛ]["озвучка"])

    def test_приложения_видят_сохранённое(self):
        путь = self.tmp / "config.json"
        launcher.сохранить({"потоковый_ответ": True, "живое_оповещение": False}, путь)
        cfg = config.load(путь)
        self.assertTrue(features.включена(cfg, "потоковый_ответ"))
        self.assertFalse(features.включена(cfg, "живое_оповещение"))


class TestДействия(QuestTestCase):
    def test_разложить(self):
        отчёт = launcher.разложить(self.load_config())
        self.assertIn("разложено файлов", отчёт)
        self.assertTrue((self.root / "архив" / "схема_секции.dat").exists())

    def test_разложить_со_случайным_кодом(self):
        cfg = self.load_config()
        было = self.constants()["код_двери"]
        отчёт = launcher.разложить(cfg, случайный_код=True)
        стало = self.constants()["код_двери"]
        self.assertIn("код двери на эту партию", отчёт)
        self.assertNotEqual(было, стало)
        записка = (self.root / "лаборатория_Б" / "код_внешней_двери.txt").read_text(
            encoding="utf-8")
        self.assertTrue(any(стало in с[::-1] for с in записка.splitlines()))

    def test_повторная_раскладка_чистит_прошлую(self):
        launcher.разложить(self.load_config())
        (self.root / "мусор.txt").write_text("следы прошлой партии", encoding="utf-8")
        launcher.разложить(self.load_config())
        self.assertFalse((self.root / "мусор.txt").exists())

    def test_проверка_готовности(self):
        launcher.разложить(self.load_config())
        готово, текст = launcher.проверка(self.load_config())
        self.assertTrue(готово)
        self.assertIn("Раскладка файлов", текст)

    def test_проверка_видит_неготовность(self):
        готово, текст = launcher.проверка(self.load_config())
        self.assertFalse(готово)
        self.assertIn("НЕ ГОТОВО", текст)


class TestЗапускОкон(QuestTestCase):
    def test_запускает_через_эмулятор_терминала(self):
        with mock.patch.object(launcher.shutil, "which",
                               side_effect=lambda имя: "/usr/bin/xterm" if имя == "xterm" else None):
            with mock.patch.object(subprocess, "Popen") as запуск:
                получилось, пояснение = launcher.открыть_окна(["терминал", "чат"])
        self.assertTrue(получилось)
        self.assertEqual(запуск.call_count, 2)
        self.assertIn("run_terminal.py", " ".join(запуск.call_args_list[0][0][0]))

    def test_предпочитает_tmux(self):
        with mock.patch.object(launcher.shutil, "which", side_effect=lambda имя: f"/usr/bin/{имя}"):
            with mock.patch.object(subprocess, "Popen") as запуск:
                получилось, пояснение = launcher.открыть_окна()
        self.assertTrue(получилось)
        self.assertEqual(запуск.call_count, 1, "tmux открывает все окна разом")
        self.assertIn("tmux", пояснение)

    def test_без_эмулятора_подсказывает_команды(self):
        with mock.patch.object(launcher.shutil, "which", return_value=None):
            получилось, пояснение = launcher.открыть_окна()
        self.assertFalse(получилось)
        self.assertIn("run_terminal.py", пояснение)
        self.assertIn("run_chat.py", пояснение)

    def test_сбой_запуска_не_роняет_окно(self):
        with mock.patch.object(launcher.shutil, "which",
                               side_effect=lambda имя: "/usr/bin/xterm" if имя == "xterm" else None):
            with mock.patch.object(subprocess, "Popen", side_effect=OSError("нельзя")):
                получилось, пояснение = launcher.открыть_окна()
        self.assertFalse(получилось)
        self.assertIn("вручную", пояснение)


class TestТекстовоеМеню(QuestTestCase):
    def меню(self, ответы):
        напечатанное = []
        путь = self.tmp / "config.json"
        код = launcher.текстовое_меню(self.load_config(), путь,
                                      ввод=Ввод(ответы), вывод=напечатанное.append)
        return код, "\n".join(str(с) for с in напечатанное), путь

    def test_переключение_и_сохранение(self):
        код, вывод, путь = self.меню(["3", "в"])
        self.assertEqual(код, 0)
        данные = json.loads(путь.read_text(encoding="utf-8"))
        self.assertTrue(данные[features.РАЗДЕЛ]["потоковый_ответ"])

    def test_недоступную_включить_нельзя(self):
        from questkit import voice
        with mock.patch.object(voice.shutil, "which", return_value=None):
            код, вывод, путь = self.меню(["4", "в"])
        данные = json.loads(путь.read_text(encoding="utf-8"))
        self.assertFalse(данные[features.РАЗДЕЛ]["озвучка"])
        self.assertIn("недоступно", вывод)

    def test_выключить_можно_и_недоступную(self):
        """Если она была включена раньше — снять галочку должно быть можно."""
        from questkit import voice
        путь = self.tmp / "config.json"
        launcher.сохранить({"озвучка": True}, путь)
        напечатанное = []
        with mock.patch.object(voice.shutil, "which", return_value=None):
            launcher.текстовое_меню(config.load(путь), путь,
                                    ввод=Ввод(["4", "в"]), вывод=напечатанное.append)
        данные = json.loads(путь.read_text(encoding="utf-8"))
        self.assertFalse(данные[features.РАЗДЕЛ]["озвучка"])

    def test_раскладка_из_меню(self):
        код, вывод, путь = self.меню(["р", "в"])
        self.assertIn("разложено файлов", вывод)
        self.assertTrue((self.root / "ЧИТАТЬ_ПЕРВЫМ.txt").exists())

    def test_проверка_из_меню(self):
        код, вывод, путь = self.меню(["п", "в"])
        self.assertIn("Раскладка файлов", вывод)

    def test_непонятный_ввод_не_ломает_меню(self):
        код, вывод, путь = self.меню(["чепуха", "в"])
        self.assertEqual(код, 0)
        self.assertIn("не понял", вывод)

    def test_обрыв_ввода_завершает_спокойно(self):
        код, вывод, путь = self.меню([])
        self.assertEqual(код, 0)


class TestТочкаВхода(QuestTestCase):
    def test_без_tkinter_открывается_текстовое_меню(self):
        with mock.patch.object(launcher, "запустить_окно",
                               side_effect=RuntimeError("tkinter недоступен")):
            with mock.patch.object(launcher, "текстовое_меню", return_value=0) as меню:
                код = launcher.main(["--конфиг", str(self.config_path)])
        self.assertEqual(код, 0)
        меню.assert_called_once()

    def test_ключ_текст_сразу_даёт_меню(self):
        with mock.patch.object(launcher, "запустить_окно",
                               side_effect=AssertionError("окно не должно открываться")):
            with mock.patch.object(launcher, "текстовое_меню", return_value=0) as меню:
                launcher.main(["--конфиг", str(self.config_path), "--текст"])
        меню.assert_called_once()


if __name__ == "__main__":
    unittest.main()


class ПоддельныйTk:
    """Минимальная подделка tkinter: позволяет прогнать код окна без экрана.

    Настоящего графического окружения в проверке нет, но сам код окна
    выполнить надо — иначе опечатка в нём обнаружилась бы только у ведущего
    за пять минут до партии.
    """

    def __init__(self):
        import types
        from unittest import mock

        self.кнопки = []
        self.галочки = []
        self.переменные = []
        self.строковые = []
        self.списки = []
        внешний = self

        class Переменная:
            def __init__(self, value=False):
                self._значение = bool(value)
                внешний.переменные.append(self)

            def get(self):
                return self._значение

            def set(self, значение):
                self._значение = bool(значение)

        class Строковая:
            """StringVar: держит подпись выбранного пакета содержимого."""

            def __init__(self, value=""):
                self._значение = str(value)
                внешний.строковые.append(self)

            def get(self):
                return self._значение

            def set(self, значение):
                self._значение = str(значение)

        class Виджет:
            """Любой виджет: принимает что угодно, ничего не делает."""

            def __init__(self, *args, **kwargs):
                self.args, self.kwargs = args, kwargs

            def __getattr__(self, имя):
                return lambda *a, **k: None

        def кнопка(*args, **kwargs):
            внешний.кнопки.append(kwargs)
            return Виджет()

        def галочка(*args, **kwargs):
            внешний.галочки.append(kwargs)
            return Виджет()

        def список(*args, **kwargs):
            внешний.списки.append(kwargs)
            return Виджет()

        self.окно = mock.MagicMock(name="Tk")
        tkinter = types.ModuleType("tkinter")
        tkinter.Tk = mock.Mock(return_value=self.окно)
        tkinter.BooleanVar = Переменная
        tkinter.StringVar = Строковая
        ttk = types.ModuleType("tkinter.ttk")
        ttk.Label = Виджет
        ttk.LabelFrame = Виджет
        ttk.Frame = Виджет
        ttk.Checkbutton = галочка
        ttk.Button = кнопка
        ttk.Combobox = список
        scrolledtext = types.ModuleType("tkinter.scrolledtext")
        scrolledtext.ScrolledText = Виджет
        tkinter.ttk = ttk
        tkinter.scrolledtext = scrolledtext
        self.модули = {"tkinter": tkinter, "tkinter.ttk": ttk,
                       "tkinter.scrolledtext": scrolledtext}

    def нажать(self, подпись):
        for кнопка in self.кнопки:
            if кнопка.get("text") == подпись:
                return кнопка["command"]()
        raise AssertionError(f"кнопки «{подпись}» нет в окне")


class TestОкно(QuestTestCase):
    """Проверка самого кода окна на поддельном tkinter."""

    def окно(self):
        подделка = ПоддельныйTk()
        путь = self.tmp / "config.json"
        with mock.patch.dict("sys.modules", подделка.модули):
            launcher.запустить_окно(self.load_config(), путь)
        return подделка, путь

    def test_окно_открывается_и_ждёт_действий(self):
        подделка, _ = self.окно()
        подделка.окно.title.assert_called_once()
        подделка.окно.mainloop.assert_called_once()

    def test_галочка_на_каждую_возможность(self):
        подделка, _ = self.окно()
        подписи = [г.get("text") for г in подделка.галочки]
        for в in features.СПИСОК:
            self.assertIn(в.название, подписи)

    def test_все_кнопки_на_месте(self):
        подделка, _ = self.окно()
        подписи = [к.get("text") for к in подделка.кнопки]
        for нужная in ("Разложить файлы", "Случайный код", "Проверка готовности",
                       "Открыть окна квеста", "Сохранить и закрыть"):
            self.assertIn(нужная, подписи)

    def test_кнопка_сохранения_пишет_настройки(self):
        подделка, путь = self.окно()
        подделка.переменные[2].set(True)          # «Ответ разума по мере набора»
        подделка.нажать("Сохранить и закрыть")
        данные = json.loads(путь.read_text(encoding="utf-8"))
        self.assertTrue(данные[features.РАЗДЕЛ]["потоковый_ответ"])
        подделка.окно.destroy.assert_called_once()

    def test_кнопка_раскладки_создаёт_файлы(self):
        подделка, _ = self.окно()
        подделка.нажать("Разложить файлы")
        self.assertTrue((self.root / "ЧИТАТЬ_ПЕРВЫМ.txt").exists())

    def test_кнопка_случайного_кода_меняет_код(self):
        подделка, _ = self.окно()
        было = self.constants()["код_двери"]
        подделка.нажать("Случайный код")
        self.assertNotEqual(было, self.constants()["код_двери"])

    def test_кнопка_проверки_не_падает_на_неготовом_квесте(self):
        подделка, _ = self.окно()
        подделка.нажать("Проверка готовности")

    def test_кнопка_запуска_окон(self):
        подделка, _ = self.окно()
        with mock.patch.object(launcher, "открыть_окна",
                               return_value=(True, "открыто")) as запуск:
            подделка.нажать("Открыть окна квеста")
        запуск.assert_called_once()

    def test_недоступная_возможность_не_отмечается_сама(self):
        from questkit import voice
        подделка = ПоддельныйTk()
        путь = self.tmp / "config.json"
        launcher.сохранить({"озвучка": True}, путь)
        with mock.patch.object(voice.shutil, "which", return_value=None):
            with mock.patch.dict("sys.modules", подделка.модули):
                launcher.запустить_окно(config.load(путь), путь)
        подделка.нажать("Сохранить и закрыть")
        данные = json.loads(путь.read_text(encoding="utf-8"))
        self.assertFalse(данные[features.РАЗДЕЛ]["озвучка"],
                         "включённую, но недоступную возможность окно снимает")

    def test_в_окне_есть_выбор_квеста(self):
        подделка, _ = self.окно()
        self.assertTrue(подделка.списки, "в окне нет выпадающего списка пакетов")
        подписи = подделка.списки[0].get("values") or []
        self.assertTrue(any("Комплекс Энтропии" in п for п in подписи))
        self.assertTrue(any("шаблон" in п for п in подписи))

    def test_смена_квеста_в_окне_сохраняется(self):
        подделка, путь = self.окно()
        подписи = подделка.списки[0]["values"]
        шаблон = next(п for п in подписи if "шаблон" in п)
        подделка.строковые[0].set(шаблон)
        подделка.нажать("Сохранить и закрыть")
        данные = json.loads(путь.read_text(encoding="utf-8"))
        self.assertIn("blank", данные["content"])
