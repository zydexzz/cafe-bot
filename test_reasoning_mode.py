"""Офлайн-проверка выбора режима рассуждения: решает код, а не модель.

    .venv\\Scripts\\python.exe test_reasoning_mode.py

Бронь и расчёт → reasoning effort "high" и шаг <размышление> в system prompt;
остальное → effort "none" и system prompt без шага. Запросов к OpenRouter нет:
вместо модели — FakeLLM из test_booking.py, который запоминает параметры запроса.
"""

import asyncio
import logging
import traceback

from cafe import choose_reasoning
from test_booking import TOMORROW, js, make, say

PLAIN_ANSWER = "Латте: S (250 мл) — 1 150 ₸, L (350 мл) — 1 350 ₸."
THINK_ANSWER = "<размышление>2 × 1 300 = 2 600</размышление><ответ>Итого 6 200 ₸.</ответ>"


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())

    def __enter__(self):
        log = logging.getLogger("cafe")
        self._level = log.level
        log.setLevel(logging.INFO)
        log.addHandler(self)
        return self

    def __exit__(self, *exc):
        log = logging.getLogger("cafe")
        log.removeHandler(self)
        log.setLevel(self._level)


def test_simple_questions_are_none():
    for text in [
        "Сколько стоит латте?",
        "Есть безглютеновый торт?",
        "Во сколько вы открываетесь в субботу и до скольки?",
        "Можно прийти 2 человека и с собакой?",          # число — это люди, а не позиции
        "Латте қанша тұрады?",
    ]:
        mode = choose_reasoning(text, booking=False)
        assert (mode.effort, mode.thinking) == ("none", False), f"{text!r} → {mode}"


def test_calculation_words_are_high():
    for text in [
        "Посчитай, сколько выйдет вечером: 2 капучино L, один из них на овсяном молоке, "
        "раф ванильный S с дополнительным шотом и чизкейк «Нью-Йорк».",
        "Сколько с меня за латте и медовик?",
        "Итого за капучино и круассан?",
        "Латте мен медовик барлығы қанша болады?",
    ]:
        mode = choose_reasoning(text, booking=False)
        assert (mode.effort, mode.reason) == ("high", "расчёт"), f"{text!r} → {mode}"


def test_several_items_with_quantity_are_high():
    for text in ["Хочу 2 латте L и медовик", "три капучино, брауни", "2× американо + чизкейк"]:
        assert choose_reasoning(text, booking=False).effort == "high", text
    # одна позиция с количеством без суммы — простой вопрос о цене
    assert choose_reasoning("2 латте есть?", booking=False).effort == "none"


async def test_plain_chat_sends_none_without_thinking_step():
    a, llm, _ = make(PLAIN_ANSWER)
    r = await say(a, "Сколько стоит латте?")
    system, kw = llm.calls[0][0][0]["content"], llm.calls[0][1]
    assert kw["effort"] == "none" and kw["max_tokens"] == 700, kw
    assert "<размышление>" not in system and "Рассуждение перед ответом" not in system
    assert r.text == PLAIN_ANSWER


async def test_calculation_chat_sends_high_with_thinking_step():
    a, llm, _ = make(THINK_ANSWER)
    with LogCapture() as logs:
        r = await say(a, "Сколько выйдет: 2 капучино L и чизкейк?")
    system, kw = llm.calls[0][0][0]["content"], llm.calls[0][1]
    assert kw["effort"] == "high", kw
    assert "<размышление>" in system and "Рассуждение перед ответом" in system
    assert r.text == "Итого 6 200 ₸.", "гостю — только текст из <ответ>"
    assert "режим рассуждения: high (расчёт)" in logs.lines, logs.lines


async def test_booking_form_sends_high_and_logs_mode():
    # заявка → разбор JSON с high; вопрос посреди брони тоже идёт с high и шагом <размышление>
    a, llm, _ = make(js(date=TOMORROW, time="19:00", guests=2), js(intent="other"),
                     "<размышление>нет данных</размышление><ответ>Парковки у меня не записано.</ответ>")
    with LogCapture() as logs:
        await say(a, "Забронируй столик на завтра в 19:00 на двоих")
        r = await say(a, "А парковка у вас есть?")
    extract_kw, chat_kw = llm.calls[0][1], llm.calls[2][1]
    assert extract_kw["effort"] == "high" and extract_kw["json_mode"], extract_kw
    assert extract_kw["max_tokens"] > 300, "рассуждение не должно съесть JSON"
    assert chat_kw["effort"] == "high", chat_kw
    assert "<размышление>" in llm.calls[2][0][0]["content"]
    assert r.text.startswith("Парковки у меня не записано.")
    assert logs.lines.count("режим рассуждения: high (бронь)") == 2, logs.lines


async def main() -> int:
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            res = fn()
            if asyncio.iscoroutine(res):
                await res
            print(f"[OK  ] {name}")
        except Exception:
            failed += 1
            print(f"[FAIL] {name}")
            traceback.print_exc()
    print(f"\nИтог: {len(tests) - failed}/{len(tests)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
