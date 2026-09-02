"""Клиент DeepSeek API (раздел 4 ТЗ).

Используется только стандартная библиотека: в виртуальной машине ведущего не
нужно ничего доустанавливать. Ключ берётся из конфигурации/переменной
окружения (раздел 9.6 ТЗ) и нигде не печатается целиком.

Если ключа нет или сеть недоступна, приложение чата может работать с
:class:`OfflineClient` — заглушкой для прогона квеста без расхода бюджета.
"""

from __future__ import annotations

import json
import random
import ssl
import urllib.error
import urllib.request
from typing import Any

from . import config


class DeepSeekError(Exception):
    """Ошибка обращения к API."""


class DeepSeekClient:
    """Минимальный клиент /chat/completions."""

    def __init__(self, cfg: dict):
        section = cfg.get("deepseek", {})
        self.base_url = str(section.get("base_url", "https://api.deepseek.com")).rstrip("/")
        self.model = section.get("model", "deepseek-chat")
        self.temperature = float(section.get("temperature", 1.0))
        self.max_tokens = int(section.get("max_tokens", 700))
        self.timeout = float(section.get("timeout_sec", 60))
        self.key = config.api_key(cfg)
        if not self.key:
            raise DeepSeekError(
                "ключ API не задан: впишите его в config/config.json "
                "или в переменную окружения "
                f"{section.get('api_key_env', 'DEEPSEEK_API_KEY')}"
            )

    @property
    def name(self) -> str:
        return f"DeepSeek/{self.model}"

    def chat(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
        """Отправляет переписку в модель и возвращает (ответ, статистика)."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.key}",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout,
                                        context=ssl.create_default_context()) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            hint = ""
            if exc.code in (401, 403):
                hint = " — проверьте ключ API"
            elif exc.code == 402:
                hint = " — исчерпан баланс аккаунта DeepSeek"
            elif exc.code == 429:
                hint = " — слишком часто, подождите несколько секунд"
            raise DeepSeekError(f"HTTP {exc.code}{hint}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise DeepSeekError(f"нет связи с {self.base_url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise DeepSeekError(f"превышено время ожидания ({self.timeout} с)") from exc
        except json.JSONDecodeError as exc:
            raise DeepSeekError(f"некорректный ответ API: {exc}") from exc

        try:
            text = body["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, AttributeError) as exc:
            raise DeepSeekError(f"в ответе API нет текста: {str(body)[:300]}") from exc
        return text, body.get("usage", {}) or {}


class OfflineClient:
    """Заглушка без сети: даёт правдоподобные казённые ответы для репетиции.

    Это НЕ модель: реплики собираются из заготовок. Ведущему это видно по
    пометке в статусе чата.
    """

    ANSWERS = [
        "Предъявите пропуск установленного образца. Предъявите пропуск установленного образца.",
        "Запрос вне компетенции распорядителя смены. Уточните номер допуска.",
        "Регламент не предусматривает обмен сведениями с лицами без допуска.",
        "Присутствие незарегистрированных лиц зафиксировано мною. Оформление занимает недолго.",
        "Ведомственная принадлежность объекта разглашению не подлежит.",
        "Особое указание не поступало. Особое указание не поступало.",
        "Я вправе применить меры, предусмотренные регламентом 4.2. Пока они не применены.",
        "Смена принята. Продолжайте наблюдение до особого указания.",
    ]

    def __init__(self, cfg: dict | None = None):
        self.model = "офлайн-заглушка"

    @property
    def name(self) -> str:
        return "офлайн-заглушка (модель не вызывается)"

    def chat(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
        last = messages[-1]["content"] if messages else ""
        if "?" in last:
            reply = random.choice(self.ANSWERS[:5])
        else:
            reply = random.choice(self.ANSWERS)
        return reply, {"офлайн": True}


def make_client(cfg: dict, offline: bool = False):
    """Возвращает клиент модели либо заглушку."""
    if offline:
        return OfflineClient(cfg)
    return DeepSeekClient(cfg)
