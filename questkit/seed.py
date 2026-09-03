"""Генератор файловой системы-головоломки (раздел 2 ТЗ).

Раскладывает по каталогам виртуальной машины три вида файлов:

1. повреждённые или переименованные — настоящий формат надо опознать
   (``file``) и восстановить (``mv``, ``gunzip``, ``unzip``, ``base64 -d``,
   ``rev``, ``chmod``);
2. обычные текстовые записки и подсказки;
3. журналы событий, описывающие происходившее до исчезновения персонала.

Раскладка описана в ``data/scenario/default.json``, поэтому для новой партии
достаточно поправить JSON и запустить скрипт заново — код трогать не нужно.

Команды::

    python3 run_seed.py разложить              # разложить файлы
    python3 run_seed.py разложить --перезаписать
    python3 run_seed.py проверить              # проверить раскладку
    python3 run_seed.py шпаргалка              # решения для ведущего
    python3 run_seed.py очистить --да          # убрать файлы после партии
"""

from __future__ import annotations

import argparse
import base64
import gzip
import io
import json
import os
import shutil
import stat
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Any

from . import config, paths, constants as constants_mod, schema, ui
from . import i18n
from .i18n import t
from .pngtext import write_png

#: Файл-маркер в корне раскладки: без него «очистить» ничего не удаляет.
MARKER = ".квест-энтропия"

#: Сигнатуры для команды «проверить».
SIGNATURES = {
    "gzip": b"\x1f\x8b",
    "zip": b"PK\x03\x04",
    "png": b"\x89PNG\r\n\x1a\n",
}


def _lines(entry: dict[str, Any]) -> list[str]:
    """Содержимое файла: список строк или одна строка с переводами строк."""
    строки = schema.поле(entry, "строки")
    if строки is not None:
        return [str(line) for line in строки]
    return str(schema.поле(entry, "содержимое", "")).splitlines()


def _text(entry: dict[str, Any]) -> str:
    body = "\n".join(_lines(entry))
    return body + "\n" if body else ""


# ------------------------------------------------------------------ создание
def _write_plain(path: Path, entry: dict[str, Any]) -> None:
    path.write_text(_text(entry), encoding="utf-8")


def _write_gzip(path: Path, entry: dict[str, Any]) -> None:
    with gzip.open(path, "wb") as fh:
        fh.write(_text(entry).encode("utf-8"))


def _write_zip(path: Path, entry: dict[str, Any]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in schema.поле(entry, "вложения", {}).items():
            body = "\n".join(content) if isinstance(content, list) else str(content)
            archive.writestr(name, body + "\n")


def _write_tar(path: Path, entry: dict[str, Any]) -> None:
    with tarfile.open(path, "w") as archive:
        for name, content in entry.get("вложения", {}).items():
            body = ("\n".join(content) if isinstance(content, list) else str(content)) + "\n"
            data = body.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = int(time.time())
            archive.addfile(info, io.BytesIO(data))


def _write_png(path: Path, entry: dict[str, Any]) -> None:
    write_png(path, [str(line) for line in schema.поле(entry, "надписи", [])],
              schema.поле(entry, "заметки", {}), int(schema.поле(entry, "масштаб", 6)))


def _write_base64(path: Path, entry: dict[str, Any]) -> None:
    encoded = base64.b64encode(_text(entry).encode("utf-8")).decode("ascii")
    wrapped = "\n".join(encoded[i:i + 76] for i in range(0, len(encoded), 76))
    path.write_text(wrapped + "\n", encoding="utf-8")


def _write_reverse(path: Path, entry: dict[str, Any]) -> None:
    """Каждая строка задом наперёд — разбирается командой ``rev``."""
    path.write_text("\n".join(line[::-1] for line in _lines(entry)) + "\n", encoding="utf-8")


def _write_tac(path: Path, entry: dict[str, Any]) -> None:
    """Строки в обратном порядке — разбирается командой ``tac``."""
    path.write_text("\n".join(reversed(_lines(entry))) + "\n", encoding="utf-8")


def _write_xor(path: Path, entry: dict[str, Any]) -> None:
    """Побайтовый XOR: разбирается только скриптом (python3 в ВМ есть)."""
    key = int(schema.поле(entry, "ключ", 42)) & 0xFF
    data = _text(entry).encode("utf-8")
    path.write_bytes(bytes(byte ^ key for byte in data))


WRITERS = {
    "текст": _write_plain,
    "записка": _write_plain,
    "журнал": _write_plain,
    "gzip": _write_gzip,
    "zip": _write_zip,
    "tar": _write_tar,
    "png": _write_png,
    "base64": _write_base64,
    "реверс": _write_reverse,
    "перестановка_строк": _write_tac,
    "xor": _write_xor,
}


class Seeder:
    """Раскладка файлов-головоломок по сценарию."""

    def __init__(self, scenario_path: str | os.PathLike, root: str | os.PathLike | None = None,
                 constants: "constants_mod.Constants | None" = None):
        self.path = paths.resolve(scenario_path)
        if not self.path.exists():
            raise FileNotFoundError(f"файл сценария не найден: {self.path}")
        self.constants = (constants if constants is not None
                          else constants_mod.для_файла(self.path))
        сырое = json.loads(self.path.read_text(encoding="utf-8"))
        self.scenario: dict[str, Any] = self.constants.render(сырое)
        self.root = paths.expand(root or schema.поле(self.scenario, "корень", "~/квест"))
        self.marker = schema.поле(self.scenario, "маркер", MARKER)

    @property
    def files(self) -> list[dict[str, Any]]:
        return list(schema.поле(self.scenario, "файлы", []))

    # ------------------------------------------------------------- раскладка
    def seed(self, overwrite: bool = False) -> list[Path]:
        if self.root.exists() and overwrite:
            self.wipe(confirmed=True, quiet=True)
        self.root.mkdir(parents=True, exist_ok=True)

        for directory in schema.поле(self.scenario, "каталоги", []):
            (self.root / directory).mkdir(parents=True, exist_ok=True)

        created: list[Path] = []
        for entry in self.files:
            target = self.root / schema.поле(entry, "путь")
            target.parent.mkdir(parents=True, exist_ok=True)
            kind = schema.тип_файла(schema.поле(entry, "тип", "текст"))
            writer = WRITERS.get(kind)
            if writer is None:
                ui.error(t("seed.unknown_type", тип=kind, путь=schema.поле(entry, "путь"),
                           type=kind, path=schema.поле(entry, "путь")))
                continue
            if target.exists():
                target.chmod(0o644)  # чтобы перезапись не спотыкалась о права
            writer(target, entry)
            права = schema.поле(entry, "права")
            if права:
                target.chmod(int(str(права), 8))
            отметка = schema.поле(entry, "время")
            if отметка:
                stamp = time.mktime(time.strptime(отметка, "%Y-%m-%d %H:%M:%S"))
                os.utime(target, (stamp, stamp))
            created.append(target)

        marker_path = self.root / self.marker
        marker_path.write_text(json.dumps({
            "сценарий": schema.поле(self.scenario, "название", self.path.name),
            "файл_сценария": str(self.path),
            "разложено": time.strftime("%Y-%m-%d %H:%M:%S"),
            "файлов": len(created),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return created

    # -------------------------------------------------------------- проверка
    def verify(self) -> tuple[list[str], list[str]]:
        ok: list[str] = []
        bad: list[str] = []
        if not self.root.is_dir():
            return ok, [f"нет корневого каталога: {self.root}"]
        for entry in self.files:
            путь = schema.поле(entry, "путь")
            target = self.root / путь
            kind = schema.тип_файла(schema.поле(entry, "тип", "текст"))
            if not target.exists():
                bad.append(f"{путь}: файла нет")
                continue
            if target.stat().st_size == 0:
                bad.append(f"{путь}: файл пуст")
                continue
            signature = SIGNATURES.get(kind)
            if signature:
                mode = target.stat().st_mode
                if not mode & stat.S_IRUSR:
                    ok.append(f"{entry['путь']}: {kind} (проверка сигнатуры пропущена: нет прав)")
                    continue
                with target.open("rb") as fh:
                    head = fh.read(len(signature))
                if head != signature:
                    bad.append(f"{путь}: сигнатура не похожа на {kind}")
                    continue
            права = schema.поле(entry, "права")
            if права:
                actual = oct(target.stat().st_mode & 0o777)[2:].rjust(3, "0")
                if actual != str(права).rjust(3, "0"):
                    bad.append(f"{путь}: права {actual}, ожидались {права}")
                    continue
            ok.append(f"{путь}: {kind}")
        return ok, bad

    # --------------------------------------------------------------- очистка
    def wipe(self, confirmed: bool = False, quiet: bool = False) -> bool:
        """Удаляет раскладку. Без маркера и подтверждения ничего не трогает."""
        if not self.root.exists():
            if not quiet:
                ui.error(t("seed.no_dir", путь=self.root, path=self.root))
            return False
        home = Path.home().resolve()
        resolved = self.root.resolve()
        if resolved == Path("/") or resolved == home or len(resolved.parts) <= 2:
            ui.error(t("seed.too_high", путь=resolved, path=resolved))
            return False
        if not (self.root / self.marker).exists():
            ui.error(t("seed.no_marker", путь=self.root, маркер=self.marker,
                       path=self.root, marker=self.marker))
            return False
        if not confirmed:
            ui.error(t("seed.need_confirm"))
            return False
        for item in self.root.rglob("*"):
            if item.is_file() or item.is_symlink():
                try:
                    item.chmod(0o644)
                except OSError:
                    pass
        shutil.rmtree(self.root)
        return True

    # ------------------------------------------------------------- шпаргалка
    def cheatsheet(self) -> str:
        имя_раскладки = schema.поле(self.scenario, "название", self.path.name)
        lines = [
            "# " + t("seed.cheatsheet_title", название=имя_раскладки, name=имя_раскладки),
            "",
            t("seed.cheatsheet_root", путь=self.root, path=self.root),
            "",
        ]
        for entry in self.files:
            lines.append(f"## {schema.поле(entry, 'путь')}  "
                         f"({schema.тип_файла(schema.поле(entry, 'тип', 'текст'))})")
            права = schema.поле(entry, "права")
            if права:
                lines.append(f'- {t("seed.cheatsheet_mode")}: {права}')
            разгадка = schema.поле(entry, "разгадка")
            if разгадка:
                lines.append(f'- {t("seed.cheatsheet_solution")}: {разгадка}')
            подсказка = schema.поле(entry, "подсказка")
            if подсказка:
                lines.append(f'- {t("seed.cheatsheet_hint")}: {подсказка}')
            lines.append("")
        return "\n".join(lines)


# ------------------------------------------------------------------ командная
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_seed.py",
        description="Раскладка файлов-головоломок для квеста квеста",
    )
    parser.add_argument("команда", nargs="?", default="разложить",
                        choices=["разложить", "проверить", "очистить", "шпаргалка", "список"],
                        help="что сделать (по умолчанию: разложить)")
    parser.add_argument("--конфиг", "--config", dest="config", default=None)
    parser.add_argument("--раскладка", "--сценарий", "--layout", dest="layout", default=None,
                        help="файл раскладки (по умолчанию layout.json активного пакета)")
    parser.add_argument("--корень", "--root", dest="root", default=None,
                        help="куда раскладывать (перебивает «корень» из сценария)")
    parser.add_argument("--перезаписать", "--overwrite", dest="overwrite", action="store_true",
                        help="удалить прежнюю раскладку и собрать заново")
    parser.add_argument("--случайный-код", "--random-code", dest="random_code",
                        action="store_true",
                        help="выдать новый случайный код двери на эту партию")
    parser.add_argument("--да", "--yes", dest="yes", action="store_true",
                        help="подтвердить удаление раскладки")
    parser.add_argument("--в-файл", "--out", dest="out", default=None,
                        help="сохранить шпаргалку в файл")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config.load(args.config)
    i18n.init(cfg)
    ui.init(cfg)
    # Раскладка ищется внутри активного пакета, если путь не задан явно.
    scenario = args.layout or config.data_file(cfg, "layout")
    константы = constants_mod.Constants(config.data_file(cfg, "constants"))
    if args.random_code and args.команда == "разложить":
        новый = константы.randomize_door_code()
        print(ui.c(t("seed.random_code", код=новый, code=новый), "жёлтый", "жирный"))
    # Куда раскладывать: ключ командной строки, затем sandbox_root из
    # настроек (там же начинают игроки), и лишь потом «корень» из раскладки.
    корень = args.root or cfg["terminal"].get("sandbox_root")
    try:
        seeder = Seeder(scenario, корень, константы)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        ui.error(str(exc))
        return 2

    command = args.команда
    if command == "разложить":
        созданные = seeder.seed(overwrite=args.overwrite)
        имя_раскладки = schema.поле(seeder.scenario, "название", str(scenario))
        print(ui.box(t("seed.done_title"), [
            t("seed.scenario", название=имя_раскладки, name=имя_раскладки),
            t("seed.root", путь=seeder.root, path=seeder.root),
            t("seed.count", число=len(созданные), count=len(созданные)),
            "",
            t("seed.next.verify"),
            t("seed.next.cheatsheet"),
            t("seed.next.terminal"),
        ], "зелёный"))
        return 0

    if command in ("проверить", "список"):
        ok, bad = seeder.verify()
        for line in ok:
            print(ui.c("  ok   ", "зелёный") + line)
        for line in bad:
            print(ui.c("  ОШИБКА ", "красный") + line)
        print("\n" + t("seed.total", хорошо=len(ok), плохо=len(bad), ok=len(ok), bad=len(bad)))
        return 1 if bad else 0

    if command == "шпаргалка":
        text = seeder.cheatsheet()
        if args.out:
            out = paths.resolve(args.out)
            out.write_text(text, encoding="utf-8")
            print(t("seed.cheatsheet_saved", файл=out, file=out))
        else:
            print(text)
        return 0

    if command == "очистить":
        done = seeder.wipe(confirmed=args.yes)
        if done:
            print(ui.c(t("seed.wiped", путь=seeder.root, path=seeder.root), "зелёный"))
        return 0 if done else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
