"""Общая подготовка временного окружения для тестов."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from entropy import paths

DATA = paths.DATA_DIR


class QuestTestCase(unittest.TestCase):
    """Временный каталог + конфигурация, указывающая на копии данных."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="энтропия-тест-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self.data = self.tmp / "data"
        self.data.mkdir()
        for name in ("complex.json", "stages.json", "persona.json", "quest.json"):
            shutil.copy(DATA / name, self.data / name)
        shutil.copytree(DATA / "canned", self.data / "canned")
        (self.data / "scenario").mkdir()
        shutil.copy(DATA / "scenario" / "default.json", self.data / "scenario" / "default.json")

        self.root = self.tmp / "квест"
        self.config_path = self.tmp / "config.json"
        self.config_path.write_text(json.dumps({
            "files": {
                "quest": str(self.data / "quest.json"),
                "complex": str(self.data / "complex.json"),
                "stages": str(self.data / "stages.json"),
                "persona": str(self.data / "persona.json"),
                "scenario": str(self.data / "scenario" / "default.json"),
                "canned_dir": str(self.data / "canned"),
            },
            "session": {
                "state_dir": str(self.tmp / "state"),
                "state_file": str(self.tmp / "state" / "session.json"),
                "events_file": str(self.tmp / "state" / "events.jsonl"),
                "history_file": str(self.tmp / "state" / "chat.json"),
            },
            "terminal": {"sandbox_root": str(self.root)},
            "chat": {"delay_min_sec": 0, "delay_max_sec": 0, "typewriter_cps": 0},
            "ui": {"color": False, "bell": False, "flash_frames": 0},
        }, ensure_ascii=False), encoding="utf-8")

        # Файл возможностей в репозитории мог остаться после прошлой партии —
        # тесты всегда начинают с «неактивно».
        from entropy.complexctl import CONFIRM_WORD, ComplexMap
        ComplexMap(self.data / "complex.json").reset(CONFIRM_WORD)

    def load_config(self) -> dict:
        from entropy import config
        return config.load(self.config_path)

    def constants(self):
        """Константы квеста из временной копии данных."""
        from entropy.quest import Constants
        return Constants(self.data / "quest.json")
