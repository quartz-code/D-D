"""Реестр необязательных возможностей квеста.

Всё, что добавлено сверх базового квеста, включается и выключается отдельно:
ведущий отмечает нужное в пусковом окне (``run_launcher.py``) или правит
секцию ``features`` в ``config/config.json``. Базовый квест работает при всех
выключенных возможностях.

Этот модуль — единственное место, где список возможностей описан целиком:
и окно с галочками, и приложения читают его отсюда.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .i18n import t

#: Раздел конфигурации, в котором хранятся отметки.
РАЗДЕЛ = "features"


@dataclass(frozen=True)
class Возможность:
    """Одна необязательная возможность.

    ``название`` и ``описание`` — ключи каталога переводов: список
    возможностей должен читаться на языке интерфейса.
    """

    ключ: str
    _название: str
    _описание: str
    по_умолчанию: bool = False
    #: Проверка, доступна ли возможность в этой системе. Возвращает
    #: (доступна, пояснение). Нужна, например, озвучке: без синтезатора речи
    #: включать её бессмысленно.
    проверка: Callable[[], tuple[bool, str]] | None = None

    @property
    def название(self) -> str:
        return t(self._название)

    @property
    def описание(self) -> str:
        return t(self._описание)

    def доступна(self) -> tuple[bool, str]:
        if self.проверка is None:
            return True, ""
        try:
            return self.проверка()
        except Exception as ошибка:            # проверка не должна ронять окно
            return False, f"проверка не удалась: {ошибка}"


def _проверить_озвучку() -> tuple[bool, str]:
    from . import voice
    движок = voice.найти_движок()
    if движок:
        return True, t("features.voice.found", движок=движок[0], engine=движок[0])
    return False, t("features.voice.missing")


#: Полный список. Порядок — как в пусковом окне.
СПИСОК: list[Возможность] = [
    Возможность("журнал_партии", "features.journal.name", "features.journal.about", True),
    Возможность("живое_оповещение", "features.alerts.name", "features.alerts.about", True),
    Возможность("потоковый_ответ", "features.stream.name", "features.stream.about", False),
    Возможность("озвучка", "features.voice.name", "features.voice.about", False,
                _проверить_озвучку),
]

ПО_КЛЮЧУ = {в.ключ: в for в in СПИСОК}


def умолчания() -> dict[str, bool]:
    return {в.ключ: в.по_умолчанию for в in СПИСОК}


def включена(cfg: dict, ключ: str) -> bool:
    """Отмечена ли возможность в конфигурации."""
    раздел = cfg.get(РАЗДЕЛ) or {}
    if ключ in раздел:
        return bool(раздел[ключ])
    возможность = ПО_КЛЮЧУ.get(ключ)
    return bool(возможность.по_умолчанию) if возможность else False


def выбранные(cfg: dict) -> dict[str, bool]:
    return {в.ключ: включена(cfg, в.ключ) for в in СПИСОК}


def описание_состояния(cfg: dict) -> list[str]:
    """Строки «возможность — включена/выключена» для статуса и отчёта."""
    строки = []
    for в in СПИСОК:
        отметка = t("features.on") if включена(cfg, в.ключ) else t("features.off")
        доступна, пояснение = в.доступна()
        if not доступна and включена(cfg, в.ключ):
            отметка = t("features.on_but_unavailable", причина=пояснение, reason=пояснение)
        строки.append(f"{в.название}: {отметка}")
    return строки
