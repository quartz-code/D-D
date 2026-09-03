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
from typing import Any, Callable

from . import config, deepseek, constants as constants_mod, session as session_mod, ui
from .i18n import t

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
        отчёт.добавить(t("doctor.python"), ОК, f"{версия.major}.{версия.minor}.{версия.micro}")
    else:
        отчёт.добавить(t("doctor.python"), ОШИБКА, f"{версия.major}.{версия.minor}",
                       t("doctor.python.old"))

    текущая = (os.environ.get("LC_ALL") or os.environ.get("LC_CTYPE")
               or os.environ.get("LANG") or locale.getpreferredencoding(False) or "")
    if "utf" in текущая.lower():
        отчёт.добавить(t("doctor.locale"), ОК, текущая)
    else:
        отчёт.добавить(t("doctor.locale"), ПРЕДУПРЕЖДЕНИЕ, текущая or "не задана",
                       t("doctor.locale.advice"))

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        отчёт.добавить(t("doctor.user"), ПРЕДУПРЕЖДЕНИЕ, "root",
                       t("doctor.user.root"))
    else:
        отчёт.добавить(t("doctor.user"), ОК, t("doctor.user.normal"))

    отчёт.добавить(t("doctor.tmux"), ОК if shutil.which("tmux") else ПРЕДУПРЕЖДЕНИЕ,
                   t("doctor.yes") if shutil.which("tmux") else t("doctor.no"),
                   "" if shutil.which("tmux") else t("doctor.tmux.advice"))

    отсутствуют = [имя for имя in ("file", "gzip", "unzip", "tar", "base64", "rev", "tac")
                   if not shutil.which(имя)]
    if отсутствуют:
        отчёт.добавить(t("doctor.tools"), ПРЕДУПРЕЖДЕНИЕ,
                       t("doctor.tools.missing", список=", ".join(отсутствуют),
                         list=", ".join(отсутствуют)),
                       t("doctor.tools.advice"))
    else:
        отчёт.добавить(t("doctor.tools"), ОК, t("doctor.tools.ok"))


def проверить_конфигурацию(отчёт: Отчёт, cfg: dict) -> None:
    if cfg.get("_конфиг_найден"):
        отчёт.добавить(t("doctor.config"), ОК, cfg.get("_путь_конфига", ""))
    else:
        отчёт.добавить(t("doctor.config"), ПРЕДУПРЕЖДЕНИЕ,
                       t("doctor.config.missing", путь=cfg.get("_путь_конфига"),
                         path=cfg.get("_путь_конфига")),
                       t("doctor.config.advice"))

    ключ = config.api_key(cfg)
    if ключ:
        отчёт.добавить(t("doctor.api_key"), ОК, config.mask_key(ключ))
    else:
        отчёт.добавить(t("doctor.api_key"), ПРЕДУПРЕЖДЕНИЕ, t("doctor.api_key.missing"),
                       t("doctor.api_key.advice"))


def проверить_данные(отчёт: Отчёт, cfg: dict) -> None:
    for имя in ("constants", "world", "stages", "persona", "layout"):
        путь = config.data_file(cfg, имя)
        if not путь.exists():
            отчёт.добавить(t("doctor.data_file", имя=имя, name=имя), ОШИБКА,
                           t("doctor.file.missing", путь=путь, path=путь))
            continue
        try:
            json.loads(путь.read_text(encoding="utf-8"))
        except json.JSONDecodeError as ошибка:
            отчёт.добавить(t("doctor.data_file", имя=имя, name=имя), ОШИБКА,
                           t("doctor.file.bad_json", ошибка=ошибка, error=ошибка),
                           t("doctor.file.bad_json_advice"))
            continue
        отчёт.добавить(t("doctor.data_file", имя=имя, name=имя), ОК, путь.name)


def проверить_константы(отчёт: Отчёт, cfg: dict) -> None:
    """Ищет ссылки {{имя}}, которым не нашлось значения."""
    try:
        константы = constants_mod.Constants(config.data_file(cfg, "constants"))
    except (FileNotFoundError, ValueError) as ошибка:
        отчёт.добавить(t("doctor.constants"), ОШИБКА, str(ошибка))
        return

    потерянные: set[str] = set()
    for имя in ("world", "stages", "persona", "layout"):
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
        отчёт.добавить(t("doctor.constants"), ОШИБКА,
                       t("doctor.constants.missing", список=", ".join(sorted(потерянные)),
                         list=", ".join(sorted(потерянные))),
                       t("doctor.constants.advice"))
    else:
        сводка = ", ".join(f"{к}={з}" for к, з in list(константы.values.items())[:3]) or "—"
        отчёт.добавить(t("doctor.constants"), ОК, сводка)


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
        отчёт.добавить(t("doctor.canned"), ОШИБКА,
                       t("doctor.canned.missing", список=", ".join(пропавшие),
                         list=", ".join(пропавшие)),
                       t("doctor.canned.advice", путь=каталог, path=каталог))
    else:
        отчёт.добавить(t("doctor.canned"), ОК,
                       t("doctor.canned.ok", число=всего, count=всего))


def проверить_раскладку(отчёт: Отчёт, cfg: dict) -> None:
    from .seed import Seeder
    try:
        seeder = Seeder(config.data_file(cfg, "layout"),
                        cfg["terminal"].get("sandbox_root"))
    except (FileNotFoundError, json.JSONDecodeError) as ошибка:
        отчёт.добавить(t("doctor.layout"), ОШИБКА, str(ошибка))
        return
    if not seeder.root.is_dir():
        отчёт.добавить(t("doctor.layout"), ОШИБКА,
                       t("doctor.layout.no_dir", путь=seeder.root, path=seeder.root),
                       t("doctor.layout.advice"))
        return
    порядок, беда = seeder.verify()
    if беда:
        отчёт.добавить(t("doctor.layout"), ОШИБКА,
                       t("doctor.layout.broken", число=len(беда), список="; ".join(беда[:3]),
                         count=len(беда), list="; ".join(беда[:3])),
                       t("doctor.layout.rebuild"))
    else:
        отчёт.добавить(t("doctor.layout"), ОК,
                       t("doctor.layout.ok", число=len(порядок), путь=seeder.root,
                         count=len(порядок), path=seeder.root))


def проверить_состояние(отчёт: Отчёт, cfg: dict) -> None:
    from .world import ComplexMap
    сессия, журнал = session_mod.open_session(cfg)
    данные = сессия.load()
    израсходовано = int(данные.get("сообщений_израсходовано", 0) or 0)

    try:
        карта = ComplexMap(config.data_file(cfg, "world"))
        применённые = карта.all_active()
    except (FileNotFoundError, ValueError):
        применённые = []

    остатки = []
    if израсходовано:
        остатки.append(t("doctor.state.messages", число=израсходовано, count=израсходовано))
    if применённые:
        остатки.append(t("doctor.state.actions",
                         список=", ".join(f"{к}/{д}" for к, д in применённые),
                         list=", ".join(f"{к}/{д}" for к, д in применённые)))
    if данные.get("этап") not in (None, "", "шлюз"):
        остатки.append(t("doctor.state.stage", этап=данные.get("этап"),
                         stage=данные.get("этап")))

    if остатки:
        отчёт.добавить(t("doctor.party_state"), ПРЕДУПРЕЖДЕНИЕ, "; ".join(остатки),
                       t("doctor.state.advice"))
    else:
        отчёт.добавить(t("doctor.party_state"), ОК, t("doctor.state.clean"))


def проверить_связь(отчёт: Отчёт, cfg: dict) -> None:
    """Пробное обращение к модели — единственная проверка, которая ходит в сеть."""
    if not config.api_key(cfg):
        отчёт.добавить(t("doctor.model"), ПРЕДУПРЕЖДЕНИЕ, t("doctor.model.skipped"))
        return
    try:
        клиент = deepseek.DeepSeekClient(cfg)
        ответ, расход = клиент.chat([
            {"role": "system", "content": "Ответь одним словом: готов"},
            {"role": "user", "content": "проверка связи"},
        ])
    except deepseek.DeepSeekError as ошибка:
        отчёт.добавить(t("doctor.model"), ОШИБКА, str(ошибка)[:160])
        return
    отчёт.добавить(t("doctor.model"), ОК,
                   t("doctor.model.ok", модель=cfg["deepseek"]["model"],
                     ответ=ответ[:40].strip(), токены=расход.get("total_tokens", "?"),
                     model=cfg["deepseek"]["model"], answer=ответ[:40].strip(),
                     tokens=расход.get("total_tokens", "?")))


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
    значки = {ОК: (t("doctor.mark.ok"), "зелёный"),
              ПРЕДУПРЕЖДЕНИЕ: (t("doctor.mark.warning"), "жёлтый"),
              ОШИБКА: (t("doctor.mark.error"), "красный")}
    print(ui.box(t("doctor.title"), [], "голубой"))
    for строка in отчёт.строки:
        значок, цвет = значки.get(строка.состояние, ("    ?    ", "белый"))
        print(ui.c(значок, цвет) + f" {строка.название}: {строка.подробность}")
        if строка.совет:
            for кусок in _перенос(строка.совет, 66):
                print(ui.c(f"           └ {кусок}", "тусклый"))
    print()
    if отчёт.готово and not отчёт.предупреждений:
        print(ui.c(t("doctor.verdict.ready"), "зелёный", "жирный"))
    elif отчёт.готово:
        print(ui.c(t("doctor.verdict.warnings", число=отчёт.предупреждений,
                     count=отчёт.предупреждений), "жёлтый", "жирный"))
    else:
        print(ui.c(t("doctor.verdict.not_ready", число=отчёт.ошибок, count=отчёт.ошибок),
                   "красный", "жирный"))


def _перенос(текст: str, ширина: int) -> list[str]:
    import textwrap
    return textwrap.wrap(текст, ширина) or [текст]
