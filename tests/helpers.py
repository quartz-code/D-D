"""Общая подготовка временного окружения для тестов."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from questkit import paths

ПРИМЕР = paths.EXAMPLES_DIR / "entropy-complex-ru"


class QuestTestCase(unittest.TestCase):
    """Временный каталог + конфигурация, указывающая на копии данных."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="энтропия-тест-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        # Пакет содержимого целиком копируется во временный каталог: тесты
        # не должны трогать пакеты в репозитории.
        self.data = self.tmp / "pack"
        shutil.copytree(ПРИМЕР, self.data)

        self.root = self.tmp / "квест"
        self.config_path = self.tmp / "config.json"
        self.config_path.write_text(json.dumps({
            "content": str(self.data),
            "session": {
                "state_dir": str(self.tmp / "state"),
                "state_file": str(self.tmp / "state" / "session.json"),
                "events_file": str(self.tmp / "state" / "events.jsonl"),
                "history_file": str(self.tmp / "state" / "chat.json"),
                "journal_file": str(self.tmp / "state" / "journal.jsonl"),
            },
            "terminal": {"sandbox_root": str(self.root)},
            "chat": {"delay_min_sec": 0, "delay_max_sec": 0, "typewriter_cps": 0},
            "deepseek": {"retries": 0, "retry_pause_sec": 0},
            "ui": {"color": False, "bell": False, "flash_frames": 0},
        }, ensure_ascii=False), encoding="utf-8")

        # Файл возможностей в репозитории мог остаться после прошлой партии —
        # тесты всегда начинают с «неактивно».
        from questkit.world import CONFIRM_WORD, ComplexMap
        ComplexMap(self.data / "world.json").reset(CONFIRM_WORD)

    def load_config(self) -> dict:
        from questkit import config
        return config.load(self.config_path)

    def constants(self):
        """Константы квеста из временной копии пакета."""
        from questkit.constants import Constants
        return Constants(self.data / "constants.json")
