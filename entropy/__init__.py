"""Инструментарий ведущего для квеста «Комплекс Энтропии».

Пакет состоит из четырёх независимых приложений:

* ``entropy.terminal``   — терминал-приложение для игроков (раздел 3 ТЗ);
* ``entropy.chat``       — чат с искусственным разумом (разделы 4-6 ТЗ);
* ``entropy.master``     — пульт ведущего: подтверждение событий (разделы 6.2, 7, 8);
* ``entropy.seed``       — генератор файловой системы-головоломки (раздел 2).

Общие подсистемы: :mod:`entropy.config`, :mod:`entropy.session`,
:mod:`entropy.stages`, :mod:`entropy.complexctl`, :mod:`entropy.persona`,
:mod:`entropy.guard`, :mod:`entropy.deepseek`, :mod:`entropy.ui`.
"""

__version__ = "1.0.0"
