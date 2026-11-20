"""Логика бота кофейни qaz.su без привязки к Telegram.

Здесь: загрузка system prompt и меню, запросы к OpenRouter с запасными моделями,
память диалога, разбор и проверка брони, запись в bookings.csv.
"""

from __future__ import annotations

import asyncio
import csv
import html
import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

log = logging.getLogger("cafe")

BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "system_prompt.md"
MENU_PATH = BASE_DIR / "menu.md"
BOOKINGS_PATH = BASE_DIR / "bookings.csv"

# В Казахстане с марта 2024 года единое время UTC+5, перехода на летнее время нет.
TZ = timezone(timedelta(hours=5))

# Данные кофейни, которые нужны коду для проверки брони.
# Они должны совпадать с разделом «О кофейне» в system_prompt.md.
CAFE_PHONE = "+7 7212 50-60-70"
OPENING_HOURS = {  # 0 = понедельник … 6 = воскресенье
    0: ("08:00", "22:00"),
    1: ("08:00", "22:00"),
    2: ("08:00", "22:00"),
    3: ("08:00", "22:00"),
    4: ("08:00", "22:00"),
    5: ("09:00", "23:00"),
    6: ("09:00", "23:00"),
}
LAST_BOOKING_BEFORE_CLOSE = timedelta(hours=1)
MAX_GUESTS = 8
BOOKING_DAYS_AHEAD = 14
HOLD_MINUTES = 15

HISTORY_LIMIT = 20  # сколько последних сообщений чата помнит бот

# Бесплатные модели OpenRouter: основная и запасные, по порядку.
# Проверены с ключом проекта 21.11.2026 (python check_models.py).
DEFAULT_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "baidu/ernie-5.5-flash-preview:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "dots-studio/dots-3-note-preview:free",
    "google/gemma-4-31b-it:free",
]
RATE_LIMIT_COOLDOWN = 60  # секунд не трогаем модель после ответа 429

WEEKDAYS_RU = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WEEKDAYS_KZ = ["дүйсенбі", "сейсенбі", "сәрсенбі", "бейсенбі", "жұма", "сенбі", "жексенбі"]
MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
             "августа", "сентября", "октября", "ноября", "декабря"]
MONTHS_KZ = ["қаңтар", "ақпан", "наурыз", "сәуір", "мамыр", "маусым", "шілде",
             "тамыз", "қыркүйек", "қазан", "қараша", "желтоқсан"]
KAZAKH_LETTERS = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")


def detect_lang(text: str) -> str:
    return "kz" if any(ch in KAZAKH_LETTERS for ch in text) else "ru"


def human_date(d: date, lang: str) -> str:
    if lang == "kz":
        return f"{d.day} {MONTHS_KZ[d.month - 1]}, {WEEKDAYS_KZ[d.weekday()]}"
    return f"{WEEKDAYS_RU[d.weekday()]}, {d.day} {MONTHS_RU[d.month - 1]}"


def _hm(s: str) -> timedelta:
    h, m = s.split(":")
    return timedelta(hours=int(h), minutes=int(m))


def booking_window(d: date) -> tuple[str, str]:
    """Первое и последнее время, на которое можно забронировать стол в этот день."""
    open_, close = OPENING_HOURS[d.weekday()]
    last = _hm(close) - LAST_BOOKING_BEFORE_CLOSE
    return open_, f"{last.seconds // 3600:02d}:{last.seconds % 3600 // 60:02d}"


# ---------- system prompt и меню ----------

def load_prompt_template() -> str:
    """system_prompt.md с подставленным menu.md. {{NOW}} заполняется при каждом запросе."""
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    menu = MENU_PATH.read_text(encoding="utf-8").strip()
    for placeholder in ("{{MENU}}", "{{NOW}}"):
        if placeholder not in prompt:
            raise RuntimeError(f"В system_prompt.md нет {placeholder}")
    return prompt.replace("{{MENU}}", menu)


def now_block(now: datetime) -> str:
    lines = [
        f"Сейчас: {human_date(now.date(), 'ru')} {now.year} г., {now:%H:%M} (время Караганды).",
        f"Календарь броней на {BOOKING_DAYS_AHEAD + 1} дней (дата — день недели — время, на которое можно забронировать):",
    ]
    for i in range(BOOKING_DAYS_AHEAD + 1):
        d = now.date() + timedelta(days=i)
        first, last = booking_window(d)
        mark = " (сегодня)" if i == 0 else " (завтра)" if i == 1 else ""
        lines.append(f"• {d.isoformat()} — {WEEKDAYS_RU[d.weekday()]}{mark} — {first}–{last}")
    return "\n".join(lines)


def menu_for_telegram() -> str:
    """menu.md → HTML для Telegram: заголовки жирным, пункты списка с «•»."""
    out = []
    for raw in MENU_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            out += ["", f"<b>{html.escape(line[3:])}</b>"]
        elif line.startswith("# "):
            out.append(f"<b>{html.escape(line[2:])}</b>")
        elif line.startswith("- "):
            out.append("• " + html.escape(line[2:]))
        elif line:
            out.append(html.escape(line))
    return "\n".join(out).strip()


# ---------- OpenRouter ----------

class LLMUnavailable(Exception):
    pass


class LLM:
    def __init__(self, api_key: str, models: list[str]):
        self.models = models
        self.cooldown: dict[str, float] = {}
        self.client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            headers={"Authorization": f"Bearer {api_key}", "X-Title": "qaz.su cafe bot"},
            timeout=httpx.Timeout(45, connect=10),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def complete(self, messages: list[dict]) -> tuple[str, str]:
        """Возвращает (текст, модель). Модели перебираются по порядку при 429, ошибках и пустом ответе."""
        now = time.monotonic()
        ready = [m for m in self.models if self.cooldown.get(m, 0) <= now]
        for model in ready or self.models:
            body = {
                "model": model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 700,
                "reasoning": {"enabled": False, "exclude": True},
            }
            started = time.monotonic()
            try:
                r = await self.client.post("/chat/completions", json=body)
            except httpx.HTTPError as e:
                log.warning("%s: %s", model, type(e).__name__)
                continue
            if r.status_code == 429:
                self.cooldown[model] = time.monotonic() + RATE_LIMIT_COOLDOWN
                log.warning("%s: 429, переключаюсь на запасную модель", model)
                continue
            if r.status_code in (401, 403):
                raise LLMUnavailable(f"OpenRouter отклонил ключ: HTTP {r.status_code}")
            if r.status_code != 200:
                log.warning("%s: HTTP %s", model, r.status_code)
                continue
            data = r.json()
            if data.get("error"):  # OpenRouter иногда отдаёт ошибку провайдера с кодом 200
                code = data["error"].get("code")
                if code == 429:
                    self.cooldown[model] = time.monotonic() + RATE_LIMIT_COOLDOWN
                log.warning("%s: ошибка провайдера %s", model, code)
                continue
            text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if not text.strip():
                log.warning("%s: пустой ответ", model)
                continue
            log.info("ответила %s за %.1f с", model, time.monotonic() - started)
            return text, model
        raise LLMUnavailable("ни одна модель не ответила")


# ---------- бронь ----------

DRAFT_RE = re.compile(r"<booking_draft>\s*(\{.*?\})\s*(?:</booking_draft>)?", re.S)
CONFIRMED_RE = re.compile(r"<booking_confirmed>\s*(\{.*?\})\s*(?:</booking_confirmed>)?", re.S)
LEFTOVER_RE = re.compile(r"</?booking_(?:draft|confirmed)>|```(?:json)?\s*```|```(?:json)?\s*$", re.S)


@dataclass(frozen=True)
class Booking:
    name: str
    day: date
    time: str  # ЧЧ:ММ
    guests: int
    phone: str  # + и цифры


class BookingError(Exception):
    def __init__(self, code: str, **kw):
        super().__init__(code)
        self.code = code
        self.kw = kw


BOOKING_ERRORS = {
    "bad": ("не получилось разобрать данные брони",
            "брондау деректерін түсіне алмадым"),
    "name": ("не хватает имени", "есіміңіз жетіспейді"),
    "past": ("это время уже прошло", "бұл уақыт өтіп кетті"),
    "too_far": (f"бронь принимаем не дальше чем на {BOOKING_DAYS_AHEAD} дней вперёд",
                f"брондауды {BOOKING_DAYS_AHEAD} күннен артық алдын ала қабылдамаймыз"),
    "hours": ("в этот день столик можно забронировать с {first} до {last}",
              "бұл күні үстелді {first} мен {last} аралығында брондауға болады"),
    "guests": (f"через бота бронируем столик на 1–{MAX_GUESTS} гостей, для большой компании позвоните {CAFE_PHONE}",
               f"бот арқылы 1–{MAX_GUESTS} адамға брондаймыз, үлкен компания үшін {CAFE_PHONE} нөміріне қоңырау шалыңыз"),
    "phone": ("номер телефона неполный", "телефон нөмірі толық емес"),
}


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    if len(digits) == 10 and digits[0] == "7":
        digits = "7" + digits
    return "+" + digits


def parse_booking(raw_json: str) -> Booking:
    try:
        d = json.loads(raw_json)
        name = str(d["name"]).strip()
        day = date.fromisoformat(str(d["date"]).strip())
        t = datetime.strptime(str(d["time"]).strip(), "%H:%M").strftime("%H:%M")
        guests = int(d["guests"])
        phone = normalize_phone(d["phone"])
    except (ValueError, KeyError, TypeError) as e:
        raise BookingError("bad") from e
    return Booking(name=name, day=day, time=t, guests=guests, phone=phone)


def validate_booking(b: Booking, now: datetime) -> None:
    if not b.name:
        raise BookingError("name")
    if not 1 <= b.guests <= MAX_GUESTS:
        raise BookingError("guests")
    digits = b.phone[1:]
    if not (digits.isdigit() and 10 <= len(digits) <= 15) or (digits.startswith("7") and len(digits) != 11):
        raise BookingError("phone")
    start = datetime.combine(b.day, datetime.strptime(b.time, "%H:%M").time(), TZ)
    if start <= now:
        raise BookingError("past")
    if b.day > now.date() + timedelta(days=BOOKING_DAYS_AHEAD):
        raise BookingError("too_far")
    first, last = booking_window(b.day)
    if not first <= b.time <= last:
        raise BookingError("hours", first=first, last=last)


ERROR_FOLLOW_UP = {  # что спросить после ошибки
    "bad": ("Давайте уточним данные ещё раз: имя, дата и время, число гостей, телефон.",
            "Деректерді қайта нақтылайық: есім, күні мен уақыты, қонақ саны, телефон."),
    "name": ("Как вас зовут?", "Есіміңіз кім?"),
    "phone": ("Напишите, пожалуйста, номер полностью, например +7 701 123 45 67.",
              "Нөміріңізді толық жазыңыз, мысалы +7 701 123 45 67."),
    "guests": ("", ""),
}


def error_text(err: BookingError, lang: str) -> str:
    i = 1 if lang == "kz" else 0
    reason = BOOKING_ERRORS[err.code][i].format(**err.kw)
    default = ("Давайте подберём другое время или дату?", "Басқа уақыт немесе күн таңдайық па?")
    follow = ERROR_FOLLOW_UP.get(err.code, default)[i]
    head = "Кешіріңіз, брондауды қабылдай алмаймын" if lang == "kz" else "Извините, не могу принять бронь"
    return f"{head}: {reason}. {follow}".strip()


def summary_text(b: Booking, lang: str) -> str:
    if lang == "kz":
        return (
            "Брондау деректерін тексеріңіз:\n"
            f"• Есім: {b.name}\n• Күні мен уақыты: {human_date(b.day, 'kz')}, {b.time}\n"
            f"• Қонақтар: {b.guests}\n• Телефон: {b.phone}\nБәрі дұрыс па?"
        )
    return (
        "Проверьте, пожалуйста, данные брони:\n"
        f"• Имя: {b.name}\n• Дата и время: {human_date(b.day, 'ru')}, {b.time}\n"
        f"• Гостей: {b.guests}\n• Телефон: {b.phone}\nВсё верно?"
    )


def confirmed_text(b: Booking, lang: str) -> str:
    if lang == "kz":
        return (
            f"Дайын, {b.name}! Брондау жазылды: {human_date(b.day, 'kz')}, {b.time}, {b.guests} адам. "
            f"Үстелді {HOLD_MINUTES} минут ұстаймыз. Брондауды болдырмау не ауыстыру — {CAFE_PHONE} телефоны арқылы."
        )
    return (
        f"Готово, {b.name}! Бронь записана: {human_date(b.day, 'ru')}, {b.time}, гостей: {b.guests}. "
        f"Столик держим {HOLD_MINUTES} минут. Отменить или перенести бронь можно по телефону {CAFE_PHONE}."
    )


BOOKING_FIELDS = ["created_at", "chat_id", "username", "name", "date", "time", "guests", "phone"]


def save_booking(b: Booking, chat_id: int, username: str, path: Path, now: datetime) -> bool:
    """Дописывает бронь строкой в CSV. False, если такая бронь от этого чата уже есть."""
    row = {
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "chat_id": chat_id,
        "username": username,
        "name": b.name,
        "date": b.day.isoformat(),
        "time": b.time,
        "guests": b.guests,
        "phone": b.phone,
    }
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            for old in csv.DictReader(f):
                if (old["chat_id"], old["date"], old["time"], old["name"]) == (
                    str(chat_id), row["date"], row["time"], row["name"]):
                    return False
        f = path.open("a", encoding="utf-8", newline="")
    else:
        # BOM нужен, чтобы Excel правильно показал кириллицу
        f = path.open("w", encoding="utf-8-sig", newline="")
        csv.DictWriter(f, BOOKING_FIELDS).writeheader()
    with f:
        csv.DictWriter(f, BOOKING_FIELDS).writerow(row)
    return True


# ---------- диалог ----------

@dataclass
class Session:
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LIMIT))
    pending: Booking | None = None  # бронь, показанная гостю на подтверждение
    pending_id: int = 0
    lang: str = "ru"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class Reply:
    text: str
    confirm_id: int | None = None  # если задан — показать кнопки «Подтвердить / Изменить»
    saved: Booking | None = None


def clean_text(text: str) -> str:
    text = DRAFT_RE.sub("", text)
    text = CONFIRMED_RE.sub("", text)
    text = LEFTOVER_RE.sub("", text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class CafeAssistant:
    def __init__(self, llm: LLM, bookings_path: Path = BOOKINGS_PATH):
        self.llm = llm
        self.bookings_path = bookings_path
        self.prompt_template = load_prompt_template()
        self.sessions: dict[int, Session] = {}

    def session(self, chat_id: int) -> Session:
        return self.sessions.setdefault(chat_id, Session())

    def reset(self, chat_id: int) -> None:
        self.sessions.pop(chat_id, None)

    def _system_prompt(self, now: datetime) -> str:
        return self.prompt_template.replace("{{NOW}}", now_block(now))

    def _set_pending(self, s: Session, b: Booking) -> int:
        s.pending = b
        s.pending_id += 1
        return s.pending_id

    def _save(self, s: Session, b: Booking, chat_id: int, username: str, now: datetime) -> None:
        if save_booking(b, chat_id, username, self.bookings_path, now):
            log.info("бронь сохранена: chat=%s %s %s, гостей %s", chat_id, b.day, b.time, b.guests)
        else:
            log.info("повтор брони, не дублирую: chat=%s", chat_id)
        s.pending = None

    async def chat(self, chat_id: int, user_text: str, username: str = "",
                   set_lang: bool = True, now: datetime | None = None) -> Reply:
        s = self.session(chat_id)
        if set_lang:
            s.lang = detect_lang(user_text)
        now = now or datetime.now(TZ)
        s.history.append({"role": "user", "content": user_text})
        messages = [{"role": "system", "content": self._system_prompt(now)}, *s.history]
        try:
            raw, _model = await self.llm.complete(messages)
        except LLMUnavailable as e:
            log.error("нет ответа от моделей: %s", e)
            s.history.pop()
            if s.lang == "kz":
                return Reply("Кешіріңіз, қазір жауап бере алмай тұрмын — бір минуттан кейін қайталап көріңіз. "
                             f"Мәзірді «Меню» батырмасынан көруге болады, ал үстелді {CAFE_PHONE} арқылы брондауға болады.")
            return Reply("Извините, сейчас не получается ответить — попробуйте через минуту. "
                         f"Меню можно открыть кнопкой «Меню», а забронировать столик — по телефону {CAFE_PHONE}.")

        visible = clean_text(raw)
        confirmed, draft = CONFIRMED_RE.search(raw), DRAFT_RE.search(raw)

        try:
            if confirmed:
                b = parse_booking(confirmed.group(1))
                validate_booking(b, now)
                if s.pending == b:
                    self._save(s, b, chat_id, username, now)
                    text = visible or confirmed_text(b, s.lang)
                    s.history.append({"role": "assistant", "content": raw})
                    return Reply(text, saved=b)
                # модель «подтвердила» то, что гость ещё не видел: сначала показываем данные
                draft_id = self._set_pending(s, b)
                text = summary_text(b, s.lang)
                s.history.append({"role": "assistant", "content": text})
                return Reply(text, confirm_id=draft_id)
            if draft:
                b = parse_booking(draft.group(1))
                validate_booking(b, now)
                draft_id = self._set_pending(s, b)
                s.history.append({"role": "assistant", "content": raw})
                return Reply(visible or summary_text(b, s.lang), confirm_id=draft_id)
        except BookingError as e:
            log.info("бронь не прошла проверку: %s", e.code)
            text = error_text(e, s.lang)
            s.history.append({"role": "assistant", "content": text})
            return Reply(text)

        s.history.append({"role": "assistant", "content": raw})
        return Reply(visible)

    def confirm(self, chat_id: int, draft_id: int, username: str = "",
                now: datetime | None = None) -> Reply | None:
        """Кнопка «Подтвердить». None — кнопка устарела."""
        s = self.session(chat_id)
        if s.pending is None or draft_id != s.pending_id:
            return None
        now = now or datetime.now(TZ)
        b = s.pending
        try:
            validate_booking(b, now)
        except BookingError as e:
            s.pending = None
            return Reply(error_text(e, s.lang))
        self._save(s, b, chat_id, username, now)
        text = confirmed_text(b, s.lang)
        s.history.append({"role": "user", "content": "Подтверждаю бронь (нажал кнопку «Подтвердить»)"})
        s.history.append({"role": "assistant", "content": text})
        return Reply(text, saved=b)

    def is_current_draft(self, chat_id: int, draft_id: int) -> bool:
        s = self.session(chat_id)
        return s.pending is not None and draft_id == s.pending_id
