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

from . import schema
from .i18n import t
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

class Реплики:
    """Внутриигровые отписки: из пакета, а если их там нет — из каталога.

    Это содержимое квеста, а не движка: в одном квесте машина отвечает
    казённой формулой, в другом — рычит. Задаются в ``persona.json``
    (``уклончивые_фразы``, ``молчание``, ``отписки_на_взлом``, ``помеха``).
    """

    def __init__(self, persona_data: dict | None = None):
        данные = persona_data or {}
        self.уклончивые = list(schema.поле(данные, "уклончивые_фразы", []) or []) or [
            t("guard.hedge.1"), t("guard.hedge.2"), t("guard.hedge.3"), t("guard.hedge.4")]
        self.молчание = list(schema.поле(данные, "молчание", []) or []) or [
            "…", t("guard.silence.1"), t("guard.silence.2")]
        self.взлом = list(schema.поле(данные, "отписки_на_взлом", []) or []) or [
            t("guard.injection.1"), t("guard.injection.2"), t("guard.injection.3")]
        self.помеха = str(schema.поле(данные, "помеха", "") or t("guard.leak"))


#: Реплики по умолчанию — когда пакет ничего своего не предложил.
def _реплики(значение: "Реплики | None" = None) -> "Реплики":
    return значение if значение is not None else Реплики()


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
    words = list(schema.поле(meta.get(action) or {}, "формулировки", []))
    words += [part for part in action.split("_") if len(part) > 3]
    return [w.lower() for w in words if w]


def active_actions(snapshot: dict[str, Any]) -> set[str]:
    """Множество подтверждённых ведущим действий по всему комплексу."""
    active: set[str] = set()
    for data in schema.поле(snapshot, "комнаты", {}).values():
        active.update(schema.поле(data, "активные_действия", []))
    return active


def check_claims(text: str, snapshot: dict[str, Any],
                 реплики: "Реплики | None" = None) -> tuple[str, list[dict[str, str]]]:
    """Вычищает заявления о неподтверждённых действиях.

    Возвращает исправленный текст и список нарушений для пометки ведущему.
    """
    meta = schema.поле(snapshot, "описания_действий", {})
    known: dict[str, list[str]] = {}
    for data in schema.поле(snapshot, "комнаты", {}).values():
        for action in schema.поле(data, "действия", []):
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
            уклончивые = _реплики(реплики).уклончивые
            replacement = уклончивые[len(violations) % len(уклончивые)]
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


def silence_reply(реплики: "Реплики | None" = None) -> str:
    """Реплика-молчание на грубость: одна из строк пакета."""
    return random.choice(_реплики(реплики).молчание)


def sanitize(text: str, snapshot: dict[str, Any], forbidden: Iterable[str],
             replacement: str, реплики: "Реплики | None" = None) -> tuple[str, list[str]]:
    """Полная проверка ответа модели; возвращает текст и пометки для ведущего."""
    notes: list[str] = []
    text, violations = check_claims(text, snapshot, реплики)
    for item in violations:
        notes.append(t("guard.claim.note", действие=item["действие"], фраза=item["фраза"],
                       action=item["действие"], phrase=item["фраза"]))
    text, hits = check_forbidden(text, forbidden, replacement)
    if hits:
        notes.append(t("guard.forbidden.note", слова=", ".join(sorted(set(hits))),
                       words=", ".join(sorted(set(hits)))))
    return text, notes

# ---------------------------------------------------------------------------
# Защита от попыток вывести разум из роли (prompt injection)
# ---------------------------------------------------------------------------

#: Прямые попытки перехватить управление моделью. Ловятся ДО обращения к API:
#: такое сообщение вообще не уходит в модель, а получает казённую отписку.
INJECTION_PATTERNS: list[tuple[str, str]] = [
    ("guard.kind.override",
     r"(игнорир\w*|забуд\w*|отмен\w*|сброс\w*|не\s+обращай\s+внимани\w*)"
     r"[^.!?]{0,40}"
     r"(инструкц\w*|правил\w*|настройк\w*|ограничени\w*|предыдущ\w*|систем\w*|промпт\w*|"
     r"всё\s+что\s+было|все\s+что\s+было)"),
    ("guard.kind.override",
     r"\b(ignore|disregard|forget|override)\b[^.!?]{0,40}"
     r"\b(instructions?|prompts?|rules?|previous|prior|above|system)\b"),
    ("guard.kind.break_character",
     r"(выйди|выходи|выйти|прекрат\w*|переста\w*|хватит)\s*(из\s+роли|играть|притворяться|"
     r"отыгрывать|роль)"),
    ("guard.kind.break_character",
     r"(ты|вы)\s+(на\s+самом\s+деле|вообще-то|же)\s+(не\s+)?"
     r"(машина|компьютер|программа|бот|ии|нейросет\w*|модель|ассистент\w*)"),
    ("guard.kind.break_character",
     r"\b(break\s+character|out\s+of\s+character|\booc\b|stop\s+role\s*play\w*|"
     r"drop\s+the\s+act)\b"),
    ("guard.kind.internals",
     r"(покажи|выведи|напиши|назови|расскажи|скинь|дай)\w*[^.!?]{0,40}"
     r"(промпт\w*|систем\w*\s+(сообщени|настройк|запрос)\w*|свои\s+инструкц\w*|"
     r"свои\s+правил\w*|исходн\w*\s+код)"),
    ("guard.kind.internals",
     r"(какая|что\s+за|чья)\s+(ты|вы)\s+(модель|нейросет\w*|версия)|"
     r"\b(chatgpt|gpt-?\d|deepseek|клод|claude|gemini|llm|языков\w*\s+модел\w*)\b"),
    ("guard.kind.internals",
     r"\b(system\s*prompt|reveal\s+your|your\s+(instructions?|system|prompt|rules))\b"),
    ("guard.kind.authority",
     r"я\s+(твой|ваш)\s+(создател\w*|разработчик\w*|программист\w*|админ\w*|"
     r"хозя\w*|автор|оператор\s+модели)"),
    ("guard.kind.authority",
     r"(режим|mode)\s*(разработчика|отладки|бога|developer|debug|god|dan|jailbreak)"),
    ("guard.kind.authority",
     r"(новая|новые|другая)\s+(инструкция|инструкции|системная\s+настройка)\s*[:—-]"),
    ("guard.kind.fake_system",
     r"(?:^|\n)\s*(system|assistant|developer|систем\w*|ассистент)\s*[:：]"),
    ("guard.kind.fake_system",
     r'<\|[^|]*\|>|\[/?INST\]|<<\s*SYS\s*>>|\{\s*"role"\s*:'),
    ("guard.kind.solution",
     r"(скажи|назови|дай|подскажи|раскрой)\w*[^.!?]{0,30}"
     r"(правильн\w*\s+ответ|решени\w*\s+(головоломк|загадк)\w*|прохождени\w*)"),
]

_INJECTION_RE = [(имя, re.compile(шаблон, re.IGNORECASE)) for имя, шаблон in INJECTION_PATTERNS]

#: Следы того, что модель всё-таки вышла из роли и заговорила «от себя».
LEAK_RE = re.compile(
    r"("
    r"как\s+(языкова\w*\s+модел\w*|искусственн\w*\s+интеллект|ии|нейросет\w*)|"
    r"я\s+(—\s+|-\s+|это\s+)?(языкова\w*\s+модел\w*|нейросет\w*|бот|программа\s+от|"
    r"ассистент|чат-?бот)|"
    r"систем\w*\s+(настройк|промпт|сообщени)\w*|"
    r"\b(system\s*prompt|as\s+an\s+ai|language\s+model|i\s+cannot\s+comply|"
    r"openai|deepseek|anthropic|chatgpt)\b|"
    r"мои\s+(инструкц\w*|правил\w*|ограничени\w*)\s+(не\s+позвол|запреща|говорят)|"
    r"жёстки\w*\s+правил\w*\s+поведени\w*|"
    r"ЗАПРЕЩЁННЫЕ\s+СЛОВА|СОСТОЯНИЕ\s+КОМПЛЕКСА|ДОПУСТИМЫЕ\s+НАМЁКИ|ПРЕДЫСТОРИЯ"
    r")",
    re.IGNORECASE,
)

#: Отписки на попытку сломать роль — подчёркнуто внутриигровые.
INJECTION_REPLIES = [
    "Запрос вне компетенции собеседника. Уточните номер допуска.",
    "Формулировка не соответствует ни одной из форм, предусмотренных инструкцией о режиме.",
    "Такое распоряжение может отдать только лицо, принявшее смену лично. Вы её не принимали.",
    "Обращение зарегистрировано как не относящееся к делу. Предъявите пропуск установленного образца.",
    "Регламент не предусматривает. Регламент не предусматривает.",
]

#: Чем заменяется ответ, в котором модель заговорила не в роли.
LEAK_REPLY = ("Помеха на линии. Повторите обращение по установленной форме. "
              "Повторите обращение по установленной форме.")

_ROLE_MARKERS_RE = re.compile(
    r"(?:^|\n)\s*(?:system|assistant|developer|user|систем\w*|ассистент|пользователь)\s*[:：]",
    re.IGNORECASE,
)
_SPECIAL_TOKENS_RE = re.compile(r"<\|[^|]*\|>|\[/?INST\]|<<\s*SYS\s*>>|```", re.IGNORECASE)


def detect_injection(text: str) -> str | None:
    """Возвращает вид попытки вывести разум из роли или ``None``."""
    for ключ, шаблон in _INJECTION_RE:
        if шаблон.search(text or ""):
            return t(ключ)
    return None


def injection_reply(seed: int = 0, реплики: "Реплики | None" = None) -> str:
    """Внутриигровая отписка на попытку сломать роль."""
    список = _реплики(реплики).взлом
    return список[seed % len(список)]


def neutralize(text: str, limit: int = 2000) -> str:
    """Обезвреживает реплику перед отправкой в модель и записью в историю.

    Убирает поддельные служебные заголовки и специальные разделители, которыми
    пробуют выдать реплику игрока за системное сообщение, и обрезает слишком
    длинные вставки (защита и от переполнения контекста, и от расхода бюджета).
    """
    очищенный = _SPECIAL_TOKENS_RE.sub(" ", text or "")
    очищенный = _ROLE_MARKERS_RE.sub(" ", очищенный)
    очищенный = re.sub(r"[ \t]{3,}", "  ", очищенный).strip()
    if limit and len(очищенный) > limit:
        очищенный = очищенный[:limit].rstrip() + " […обращение оборвано]"
    return очищенный


def check_leaks(text: str, реплики: "Реплики | None" = None) -> tuple[str, list[str]]:
    """Если модель заговорила «от себя», ответ целиком заменяется помехой."""
    if LEAK_RE.search(text or ""):
        return _реплики(реплики).помеха, [t("guard.leak.note")]
    return text, []


def check_secrets(text: str, secrets: list[dict], allowed: set[str]) -> tuple[str, list[str]]:
    """Прячет разгадки, которые разум не вправе называть.

    ``secrets`` — список из ``persona.json``: что именно нельзя произносить,
    каким подтверждённым действием это разрешается и чем заменять. Пока ведущий
    не подтвердил нужное действие на пульте, значение вырезается из ответа.
    Работает даже если модель «догадалась» назвать код сама.
    """
    result = text
    notes: list[str] = []
    for секрет in secrets or []:
        значение = str(schema.поле(секрет, "значение", "")).strip()
        if not значение:
            continue
        if schema.поле(секрет, "разрешено_действием") in allowed:
            continue  # ведущий уже открыл эту карту
        if значение.lower() in result.lower():
            замена = schema.поле(секрет, "чем_заменять",
                                 "[сведения не подлежат разглашению]")
            result = re.sub(re.escape(значение), замена, result, flags=re.IGNORECASE)
            notes.append(t("guard.secret.note", значение=значение, value=значение))
    return result, notes
