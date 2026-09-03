"""Проверка готовности к партии."""

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

from entropy import config, doctor
from entropy.complexctl import CONFIRM_WORD, ComplexMap
from entropy.seed import Seeder

from .helpers import QuestTestCase


class DoctorTestCase(QuestTestCase):
    def разложить(self):
        Seeder(config.data_file(self.load_config(), "scenario"), self.root).seed()

    def строка(self, отчёт, начало):
        for s in отчёт.строки:
            if s.название.startswith(начало):
                return s
        self.fail(f"в отчёте нет строки «{начало}»")


class TestГотовность(DoctorTestCase):
    def test_полностью_готовый_квест(self):
        self.разложить()
        отчёт = doctor.проверить(self.load_config())
        self.assertTrue(отчёт.готово, [s for s in отчёт.строки if s.состояние == doctor.ОШИБКА])
        self.assertEqual(self.строка(отчёт, "Раскладка").состояние, doctor.ОК)
        self.assertEqual(self.строка(отчёт, "Состояние партии").состояние, doctor.ОК)

    def test_неразложенный_квест_это_ошибка(self):
        отчёт = doctor.проверить(self.load_config())
        строка = self.строка(отчёт, "Раскладка")
        self.assertEqual(строка.состояние, doctor.ОШИБКА)
        self.assertIn("run_seed.py разложить", строка.совет)
        self.assertFalse(отчёт.готово)

    def test_испорченная_раскладка_видна(self):
        self.разложить()
        (self.root / "архив" / "схема_секции.dat").write_text("уже не картинка", encoding="utf-8")
        отчёт = doctor.проверить(self.load_config())
        self.assertEqual(self.строка(отчёт, "Раскладка").состояние, doctor.ОШИБКА)

    def test_битый_json_данных(self):
        (self.data / "stages.json").write_text("{это не json", encoding="utf-8")
        отчёт = doctor.проверить(self.load_config())
        self.assertEqual(self.строка(отчёт, "Файл данных «stages»").состояние, doctor.ОШИБКА)

    def test_потерянная_ссылка_на_константу(self):
        """Иначе игрок увидит в файле «{{...}}» вместо значения."""
        путь = self.data / "stages.json"
        данные = json.loads(путь.read_text(encoding="utf-8"))
        данные["этапы"]["шлюз"]["описание"] = "объект {{несуществующая_константа}}"
        путь.write_text(json.dumps(данные, ensure_ascii=False), encoding="utf-8")
        отчёт = doctor.проверить(self.load_config())
        строка = self.строка(отчёт, "Константы")
        self.assertEqual(строка.состояние, doctor.ОШИБКА)
        self.assertIn("несуществующая_константа", строка.подробность)

    def test_пропавшая_заготовка_ответа(self):
        (self.data / "canned" / "corridor_vent.txt").unlink()
        отчёт = doctor.проверить(self.load_config())
        строка = self.строка(отчёт, "Заготовленные ответы")
        self.assertEqual(строка.состояние, doctor.ОШИБКА)
        self.assertIn("corridor_vent.txt", строка.подробность)

    def test_следы_прошлой_партии(self):
        self.разложить()
        cfg = self.load_config()
        ComplexMap(config.data_file(cfg, "complex")).apply_action(
            "коридор_3", "газовая_атака", CONFIRM_WORD)
        отчёт = doctor.проверить(cfg)
        строка = self.строка(отчёт, "Состояние партии")
        self.assertEqual(строка.состояние, doctor.ПРЕДУПРЕЖДЕНИЕ)
        self.assertIn("газовая_атака", строка.подробность)
        self.assertIn("сброс", строка.совет)
        self.assertTrue(отчёт.готово, "следы прошлой партии — замечание, а не запрет")

    def test_предупреждение_про_root(self):
        with mock.patch.object(os, "geteuid", return_value=0, create=True):
            отчёт = doctor.проверить(self.load_config())
        строка = self.строка(отчёт, "Пользователь")
        self.assertEqual(строка.состояние, doctor.ПРЕДУПРЕЖДЕНИЕ)
        self.assertIn("chmod", строка.совет)

    def test_ключ_показан_не_целиком(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-очень-секретный-ключ"}):
            отчёт = doctor.проверить(self.load_config())
        строка = self.строка(отчёт, "Ключ API")
        self.assertEqual(строка.состояние, doctor.ОК)
        self.assertNotIn("очень-секретный", строка.подробность)


class TestЖиваяПроверка(DoctorTestCase):
    def test_пробный_запрос_к_модели(self):
        отчёт = doctor.Отчёт()
        cfg = self.load_config()
        cfg["deepseek"]["api_key"] = "ключ"
        клиент = mock.Mock()
        клиент.chat.return_value = ("готов", {"total_tokens": 12})
        with mock.patch.object(doctor.deepseek, "DeepSeekClient", return_value=клиент):
            doctor.проверить_связь(отчёт, cfg)
        self.assertEqual(отчёт.строки[-1].состояние, doctor.ОК)

    def test_недоступная_модель_это_ошибка(self):
        отчёт = doctor.Отчёт()
        cfg = self.load_config()
        cfg["deepseek"]["api_key"] = "ключ"
        with mock.patch.object(doctor.deepseek, "DeepSeekClient",
                               side_effect=doctor.deepseek.DeepSeekError("нет связи")):
            doctor.проверить_связь(отчёт, cfg)
        self.assertEqual(отчёт.строки[-1].состояние, doctor.ОШИБКА)

    def test_без_ключа_связь_не_проверяется(self):
        отчёт = doctor.Отчёт()
        cfg = self.load_config()
        cfg["deepseek"]["api_key"] = ""
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            with mock.patch.object(doctor.deepseek, "DeepSeekClient",
                                   side_effect=AssertionError("не должно вызываться")):
                doctor.проверить_связь(отчёт, cfg)
        self.assertEqual(отчёт.строки[-1].состояние, doctor.ПРЕДУПРЕЖДЕНИЕ)


class TestВыводОтчёта(DoctorTestCase):
    def test_отчёт_читаемый_и_с_кодом_возврата(self):
        from entropy.master import main
        self.разложить()
        буфер = io.StringIO()
        with redirect_stdout(буфер):
            код = main(["--конфиг", str(self.config_path), "проверка"])
        вывод = буфер.getvalue()
        self.assertIn("ПРОВЕРКА ГОТОВНОСТИ", вывод)
        self.assertIn("Раскладка файлов", вывод)
        self.assertEqual(код, 0)

    def test_код_возврата_при_ошибке(self):
        from entropy.master import main
        буфер = io.StringIO()
        with redirect_stdout(буфер):
            код = main(["--конфиг", str(self.config_path), "проверка"])
        self.assertEqual(код, 1, "неразложенный квест — не готов")
        self.assertIn("НЕ ГОТОВО", буфер.getvalue())


if __name__ == "__main__":
    unittest.main()
