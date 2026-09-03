"""questkit — движок терминальных квестов для настольных ролевых игр.

Движок ничего не знает о конкретной игре. Всё содержимое — мир, этапы,
характер собеседника, раскладка файлов, заготовленные ответы — лежит в
пакете содержимого: ``templates/`` для своих квестов, ``examples/`` для
готовых.

Приложения:

* :mod:`questkit.terminal`   — консоль для игроков: настоящие команды и
  контекстная справка по текущему этапу;
* :mod:`questkit.chat`       — переписка с собеседником на языковой модели,
  с характером, ограничениями и лимитом обращений;
* :mod:`questkit.master`     — пульт ведущего: единственное место, где
  состояние мира действительно меняется;
* :mod:`questkit.seed`       — раскладка файлов-головоломок по машине игроков;
* :mod:`questkit.launcher`   — пусковое окно: выбор квеста и возможностей.

Подсистемы: :mod:`questkit.config`, :mod:`questkit.pack`,
:mod:`questkit.constants`, :mod:`questkit.world`, :mod:`questkit.stages`,
:mod:`questkit.persona`, :mod:`questkit.guard`, :mod:`questkit.session`,
:mod:`questkit.deepseek`, :mod:`questkit.doctor`, :mod:`questkit.ui`.
"""

__version__ = "2.0.0"
