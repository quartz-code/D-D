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
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from . import config


class DeepSeekError(Exception):
    """Ошибка обращения к API.

    Атрибут ``временная`` говорит, имеет ли смысл повторить запрос.
    """

    временная = False


class DeepSeekClient:
    """Минимальный клиент /chat/completions."""

    def __init__(self, cfg: dict):
        section = cfg.get("deepseek", {})
        self.base_url = str(section.get("base_url", "https://api.deepseek.com")).rstrip("/")
        self.model = section.get("model", "deepseek-chat")
        self.temperature = float(section.get("temperature", 1.0))
        self.max_tokens = int(section.get("max_tokens", 700))
        self.timeout = float(section.get("timeout_sec", 60))
        self.retries = max(0, int(section.get("retries", 2)))
        self.retry_pause = float(section.get("retry_pause_sec", 2.0))
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

    #: Коды, при которых повтор осмыслен: перегрузка и сбои на стороне сервиса.
    ПОВТОРЯЕМЫЕ_КОДЫ = (429, 500, 502, 503, 504)

    def chat(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
        """Отправляет переписку в модель, повторяя при временных сбоях.

        Одна помеха в сети не должна стоить игрокам реплики: запрос
        повторяется ``retries`` раз с нарастающей паузой. Ошибки, которые
        повтор не исправит (неверный ключ, кончившийся баланс), возвращаются
        сразу.
        """
        последняя: DeepSeekError | None = None
        for попытка in range(self.retries + 1):
            try:
                return self._chat_once(messages)
            except DeepSeekError as ошибка:
                последняя = ошибка
                if not getattr(ошибка, "временная", False) or попытка >= self.retries:
                    raise
                time.sleep(self.retry_pause * (2 ** попытка))
        raise последняя  # pragma: no cover — цикл всегда возвращает или бросает

    def chat_stream(self, messages: list[dict[str, str]],
                    кусок: Callable[[str], None]) -> tuple[str, dict[str, Any]]:
        """Получает ответ потоком, отдавая куски по мере поступления.

        ``кусок`` вызывается на каждую порцию текста. Возвращает собранный
        ответ целиком и статистику — как обычный :meth:`chat`.

        Повторы здесь не делаются: часть ответа уже могла быть напечатана, и
        второй проход выглядел бы как оговорка машины.
        """
        запрос = self._запрос(messages, поток=True)
        собранное: list[str] = []
        расход: dict[str, Any] = {}
        try:
            with urllib.request.urlopen(запрос, timeout=self.timeout,
                                        context=ssl.create_default_context()) as поток:
                for сырая in поток:
                    строка = сырая.decode("utf-8", "replace").strip()
                    if not строка or not строка.startswith("data:"):
                        continue
                    данные = строка[5:].strip()
                    if данные == "[DONE]":
                        break
                    try:
                        порция = json.loads(данные)
                    except json.JSONDecodeError:
                        continue
                    if порция.get("usage"):
                        расход = порция["usage"]
                    for выбор in порция.get("choices", []):
                        текст = (выбор.get("delta") or {}).get("content") or ""
                        if текст:
                            собранное.append(текст)
                            кусок(текст)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            ошибка = DeepSeekError(f"HTTP {exc.code}: {detail}")
            ошибка.временная = exc.code in self.ПОВТОРЯЕМЫЕ_КОДЫ
            raise ошибка from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            ошибка = DeepSeekError(f"поток прерван: {exc}")
            ошибка.временная = True
            raise ошибка from exc

        ответ = "".join(собранное).strip()
        if not ответ:
            raise DeepSeekError("модель прислала пустой поток")
        return ответ, расход

    def _запрос(self, messages: list[dict[str, str]], поток: bool = False):
        """Готовит HTTP-запрос к /chat/completions."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": поток,
        }
        return urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.key}",
                "Accept": "text/event-stream" if поток else "application/json",
            },
            method="POST",
        )

    def _chat_once(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
        """Одно обращение к API без повторов."""
        request = self._запрос(messages)
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
            ошибка = DeepSeekError(f"HTTP {exc.code}{hint}: {detail}")
            ошибка.временная = exc.code in self.ПОВТОРЯЕМЫЕ_КОДЫ
            raise ошибка from exc
        except urllib.error.URLError as exc:
            ошибка = DeepSeekError(f"нет связи с {self.base_url}: {exc.reason}")
            ошибка.временная = True
            raise ошибка from exc
        except TimeoutError as exc:
            ошибка = DeepSeekError(f"превышено время ожидания ({self.timeout} с)")
            ошибка.временная = True
            raise ошибка from exc
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

    def chat_stream(self, messages: list[dict[str, str]],
                    кусок) -> tuple[str, dict[str, Any]]:
        """Заглушка тоже умеет «поток» — отдаёт ответ по словам."""
        ответ, расход = self.chat(messages)
        for слово in ответ.split(" "):
            кусок(слово + " ")
        return ответ, расход

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
