"""Офлайн-проверка формы брони: вместо OpenRouter — фейковая модель с заготовленными ответами.

    .venv\\Scripts\\python.exe test_booking.py

Запросов к OpenRouter нет, лимит не тратится. Качество самого промпта разбора
здесь не проверяется — для этого test_scenarios.py.
"""

import asyncio
import csv
import json
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

from cafe import QUESTIONS, TEXTS, TZ, CafeAssistant, LLMUnavailable, parse_extraction

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=TZ)  # суббота
TOMORROW = "2026-11-22"                          # воскресенье, бронь 09:00–22:00


def js(**kw) -> str:
    d = {"intent": "booking", "date": None, "time": None, "guests": None, "name": None, "phone": None}
    d.update(kw)
    d["missing"] = [f for f in ("date", "time", "guests", "name", "phone") if d[f] is None]
    return json.dumps(d, ensure_ascii=False)


FULL = js(date=TOMORROW, time="19:00", guests=2, name="Айдос", phone="+77019431010")


class FakeLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, messages, **kw):
        self.calls.append((messages, kw))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r, "fake-model"

    async def close(self):
        pass


def make(*responses):
    llm = FakeLLM(*responses)
    csv_path = Path(tempfile.mkdtemp()) / "bookings.csv"
    return CafeAssistant(llm, bookings_path=csv_path), llm, csv_path


async def say(a, text, chat=1):
    return await a.chat(chat, text, username="test", now=NOW)


def rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ---------- тесты ----------

def test_parse_json_with_noise():
    d = parse_extraction("Вот заявка:\n```json\n" + FULL + "\n```\nГотово!")
    assert d["date"] == TOMORROW and d["guests"] == 2 and d["missing"] == []


def test_parse_rejects_bad_json():
    for raw in ["Не понял вопрос", '{"intent": "booking"}', "{битый json"]:
        try:
            parse_extraction(raw)
        except ValueError:
            continue
        raise AssertionError(f"разобрал мусор: {raw}")


def test_parse_drops_invented_values():
    d = parse_extraction(json.dumps({"intent": "booking", "date": "завтра", "time": "7 вечера", "guests": "двое",
                                     "name": "", "phone": None, "missing": []}, ensure_ascii=False))
    assert d["missing"] == ["date", "time", "guests", "name", "phone"], d


def test_booking_trigger():
    from cafe import BOOKING_TRIGGER_RE as R
    yes = ["завтра в 19:00, 2 человека, Айдос, +7 701 943 10 10", "Хочу забронировать", "есть свободный столик?",
           "87010000000", "на 18.30 нас будет трое гостей", "Ертеңге үстел керек"]
    no = ["Сколько стоит латте?", "Капучино L 1 300 или 1 100?", "Во сколько закрываетесь? До 22:00?",
          "Есть Wi-Fi?", "Напиши код на Python"]
    assert all(R.search(s) for s in yes), [s for s in yes if not R.search(s)]
    assert not any(R.search(s) for s in no), [s for s in no if R.search(s)]


async def test_button_starts_form_without_model():
    a, llm, _ = make()
    r = a.start_booking(1, "Забронировать столик")
    assert QUESTIONS["date"][0] in r.text and not llm.calls


async def test_full_request_then_yes_saves_csv():
    a, llm, path = make(FULL)
    r = await say(a, "завтра в 19:00, 2 человека, Айдос, +7 701 943 10 10")
    assert r.confirm_id and "Подтверждаешь?" in r.text and "воскресенье, 22 ноября, 19:00" in r.text, r.text
    assert not path.exists()
    system, kw = llm.calls[0][0][0]["content"], llm.calls[0][1]
    assert kw.get("json_mode") and kw.get("temperature") == 0
    assert "2026-11-21, суббота" in system and "{{" not in system
    r = await say(a, "Да, всё верно")
    assert r.saved and len(llm.calls) == 1, "на «да» модель не нужна"
    row = rows(path)[0]
    assert (row["name"], row["date"], row["time"], row["guests"], row["phone"]) == \
        ("Айдос", TOMORROW, "19:00", "2", "+77019431010"), row


async def test_missing_fields_one_question_each():
    a, llm, path = make(js(date=TOMORROW, time="19:00", guests=4),
                        js(name="Айдос"),
                        js(phone="77010000000"))
    r = await say(a, "Хочу столик завтра в 19:00 на четверых")
    assert r.text == QUESTIONS["name"][0], r.text
    r = await say(a, "Айдос")
    assert r.text == QUESTIONS["phone"][0], r.text
    assert "вопрос про поле name" in llm.calls[1][0][0]["content"], "код не передал модели, на что отвечает гость"
    r = await say(a, "77010000000")
    assert r.confirm_id and "+7 701 000 00 00" in r.text and "Гостей: 4" in r.text, r.text


async def test_retry_once_then_success():
    a, llm, _ = make("Конечно! Сейчас оформлю.", FULL)
    r = await say(a, "забронируй на завтра в 19:00 двоих, Айдос +77019431010")
    assert r.confirm_id and len(llm.calls) == 2


async def test_retry_fails_twice_polite_message():
    a, llm, _ = make("не json", "{сломано")
    r = await say(a, "забронируй столик на завтра")
    assert r.text == TEXTS["parse_failed"][0] and len(llm.calls) == 2
    assert a.session(1).form is not None, "форма должна остаться открытой"


async def test_past_date_rejected():
    a, _, _ = make(js(date="2026-11-20", time="19:00", guests=2, name="Айдос", phone="77019431010"))
    r = await say(a, "столик на вчера")
    assert "эта дата уже прошла" in r.text and QUESTIONS["date"][0] in r.text, r.text
    assert a.session(1).form.data["date"] is None


async def test_time_outside_hours_rejected():
    a, _, _ = make(js(date=TOMORROW, time="23:30", guests=2, name="Айдос", phone="77019431010"))
    r = await say(a, "столик завтра в 23:30")
    assert "с 09:00 до 22:00" in r.text and QUESTIONS["time"][0] in r.text, r.text


async def test_time_already_passed_today():
    a, _, _ = make(js(date="2026-11-21", time="10:00", guests=2, name="Айдос", phone="77019431010"))
    r = await say(a, "столик сегодня в 10:00")
    assert "время уже прошло" in r.text, r.text


async def test_phone_must_have_11_digits():
    a, _, _ = make(js(date=TOMORROW, time="19:00", guests=2, name="Айдос", phone="7010000000"))
    r = await say(a, "бронь завтра 19:00, двое, Айдос, 701 000 00 00")
    assert "11 цифр" in r.text and r.confirm_id is None, r.text
    assert a.session(1).form.asking == "phone"


async def test_big_group_goes_to_phone():
    a, _, _ = make(js(date=TOMORROW, time="18:00", guests=12, name="Ерлан", phone="77051112233"))
    r = await say(a, "столик на 12 человек завтра в 18:00")
    assert "50-60-70" in r.text and r.confirm_id is None and a.session(1).form is None, r.text


async def test_no_then_change():
    a, _, path = make(FULL, js(time="20:00"))
    await say(a, "столик завтра 19:00 двое Айдос +77019431010")
    r = await say(a, "нет")
    assert r.text == TEXTS["edit"][0]
    r = await say(a, "на 20:00")
    assert r.confirm_id and "20:00" in r.text and not path.exists(), r.text


async def test_correction_instead_of_yes():
    a, _, path = make(FULL, js(time="20:00"))
    await say(a, "столик завтра 19:00 двое Айдос +77019431010")
    r = await say(a, "нет, давай на 20:00")
    assert r.confirm_id and "20:00" in r.text and not path.exists(), r.text


async def test_trigger_word_but_not_a_booking():
    a, llm, _ = make(js(intent="other"), "Отмена и перенос — только по телефону +7 7212 50-60-70.")
    r = await say(a, "как отменить бронь?")
    assert "по телефону" in r.text and a.session(1).form is None
    assert "json_mode" not in llm.calls[1][1], "второй запрос должен уйти в обычный чат"


async def test_question_in_the_middle_of_booking():
    a, _, _ = make(js(intent="other"), "Латте S — 1 150 ₸, L — 1 350 ₸.")
    a.start_booking(1, "Забронировать столик")
    r = await say(a, "а сколько стоит латте?")
    assert "1 150 ₸" in r.text and r.text.endswith(QUESTIONS["date"][0]), r.text


async def test_cancel():
    a, llm, _ = make()
    a.start_booking(1, "Забронировать столик")
    r = await say(a, "отмена")
    assert r.text == TEXTS["cancel"][0] and a.session(1).form is None and not llm.calls


async def test_buttons_confirm_and_stale():
    a, _, path = make(FULL)
    r = await say(a, "столик завтра 19:00 двое Айдос +77019431010")
    assert a.confirm(1, r.confirm_id + 1, now=NOW) is None, "чужая кнопка не должна сработать"
    done = a.confirm(1, r.confirm_id, username="test", now=NOW)
    assert done and done.saved and len(rows(path)) == 1
    assert a.confirm(1, r.confirm_id, now=NOW) is None, "повторное нажатие не должно сработать"


async def test_kazakh_questions():
    a, _, _ = make(js(date=TOMORROW, time="19:00"))
    r = await say(a, "Ертеңге сағат 19:00-ге үстел брондағым келеді")
    assert r.text == QUESTIONS["guests"][1], r.text


async def test_formula_in_name_is_cleaned():
    a, _, path = make(js(date=TOMORROW, time="19:00", guests=2, name='=HYPERLINK("https://example.com";"Айдос")',
                         phone="77019431010"))
    r = await say(a, "столик")
    await say(a, "да")
    assert not rows(path)[0]["name"].startswith("="), rows(path)[0]["name"]


async def test_model_down_keeps_form_data():
    a, _, _ = make(js(date=TOMORROW, time="19:00", guests=2, name="Айдос"), LLMUnavailable("лимит"))
    await say(a, "столик завтра 19:00 двое Айдос")
    r = await say(a, "77010000000")
    assert r.text == TEXTS["unavailable"][0]
    assert a.session(1).form.data["name"] == "Айдос", "собранные данные не должны теряться"


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
