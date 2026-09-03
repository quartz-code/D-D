"""Живое оповещение о событиях (возможность «живое_оповещение»).

Без неё окно игроков узнаёт о подтверждённом действии только когда кто-нибудь
нажмёт Enter: приложение читает журнал перед выводом приглашения. Газ,
поданный ведущим в напряжённый момент, вспыхивал с запозданием.

Здесь заводится фоновый поток, который следит за журналом событий и печатает
сигнал сразу. Печать поверх строки, которую игрок как раз набирает, аккуратно
восстанавливает приглашение и набранный текст — насколько это позволяет
readline.
"""

from __future__ import annotations

import sys
import threading
from typing import Any, Callable

try:                      # readline есть не везде, без него просто печатаем
    import readline
except ImportError:       # pragma: no cover
    readline = None       # type: ignore[assignment]

from .session import EventLog


class Наблюдатель:
    """Фоновое слежение за журналом событий."""

    def __init__(self, журнал: EventLog, обработчик: Callable[[dict[str, Any]], None],
                 интервал: float = 0.4, курсор: int | None = None):
        self.журнал = журнал
        self.обработчик = обработчик
        self.интервал = интервал
        self.курсор = журнал.size() if курсор is None else курсор
        self._стоп = threading.Event()
        self._поток: threading.Thread | None = None
        #: Захватывается на время печати, чтобы вывод не перемешался.
        self.замок = threading.Lock()

    # ------------------------------------------------------------- жизненный цикл
    def запустить(self) -> "Наблюдатель":
        if self._поток is not None:
            return self
        self._поток = threading.Thread(target=self._цикл, name="энтропия-события",
                                       daemon=True)
        self._поток.start()
        return self

    def остановить(self) -> None:
        self._стоп.set()
        поток = self._поток
        if поток is not None and поток.is_alive():
            поток.join(timeout=self.интервал * 3)
        self._поток = None

    def __enter__(self) -> "Наблюдатель":
        return self.запустить()

    def __exit__(self, *_: object) -> None:
        self.остановить()

    # ---------------------------------------------------------------------- цикл
    def _цикл(self) -> None:
        while not self._стоп.wait(self.интервал):
            try:
                self.проверить()
            except Exception:      # фоновый поток не имеет права уронить игру
                continue

    def проверить(self) -> list[dict[str, Any]]:
        """Разбирает накопившиеся события. Вызывается и вручную, и из потока."""
        события, self.курсор = self.журнал.tail(self.курсор)
        for событие in события:
            with self.замок:
                self.обработчик(событие)
        return события


def печать_поверх_ввода(вывести: Callable[[], None]) -> None:
    """Печатает сообщение, не съев приглашение и набранный игроком текст.

    Пока игрок набирает команду, курсор стоит в его строке. Мы уводим строку,
    печатаем сообщение и просим readline перерисовать приглашение вместе с
    тем, что уже набрано.
    """
    if sys.stdout.isatty():
        sys.stdout.write("\r\033[2K")     # в начало строки и стереть её
        sys.stdout.flush()
    вывести()
    if readline is not None and sys.stdout.isatty():
        try:
            приглашение = readline.get_line_buffer()
            if приглашение:
                sys.stdout.write(приглашение)
                sys.stdout.flush()
            readline.redisplay()
        except Exception:                  # pragma: no cover — зависит от сборки
            pass
