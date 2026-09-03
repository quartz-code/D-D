"""Проверка готовности к партии.

Отвечает на единственный вопрос: «можно начинать?» Раньше это был список в
голове ведущего — ключ на месте, файлы разложены, состояние сброшено, играем
не из-под root. Половина проблем всплывала уже посреди игры.

Запуск::

    python3 run_master.py проверка          # без обращений к сети
    python3 run_master.py проверка --живой  # плюс пробный запрос к модели
"""

from __future__ import annotations

import json
import locale
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import config, deepseek, paths, quest as quest_mod, session as session_mod, ui

ОК, ПРЕДУПРЕЖДЕНИЕ, ОШИБКА = "ок", "внимание", "ошибка"


@dataclass
class Результат:
    """Итог одной проверки."""

    название: str
    состояние: str
    подробность: str = ""
    совет: str = ""


@dataclass
class Отчёт:
    """Итог всех проверок."""

    строки: list[Результат] = field(default_factory=list)

    def добавить(self, название: str, состояние: str, подробность: str = "",
                 совет: str = "") -> Результат:
        строка = Результат(название, состояние, подробность, совет)
        self.строки.append(строка)
        return строка

    @property
    def ошибок(self) -> int:
        return sum(1 for s in self.строки if s.состояние == ОШИБКА)

    @property
    def предупреждений(self) -> int:
        return sum(1 for s in self.строки if s.состояние == ПРЕДУПРЕЖДЕНИЕ)

    @property
    def готово(self) -> bool:
        return self.ошибок == 0


# --------------------------------------------------------------------- проверки
def проверить_окружение(отчёт: Отчёт) -> None:
    версия = sys.version_info
    if версия >= (3, 9):
        отчёт.добавить("Python", ОК, f"{версия.major}.{версия.minor}.{версия.micro}")
    else:
        отчёт.добавить("Python", ОШИБКА, f"{версия.major}.{версия.minor}",
                       "нужен Python 3.9 или новее")

    текущая = (os.environ.get("LC_ALL") or os.environ.get("LC_CTYPE")
               or os.environ.get("LANG") or locale.getpreferredencoding(False) or "")
    if "utf" in текущая.lower():
        отчёт.добавить("Локаль UTF-8", ОК, текущая)
    else:
        отчёт.добавить("Локаль UTF-8", ПРЕДУПРЕЖДЕНИЕ, текущая or "не задана",
                       "терминал сам подставит C.UTF-8 дочерним командам; "
                       "для остального стоит выставить UTF-8-локаль в системе")

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        отчёт.добавить("Пользователь", ПРЕДУПРЕЖДЕНИЕ, "root",
                       "под root головоломка с правами доступа не работает: "
                       "файл читается без chmod. Играйте от обычного пользователя")
    else:
        отчёт.добавить("Пользователь", ОК, "обычный (не root)")

    отчёт.добавить("tmux", ОК if shutil.which("tmux") else ПРЕДУПРЕЖДЕНИЕ,
                   "есть" if shutil.which("tmux") else "нет",
                   "" if shutil.which("tmux") else
                   "не обязателен: три окна можно открыть вручную")

    отсутствуют = [имя for имя in ("file", "gzip", "unzip", "tar", "base64", "rev", "tac")
                   if not shutil.which(имя)]
    if отсутствуют:
        отчёт.добавить("Утилиты для головоломок", ПРЕДУПРЕЖДЕНИЕ,
                       "нет: " + ", ".join(отсутствуют),
                       "без них часть головоломок не решается штатными средствами")
    else:
        отчёт.добавить("Утилиты для головоломок", ОК, "все на месте")


def проверить_конфигурацию(отчёт: Отчёт, cfg: dict) -> None:
    if cfg.get("_конфиг_найден"):
        отчёт.добавить("Файл настроек", ОК, cfg.get("_путь_конфига", ""))
    else:
        отчёт.добавить("Файл настроек", ПРЕДУПРЕЖДЕНИЕ,
                       f"{cfg.get('_путь_конфига')} не найден — взяты умолчания",
                       "скопируйте config/config.example.json в config/config.json")

    ключ = config.api_key(cfg)
    if ключ:
        отчёт.добавить("Ключ API", ОК, config.mask_key(ключ))
    else:
        отчёт.добавить("Ключ API", ПРЕДУПРЕЖДЕНИЕ, "не задан",
                       "без ключа доступен только режим --офлайн: "
                       "export DEEPSEEK_API_KEY=…")


def проверить_данные(отчёт: Отчёт, cfg: dict) -> None:
    for имя in ("quest", "complex", "stages", "persona", "scenario"):
        путь = config.data_file(cfg, имя)
        if not путь.exists():
            отчёт.добавить(f"Файл данных «{имя}»", ОШИБКА, f"{путь} не найден")
            continue
        try:
            json.loads(путь.read_text(encoding="utf-8"))
        except json.JSONDecodeError as ошибка:
            отчёт.добавить(f"Файл данных «{имя}»", ОШИБКА, f"битый JSON: {ошибка}",
                           "проверьте запятые и кавычки")
            continue
        отчёт.добавить(f"Файл данных «{имя}»", ОК, путь.name)


def проверить_константы(отчёт: Отчёт, cfg: dict) -> None:
    """Ищет ссылки {{имя}}, которым не нашлось значения."""
    try:
        константы = quest_mod.Constants(config.data_file(cfg, "quest"))
    except (FileNotFoundError, ValueError) as ошибка:
        отчёт.добавить("Константы квеста", ОШИБКА, str(ошибка))
        return

    потерянные: set[str] = set()
    for имя in ("complex", "stages", "persona", "scenario"):
        путь = config.data_file(cfg, имя)
        if путь.exists():
            try:
                потерянные |= константы.missing(json.loads(путь.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
    каталог = config.data_file(cfg, "canned_dir")
    if каталог.is_dir():
        for файл in каталог.glob("*.txt"):
            потерянные |= константы.missing(файл.read_text(encoding="utf-8"))

    if потерянные:
        отчёт.добавить("Константы квеста", ОШИБКА,
                       "ссылки без значения: " + ", ".join(sorted(потерянные)),
                       "добавьте их в data/quest.json — иначе игроки увидят «{{…}}»")
    else:
        отчёт.добавить("Константы квеста", ОК,
                       f"код двери {константы.get('код_двери', '—')}, "
                       f"объект {константы.get('объект', '—')}")


def проверить_заготовки(отчёт: Отчёт, cfg: dict) -> None:
    """Каждая сценарная команда должна находить свой файл-заготовку."""
    путь = config.data_file(cfg, "stages")
    каталог = config.data_file(cfg, "canned_dir")
    if not путь.exists():
        return
    try:
        этапы = json.loads(путь.read_text(encoding="utf-8")).get("этапы", {})
    except json.JSONDecodeError:
        return
    пропавшие = []
    всего = 0
    for имя, данные in этапы.items():
        for запись in данные.get("сценарные_команды", []):
            файл = запись.get("файл")
            if not файл:
                continue
            всего += 1
            if not (каталог / файл).exists():
                пропавшие.append(f"{имя}: {файл}")
    if пропавшие:
        отчёт.добавить("Заготовленные ответы", ОШИБКА, "нет файлов: " + ", ".join(пропавшие),
                       f"ожидались в {каталог}")
    else:
        отчёт.добавить("Заготовленные ответы", ОК, f"{всего} шт., все на месте")


def проверить_раскладку(отчёт: Отчёт, cfg: dict) -> None:
    from .seed import Seeder
    try:
        seeder = Seeder(config.data_file(cfg, "scenario"),
                        cfg["terminal"].get("sandbox_root"))
    except (FileNotFoundError, json.JSONDecodeError) as ошибка:
        отчёт.добавить("Раскладка файлов", ОШИБКА, str(ошибка))
        return
    if not seeder.root.is_dir():
        отчёт.добавить("Раскладка файлов", ОШИБКА, f"нет каталога {seeder.root}",
                       "разложите файлы: python3 run_seed.py разложить")
        return
    порядок, беда = seeder.verify()
    if беда:
        отчёт.добавить("Раскладка файлов", ОШИБКА,
                       f"{len(беда)} с ошибками: " + "; ".join(беда[:3]),
                       "пересоберите: python3 run_seed.py разложить --перезаписать")
    else:
        отчёт.добавить("Раскладка файлов", ОК, f"{len(порядок)} файлов в {seeder.root}")


def проверить_состояние(отчёт: Отчёт, cfg: dict) -> None:
    from .complexctl import ComplexMap
    сессия, журнал = session_mod.open_session(cfg)
    данные = сессия.load()
    израсходовано = int(данные.get("сообщений_израсходовано", 0) or 0)

    try:
        карта = ComplexMap(config.data_file(cfg, "complex"))
        применённые = карта.all_active()
    except (FileNotFoundError, ValueError):
        применённые = []

    остатки = []
    if израсходовано:
        остатки.append(f"израсходовано обращений: {израсходовано}")
    if применённые:
        остатки.append("применённые действия: "
                       + ", ".join(f"{к}/{д}" for к, д in применённые))
    if данные.get("этап") not in (None, "", "шлюз"):
        остатки.append(f"этап: {данные.get('этап')}")

    if остатки:
        отчёт.добавить("Состояние партии", ПРЕДУПРЕЖДЕНИЕ, "; ".join(остатки),
                       "это следы прошлой партии. Сброс: python3 run_master.py сброс --да "
                       "и python3 run_chat.py --новая")
    else:
        отчёт.добавить("Состояние партии", ОК, "чистое, можно начинать")


def проверить_связь(отчёт: Отчёт, cfg: dict) -> None:
    """Пробное обращение к модели — единственная проверка, которая ходит в сеть."""
    if not config.api_key(cfg):
        отчёт.добавить("Связь с моделью", ПРЕДУПРЕЖДЕНИЕ, "пропущена: нет ключа")
        return
    try:
        клиент = deepseek.DeepSeekClient(cfg)
        ответ, расход = клиент.chat([
            {"role": "system", "content": "Ответь одним словом: готов"},
            {"role": "user", "content": "проверка связи"},
        ])
    except deepseek.DeepSeekError as ошибка:
        отчёт.добавить("Связь с моделью", ОШИБКА, str(ошибка)[:160])
        return
    отчёт.добавить("Связь с моделью", ОК,
                   f"{cfg['deepseek']['model']} отвечает ({ответ[:40].strip()}…), "
                   f"токенов: {расход.get('total_tokens', '?')}")


ПРОВЕРКИ: list[Callable[..., Any]] = [
    проверить_окружение, проверить_конфигурацию, проверить_данные,
    проверить_константы, проверить_заготовки, проверить_раскладку, проверить_состояние,
]


def проверить(cfg: dict, живой: bool = False) -> Отчёт:
    """Прогоняет весь список проверок и возвращает отчёт."""
    отчёт = Отчёт()
    проверить_окружение(отчёт)
    for проверка in ПРОВЕРКИ[1:]:
        проверка(отчёт, cfg)
    if живой:
        проверить_связь(отчёт, cfg)
    return отчёт


def напечатать(отчёт: Отчёт) -> None:
    """Показывает отчёт ведущему."""
    значки = {ОК: ("  ок     ", "зелёный"), ПРЕДУПРЕЖДЕНИЕ: (" внимание", "жёлтый"),
              ОШИБКА: ("  ОШИБКА ", "красный")}
    print(ui.box("ПРОВЕРКА ГОТОВНОСТИ К ПАРТИИ", [], "голубой"))
    for строка in отчёт.строки:
        значок, цвет = значки.get(строка.состояние, ("    ?    ", "белый"))
        print(ui.c(значок, цвет) + f" {строка.название}: {строка.подробность}")
        if строка.совет:
            for кусок in _перенос(строка.совет, 66):
                print(ui.c(f"           └ {кусок}", "тусклый"))
    print()
    if отчёт.готово and not отчёт.предупреждений:
        print(ui.c("ВСЁ ГОТОВО. Можно начинать партию.", "зелёный", "жирный"))
    elif отчёт.готово:
        print(ui.c(f"Готово, но есть замечания ({отчёт.предупреждений}). "
                   "Играть можно.", "жёлтый", "жирный"))
    else:
        print(ui.c(f"НЕ ГОТОВО: ошибок {отчёт.ошибок}. "
                   "Исправьте отмеченное выше.", "красный", "жирный"))


def _перенос(текст: str, ширина: int) -> list[str]:
    import textwrap
    return textwrap.wrap(текст, ширина) or [текст]
