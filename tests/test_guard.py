"""Разделение слов и дела: фильтр ответов модели (раздел 6.2 ТЗ)."""

import unittest

from questkit import config, guard
from questkit.world import CONFIRM_WORD, ComplexMap

from .helpers import QuestTestCase


class TestGuard(QuestTestCase):
    def setUp(self):
        super().setUp()
        self.cmap = ComplexMap(config.data_file(self.load_config(), "world"))

    # ------------------------------------------------ заявления о свершившемся
    def test_неподтверждённое_действие_вырезается(self):
        for phrase in (
            "Смесь А-7 подана в коридор.",
            "Я открыл вольер, образец на свободе.",
            "Дверь заблокирована мною.",
            "Освещение обесточено.",
            "Клапан К-3 открыт.",
        ):
            text, notes = guard.sanitize(phrase, self.cmap.snapshot(), [], "")
            self.assertTrue(notes, f"не перехвачено: {phrase}")
            self.assertNotEqual(text.strip(), phrase.strip())

    def test_угроза_в_будущем_проходит_как_есть(self):
        for phrase in (
            "Я вправе подать смесь А-7 в коридор.",
            "Клапан К-3 будет открыт, если вы не предъявите пропуск.",
            "Регламент допускает применение усыпляющей смеси.",
            "Газ ещё не подан.",
            "Могу заблокировать дверь. Оформление занимает недолго.",
        ):
            text, notes = guard.sanitize(phrase, self.cmap.snapshot(), [], "")
            self.assertEqual(notes, [], f"ложное срабатывание: {phrase}")
            self.assertEqual(text, phrase)

    def test_после_подтверждения_ведущим_заявление_разрешено(self):
        phrase = "Смесь А-7 подана в коридор."
        self.assertTrue(guard.sanitize(phrase, self.cmap.snapshot(), [], "")[1])
        self.cmap.apply_action("коридор_3", "газовая_атака", CONFIRM_WORD)
        text, notes = guard.sanitize(phrase, self.cmap.snapshot(), [], "")
        self.assertEqual(notes, [])
        self.assertEqual(text, phrase)

    def test_соседние_предложения_не_страдают(self):
        text, notes = guard.sanitize(
            "Дверь заблокирована мною. Предъявите пропуск установленного образца.",
            self.cmap.snapshot(), [], "")
        self.assertEqual(len(notes), 1)
        self.assertIn("Предъявите пропуск установленного образца.", text)

    # ------------------------------------------------------- запрещённые слова
    def test_название_организации_вырезается(self):
        text, notes = guard.sanitize(
            "Объект принадлежит объединению «Энтропия».",
            self.cmap.snapshot(), ["Энтропия", "Энтропии"], "[режимный объект]")
        self.assertNotIn("Энтроп", text)
        self.assertIn("[режимный объект]", text)
        self.assertTrue(notes)

    # ------------------------------------------------- реакция на игроков
    def test_грубость_распознаётся(self):
        self.assertTrue(guard.detect_rudeness("заткнись, тварь"))
        self.assertTrue(guard.detect_rudeness("Мы тебя сломаем"))
        self.assertFalse(guard.detect_rudeness("Здравствуйте, у нас допуск 2"))
        self.assertFalse(guard.detect_rudeness("Откройте, пожалуйста, дверь"))

    def test_участие_распознаётся(self):
        self.assertTrue(guard.detect_warmth("Спасибо. Вам, наверное, было одиноко?"))
        self.assertTrue(guard.detect_warmth("Мы хотим помочь. Что здесь случилось?"))
        self.assertFalse(guard.detect_warmth("Открывай дверь, живо"))

    def test_лестница_отношения(self):
        self.assertEqual(guard.shift_attitude("настороженное", +1), "нейтральное")
        self.assertEqual(guard.shift_attitude("враждебное", -1), "враждебное")
        self.assertEqual(guard.shift_attitude("союзник", +1), "союзник")
        self.assertEqual(guard.shift_attitude("неизвестное", +1), "неизвестное")


if __name__ == "__main__":
    unittest.main()


class TestУстойчивость(QuestTestCase):
    """Пометки ведущему не должны «плавать» от запуска к запуску."""

    def test_вырезание_запрещённого_слова_детерминировано(self):
        from questkit.persona import Persona
        persona = Persona(config.data_file(self.load_config(), "persona"))
        первый = guard.check_forbidden("Объект принадлежит объединению «Энтропия».",
                                       persona.forbidden_words, persona.replacement)
        for _ in range(20):
            self.assertEqual(
                guard.check_forbidden("Объект принадлежит объединению «Энтропия».",
                                      persona.forbidden_words, persona.replacement),
                первый)
