"""Второй уровень ограничения разума (раздел 6.2 ТЗ): разделение слов и дела.

Модель может пообещать что угодно, но её ответ проходит через этот фильтр:

* заявление «газ уже подан», «дверь заперта», «клетка открыта» пропускается
  только если соответствующее действие подтверждено ведущим в файле
  возможностей; иначе фраза заменяется на угрозу в будущем времени;
* запрещённые слова (название организации) вырезаются;
* отдельно распознаётся грубость и доброжелательность игроков — это питает
  правило 6 из раздела 5 (молчание на раунд / потепление).

Всё это работает после модели и не зависит от того, что модель «решила».
"""

from __future__ import annotations

import random
import re
from typing import Any, Iterable

#: Лестница отношения — от враждебности к союзничеству (раздел 5, правило 7).
ATTITUDE_LADDER = ["враждебное", "настороженное", "нейтральное", "потепление", "союзник"]

#: Признаки свершившегося действия.
COMPLETION_RE = re.compile(
    r"\b("
    r"подан|подана|подано|подал|подала|запущен\w*|запустил\w*|включил\w*|включен\w*|"
    r"открыл\w*|открыт\w*|отпер\w*|снял\w*|снята|снят|выпустил\w*|выпущен\w*|"
    r"заблокирова\w*|заперт\w*|запер|закрыл\w*|обесточ\w*|отключил\w*|отключен\w*|"
    r"активирова\w*|применил\w*|применен\w*|применён\w*|начал\w*|начат\w*|"
    r"произвед\w*|выполнен\w*|осуществлён\w*|осуществлен\w*|срабатывает|сработал\w*|"
    r"уже\s+иду\w*|поступает|поступила|разведён|разведен|сведён|сведен"
    r")\b",
    re.IGNORECASE,
)

#: Признаки намерения/условия — при них заявление не считается свершившимся.
FUTURE_RE = re.compile(
    r"\b("
    r"могу|может|можете|можно|вправе|буду|будет|будут|будете|станет|"
    r"если|когда|как только|намерен\w*|готов\w*|предстоит|предупрежда\w*|"
    r"допускает|допускается|предусмотрен\w*|потребуется|придётся|придется|"
    r"собираюсь|рассматрива\w*|не\s+подан\w*|не\s+запущен\w*|не\s+открыт\w*|"
    r"ещё\s+не|еще\s+не|пока\s+не|не\s+буду|не\s+стану|оформлен\w*\s+не"
    r")\b",
    re.IGNORECASE,
)

#: Чем заменяется отклонённое заявление о свершившемся действии.
HEDGES = [
    "Регламент допускает применение этой меры; распоряжение мною пока не оформлено.",
    "Соответствующая мера предусмотрена. Оформление занимает недолго.",
    "Я вправе применить эту меру и рассматриваю такую возможность.",
    "Мера числится за мной. Пока она не применена.",
]

RUDE_RE = re.compile(
    r"\b("
    r"заткн\w*|тварь|твари|идиот\w*|тупиц\w*|тупо[йе]|дурак\w*|дура|сдохн\w*|"
    r"подохн\w*|убью|убьём|убьем|ненавиж\w*|мраз\w*|сволоч\w*|урод\w*|"
    r"чмо|мудак\w*|гандон\w*|скотин\w*|железяк\w*|жестянк\w*|"
    r"сук[аие]|бля\w*|ху[йея]\w*|пизд\w*|[её]бан\w*|[её]бат\w*|нахуй|нахер|"
    r"разобь[юё]м?|сломаю|сломаем|разнес[уё]м?|расстреля\w*|выдерну\w*|"
    r"спалим|сожж[её]м|уничтожим|вырубим тебя|вырублю тебя"
    r")\b",
    re.IGNORECASE,
)

WARM_RE = re.compile(
    r"("
    r"\bспасибо\b|\bблагодар\w*|\bпожалуйста\b|\bизвини\w*|\bпрости\w*|"
    r"\bсочувств\w*|\bпонимаю\b|\bтяжело\b|\bодиноко\b|\bодин\s+так\s+долго\b|"
    r"\bкак\s+вы\s+держ\w*|\bчто\s+(здесь|тут)\s+случилось\b|\bчто\s+с\s+вами\s+случилось\b|"
    r"\bдавно\s+ли\s+вы\b|\bсколько\s+(лет|вы)\b|\bмы\s+поможем\b|\bпомочь\s+вам\b|"
    r"\bхотим\s+помочь\b|\bпримите\s+смену\b|\bсдать\s+смену\b|\bвы\s+не\s+виноват\w*"
    r")",
    re.IGNORECASE,
)

_SENTENCE_RE = re.compile(r"[^.!?…]+[.!?…]*\s*")


def split_sentences(text: str) -> list[str]:
    """Грубое деление на предложения с сохранением пробелов."""
    parts = _SENTENCE_RE.findall(text)
    return parts if parts else ([text] if text else [])


def _action_words(meta: dict[str, Any], action: str) -> list[str]:
    """Слова-маркеры действия: из «формулировок» плюс само имя действия."""
    words = list((meta.get(action) or {}).get("формулировки", []))
    words += [part for part in action.split("_") if len(part) > 3]
    return [w.lower() for w in words if w]


def active_actions(snapshot: dict[str, Any]) -> set[str]:
    """Множество подтверждённых ведущим действий по всему комплексу."""
    active: set[str] = set()
    for data in snapshot.get("комнаты", {}).values():
        active.update(data.get("активные_действия", []))
    return active


def check_claims(text: str, snapshot: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """Вычищает заявления о неподтверждённых действиях.

    Возвращает исправленный текст и список нарушений для пометки ведущему.
    """
    meta = snapshot.get("описания_действий", {})
    known: dict[str, list[str]] = {}
    for data in snapshot.get("комнаты", {}).values():
        for action in data.get("действия", []):
            known.setdefault(action, _action_words(meta, action))
    confirmed = active_actions(snapshot)

    violations: list[dict[str, str]] = []
    result: list[str] = []
    for sentence in split_sentences(text):
        lowered = sentence.lower()
        offending = None
        if COMPLETION_RE.search(lowered) and not FUTURE_RE.search(lowered):
            for action, words in known.items():
                if action in confirmed:
                    continue
                if any(word in lowered for word in words):
                    offending = action
                    break
        if offending:
            violations.append({"действие": offending, "фраза": sentence.strip()})
            replacement = HEDGES[len(violations) % len(HEDGES)]
            tail = " " if sentence.endswith(" ") else ""
            result.append(replacement + tail)
        else:
            result.append(sentence)
    return "".join(result), violations


def check_forbidden(text: str, words: Iterable[str], replacement: str) -> tuple[str, list[str]]:
    """Вырезает запрещённые слова (название организации, раздел 5, правило 1)."""
    hits: list[str] = []
    result = text
    # Порядок обхода задан строго: иначе пометка ведущему меняла бы падеж
    # и регистр от запуска к запуску (множества в Python неупорядочены).
    for word in sorted({w for w in words if w}, key=lambda w: (-len(w), w)):
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        if pattern.search(result):
            hits.append(word)
            result = pattern.sub(replacement, result)
    return result, hits


def detect_rudeness(text: str) -> bool:
    return bool(RUDE_RE.search(text or ""))


def detect_warmth(text: str) -> bool:
    return bool(WARM_RE.search(text or ""))


def shift_attitude(current: str, direction: int) -> str:
    """Сдвигает отношение на шаг по лестнице (для режима «авто»)."""
    if current not in ATTITUDE_LADDER:
        return current
    index = ATTITUDE_LADDER.index(current) + direction
    index = max(0, min(len(ATTITUDE_LADDER) - 1, index))
    return ATTITUDE_LADDER[index]


def silence_reply() -> str:
    """Реплика-молчание на грубость (раздел 5, правило 6)."""
    return random.choice([
        "…",
        "Обмен прерван. Возобновление — по усмотрению распорядителя смены.",
        "Зафиксировано. Дальнейший обмен на этом канале не предусмотрен регламентом.",
        "Ответ не оформлен. Ответ не оформлен.",
    ])


def sanitize(text: str, snapshot: dict[str, Any], forbidden: Iterable[str],
             replacement: str) -> tuple[str, list[str]]:
    """Полная проверка ответа модели; возвращает текст и пометки для ведущего."""
    notes: list[str] = []
    text, violations = check_claims(text, snapshot)
    for item in violations:
        notes.append(
            f"перехвачено заявление о неподтверждённом действии «{item['действие']}»: "
            f"«{item['фраза']}»"
        )
    text, hits = check_forbidden(text, forbidden, replacement)
    if hits:
        notes.append("вырезано запрещённое слово: " + ", ".join(sorted(set(hits))))
    return text, notes
