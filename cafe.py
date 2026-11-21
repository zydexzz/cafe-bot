"""Логика бота кофейни qaz.su без привязки к Telegram.

Здесь: загрузка system prompt и меню, запросы к OpenRouter с запасными моделями,
память диалога, форма брони (заявка разбирается моделью в JSON), запись в bookings.csv.
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
    """system_prompt.md с подставленным menu.md. {{NOW}}, если он есть, заполняется при каждом запросе."""
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    menu = MENU_PATH.read_text(encoding="utf-8").strip()
    if "{{MENU}}" not in prompt:
        raise RuntimeError("В system_prompt.md нет {{MENU}}")
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

    async def complete(self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 700,
                       json_mode: bool = False) -> tuple[str, str]:
        """Возвращает (текст, модель). Модели перебираются по порядку при 429, ошибках и пустом ответе."""
        now = time.monotonic()
        ready = [m for m in self.models if self.cooldown.get(m, 0) <= now]
        for model in ready or self.models:
            body = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "reasoning": {"enabled": False, "exclude": True},
            }
            if json_mode:  # просим у провайдера чистый JSON; где не поддерживается, OpenRouter это игнорирует
                body["response_format"] = {"type": "json_object"}
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


# ---------- бронь: данные, проверки, тексты ----------

EXTRACT_PROMPT_PATH = BASE_DIR / "booking_extract_prompt.md"
FORM_FIELDS = ["date", "time", "guests", "name", "phone"]  # в этом порядке бот спрашивает недостающее

# Сообщения, после которых включается форма брони (дальше intent из JSON решает, бронь это или нет):
# слова про бронь, номер телефона или «время + сколько человек»
BOOKING_TRIGGER_RE = re.compile(
    r"брон|резерв|столик|\bстол(?:ы|а|ик)?\b|үстел"
    r"|(?:\+?\d[\s\-()]*){10,}"
    r"|\b\d{1,2}[:.]\d{2}\b.*(?:человек|чел\b|гост|двоих|троих|четвер|адам|қонақ)"
    r"|(?:человек|чел\b|гост|двоих|троих|четвер|адам|қонақ).*\b\d{1,2}[:.]\d{2}\b",
    re.I | re.S,
)
CANCEL_RE = re.compile(r"^\s*(отмена|отмени(?:ть)?|передумал[аи]?|не надо|не нужно|стоп|болдырма|керек емес)\b", re.I)
YES_WORDS = {"да", "ага", "угу", "верно", "правильно", "всё", "все", "подтверждаю", "подтверждаем", "ок", "окей",
             "ok", "okay", "yes", "конечно", "точно", "давай", "бронируй", "иә", "ия", "дұрыс", "бәрі", "растаймын"}
NO_WORDS = {"нет", "неа", "не", "неверно", "неправильно", "жоқ", "қате"}


@dataclass(frozen=True)
class Booking:
    name: str
    day: date
    time: str  # ЧЧ:ММ
    guests: int
    phone: str  # +7 и 10 цифр


class BookingError(Exception):
    def __init__(self, code: str, **kw):
        super().__init__(code)
        self.code = code
        self.kw = kw


BOOKING_ERRORS = {  # (русский, казахский)
    "bad": ("не хватает имени", "есімің жетіспейді"),
    "past_date": ("эта дата уже прошла", "бұл күн өтіп кетті"),
    "past": ("это время уже прошло", "бұл уақыт өтіп кетті"),
    "too_far": (f"бронь принимаем не дальше чем на {BOOKING_DAYS_AHEAD} дней вперёд",
                f"брондауды {BOOKING_DAYS_AHEAD} күннен артық алдын ала қабылдамаймыз"),
    "hours": ("в этот день столик можно забронировать с {first} до {last}",
              "бұл күні үстелді {first} мен {last} аралығында брондауға болады"),
    "guests_bad": ("число гостей должно быть от 1 до 8", "қонақ саны 1-ден 8-ге дейін болуы керек"),
    "guests_big": (f"через бота бронируем столик на 1–{MAX_GUESTS} гостей, для большой компании звони {CAFE_PHONE}",
                   f"бот арқылы 1–{MAX_GUESTS} адамға брондаймыз, үлкен компания үшін {CAFE_PHONE} нөміріне қоңырау шал"),
    "phone": ("в номере телефона должно быть 11 цифр", "телефон нөмірінде 11 цифр болуы керек"),
}

ERROR_FIELD = {"bad": "name", "past_date": "date", "too_far": "date", "hours": "time", "past": "time",
               "guests_bad": "guests", "guests_big": "guests", "phone": "phone"}

QUESTIONS = {  # один вопрос на каждое недостающее поле
    "date": ("На какую дату бронируем?", "Қай күнге брондаймыз?"),
    "time": ("На какое время?", "Сағат нешеге?"),
    "guests": ("Сколько будет гостей?", "Қанша қонақ болады?"),
    "name": ("На какое имя записать?", "Қай есімге жазайын?"),
    "phone": ("Оставь номер телефона — 11 цифр, например +7 701 123 45 67.",
              "Телефон нөміріңді жаз — 11 цифр, мысалы +7 701 123 45 67."),
}
TEXTS = {
    "start": ("Давай забронируем! Можно одним сообщением: дата, время, сколько гостей, имя и телефон.",
              "Брондайық! Бір хабарламамен жазуға болады: күні, уақыты, қонақ саны, есімің және телефон."),
    "parse_failed": ("Извини, не получилось разобрать заявку 🙏 Напиши её, пожалуйста, ещё раз одним сообщением: "
                     "дата, время, сколько гостей, имя и телефон.",
                     "Кешір, өтінішті түсіне алмадым 🙏 Қайта бір хабарламамен жазшы: "
                     "күні, уақыты, қонақ саны, есімің және телефон."),
    "edit": ("Что поменять? Напиши новое значение: дату, время, число гостей, имя или телефон.",
             "Нені өзгертеміз? Жаңа мәнін жаз: күні, уақыты, қонақ саны, есімің немесе телефон."),
    "cancel": ("Окей, бронь не оформляю. Если передумаешь — кнопка «Забронировать столик» внизу.",
               "Жарайды, брондауды тоқтаттым. Ойыңнан қайтсаң — төмендегі «Забронировать столик» батырмасы."),
    "unavailable": ("Извини, сейчас не получается ответить — попробуй через минуту. "
                    f"Меню можно открыть кнопкой «Меню», а забронировать столик — по телефону {CAFE_PHONE}.",
                    "Кешір, қазір жауап бере алмай тұрмын — бір минуттан кейін қайталап көр. "
                    f"Мәзірді «Меню» батырмасынан көруге болады, ал үстелді {CAFE_PHONE} арқылы брондауға болады."),
}


def t(key: tuple[str, str], lang: str) -> str:
    return key[1] if lang == "kz" else key[0]


def normalize_phone(raw: str) -> str | None:
    """11 цифр, первая 7 или 8 → «+7XXXXXXXXXX». Иначе None."""
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) != 11 or digits[0] not in "78":
        return None
    return "+7" + digits[1:]


def format_phone(p: str) -> str:
    d = p[2:]
    return f"+7 {d[:3]} {d[3:6]} {d[6:8]} {d[8:]}"


def validate_booking(b: Booking, now: datetime) -> None:
    """Финальная проверка перед записью в CSV."""
    if not b.name:
        raise BookingError("bad")
    if b.guests > MAX_GUESTS:
        raise BookingError("guests_big")
    if b.guests < 1:
        raise BookingError("guests_bad")
    if normalize_phone(b.phone) != b.phone:
        raise BookingError("phone")
    if b.day < now.date():
        raise BookingError("past_date")
    if b.day > now.date() + timedelta(days=BOOKING_DAYS_AHEAD):
        raise BookingError("too_far")
    first, last = booking_window(b.day)
    if not first <= b.time <= last:
        raise BookingError("hours", first=first, last=last)
    if b.day == now.date() and b.time <= now.strftime("%H:%M"):
        raise BookingError("past")


def check_form(data: dict, now: datetime) -> tuple[str, BookingError] | None:
    """Проверяет уже известные поля заявки. Возвращает (поле, ошибка) для первого неверного поля."""
    day = date.fromisoformat(data["date"]) if data["date"] else None
    if day:
        if day < now.date():
            return "date", BookingError("past_date")
        if day > now.date() + timedelta(days=BOOKING_DAYS_AHEAD):
            return "date", BookingError("too_far")
        if data["time"]:
            first, last = booking_window(day)
            if not first <= data["time"] <= last:
                return "time", BookingError("hours", first=first, last=last)
            if day == now.date() and data["time"] <= now.strftime("%H:%M"):
                return "time", BookingError("past")
    if data["guests"] is not None:
        if data["guests"] > MAX_GUESTS:
            return "guests", BookingError("guests_big")
        if data["guests"] < 1:
            return "guests", BookingError("guests_bad")
    if data["phone"] is not None and normalize_phone(data["phone"]) is None:
        return "phone", BookingError("phone")
    return None


def form_to_booking(data: dict) -> Booking:
    return Booking(name=data["name"], day=date.fromisoformat(data["date"]), time=data["time"],
                   guests=data["guests"], phone=normalize_phone(data["phone"]))


def summary_text(b: Booking, lang: str) -> str:
    if lang == "kz":
        return (
            "Брондау деректерін тексер:\n"
            f"• Есім: {b.name}\n• Күні мен уақыты: {human_date(b.day, 'kz')}, {b.time}\n"
            f"• Қонақтар: {b.guests}\n• Телефон: {format_phone(b.phone)}\nРастайсың ба?"
        )
    return (
        "Проверь данные брони:\n"
        f"• Имя: {b.name}\n• Дата и время: {human_date(b.day, 'ru')}, {b.time}\n"
        f"• Гостей: {b.guests}\n• Телефон: {format_phone(b.phone)}\nПодтверждаешь?"
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


# ---------- бронь: разбор заявки моделью в JSON ----------

def extract_prompt(template: str, now: datetime, expected: str | None) -> str:
    """booking_extract_prompt.md с сегодняшней датой, календарём и полем, про которое спросили гостя."""
    today = f"{now.date().isoformat()}, {WEEKDAYS_RU[now.weekday()]}, сейчас {now:%H:%M} (время Караганды)."
    calendar = []
    for i in range(BOOKING_DAYS_AHEAD + 1):
        d = now.date() + timedelta(days=i)
        mark = " (сегодня)" if i == 0 else " (завтра)" if i == 1 else " (послезавтра)" if i == 2 else ""
        calendar.append(f"{d.isoformat()} — {WEEKDAYS_RU[d.weekday()]}{mark}")
    hint = f"Гость отвечает на вопрос про поле {expected}." if expected else ""
    return (template.replace("{{TODAY}}", today)
            .replace("{{CALENDAR}}", "\n".join(calendar))
            .replace("{{EXPECTED}}", hint)
            .replace("{{TOMORROW}}", (now.date() + timedelta(days=1)).isoformat()))


def _clean_date(v) -> str | None:
    try:
        return date.fromisoformat(str(v).strip()).isoformat() if v else None
    except ValueError:
        return None


def _clean_time(v) -> str | None:
    try:
        return datetime.strptime(str(v).strip(), "%H:%M").strftime("%H:%M") if v else None
    except ValueError:
        return None


def _clean_int(v) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return int(str(v).strip())
    except ValueError:
        return None


def _clean_name(v) -> str | None:
    if not isinstance(v, str):
        return None
    name = v.strip().lstrip("=+-@\t\r").strip()  # формула в начале ячейки выполнится в Excel
    return name[:60] or None


def _clean_phone(v) -> str | None:
    digits = re.sub(r"\D", "", str(v)) if v else ""
    return digits or None


REQUIRED_KEYS = {"intent", *FORM_FIELDS, "missing"}


def parse_extraction(raw: str) -> dict:
    """Разбирает ответ модели. ValueError — если это не JSON нужного вида."""
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", raw.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("в ответе нет JSON-объекта")
    data = json.loads(text[start:end + 1])  # json.JSONDecodeError — подкласс ValueError
    if not isinstance(data, dict) or not REQUIRED_KEYS <= data.keys() or not isinstance(data["missing"], list):
        raise ValueError("в JSON не те поля")
    out = {
        "intent": "booking" if data["intent"] == "booking" else "other",
        "date": _clean_date(data["date"]),
        "time": _clean_time(data["time"]),
        "guests": _clean_int(data["guests"]),
        "name": _clean_name(data["name"]),
        "phone": _clean_phone(data["phone"]),
    }
    for f in data["missing"]:  # модель сама сказала, что поля нет, — не верим значению
        if f in FORM_FIELDS:
            out[f] = None
    out["missing"] = [f for f in FORM_FIELDS if out[f] is None]
    return out


# ---------- диалог ----------

@dataclass
class BookingForm:
    data: dict = field(default_factory=lambda: dict.fromkeys(FORM_FIELDS))
    asking: str | None = None        # поле, про которое бот спросил последним
    confirm_id: int | None = None    # задан, пока гость смотрит итог и должен ответить «да»


@dataclass
class Session:
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LIMIT))
    form: BookingForm | None = None
    seq: int = 0
    lang: str = "ru"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class Reply:
    text: str
    confirm_id: int | None = None  # если задан — показать кнопки «Подтвердить / Изменить»
    saved: Booking | None = None


def clean_text(text: str) -> str:
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\wәғқңөұүһі]+", text.lower()))


def is_yes(text: str) -> bool:
    w = _words(text)
    return bool(w) and w <= YES_WORDS


def is_no(text: str) -> bool:
    w = _words(text)
    return bool(w) and w <= NO_WORDS


class CafeAssistant:
    def __init__(self, llm: LLM, bookings_path: Path = BOOKINGS_PATH):
        self.llm = llm
        self.bookings_path = bookings_path
        self.prompt_template = load_prompt_template()
        self.extract_template = EXTRACT_PROMPT_PATH.read_text(encoding="utf-8")
        self.sessions: dict[int, Session] = {}

    def session(self, chat_id: int) -> Session:
        return self.sessions.setdefault(chat_id, Session())

    def reset(self, chat_id: int) -> None:
        self.sessions.pop(chat_id, None)

    def _remember(self, s: Session, user_text: str, reply: Reply) -> Reply:
        s.history.append({"role": "user", "content": user_text})
        s.history.append({"role": "assistant", "content": reply.text})
        return reply

    # --- вход ---

    async def chat(self, chat_id: int, user_text: str, username: str = "",
                   set_lang: bool = True, now: datetime | None = None) -> Reply:
        s = self.session(chat_id)
        if set_lang:
            s.lang = detect_lang(user_text)
        now = now or datetime.now(TZ)
        if s.form is None and BOOKING_TRIGGER_RE.search(user_text):
            s.form = BookingForm()
        if s.form is not None:
            return await self._form_step(s, chat_id, user_text, username, now)
        return await self._free_chat(s, user_text, now)

    def start_booking(self, chat_id: int, button_text: str) -> Reply:
        """Кнопка «Забронировать столик»: открывает форму без запроса к модели."""
        s = self.session(chat_id)
        s.form = BookingForm(asking=FORM_FIELDS[0])
        text = f"{t(TEXTS['start'], s.lang)}\n{t(QUESTIONS[FORM_FIELDS[0]], s.lang)}"
        return self._remember(s, button_text, Reply(text))

    # --- обычный разговор ---

    async def _free_chat(self, s: Session, user_text: str, now: datetime) -> Reply:
        system = self.prompt_template.replace("{{NOW}}", now_block(now))
        messages = [{"role": "system", "content": system}, *s.history, {"role": "user", "content": user_text}]
        try:
            raw, _model = await self.llm.complete(messages)
        except LLMUnavailable as e:
            log.error("нет ответа от моделей: %s", e)
            return Reply(t(TEXTS["unavailable"], s.lang))
        return self._remember(s, user_text, Reply(clean_text(raw)))

    # --- форма брони ---

    async def _extract(self, s: Session, user_text: str, now: datetime) -> dict | None:
        """Сообщение гостя → JSON с данными брони. Один повтор, если JSON не разобрался."""
        messages = [
            {"role": "system", "content": extract_prompt(self.extract_template, now, s.form.asking)},
            {"role": "user", "content": user_text},
        ]
        for attempt in (1, 2):
            raw, model = await self.llm.complete(messages, temperature=0, max_tokens=300, json_mode=True)
            try:
                return parse_extraction(raw)
            except ValueError as e:
                log.warning("заявка: JSON не разобран (попытка %s, %s): %s", attempt, model, e)
        return None

    def _ask(self, s: Session, f: str) -> str:
        s.form.asking = f
        return t(QUESTIONS[f], s.lang)

    async def _form_step(self, s: Session, chat_id: int, user_text: str, username: str,
                         now: datetime) -> Reply:
        form = s.form
        if CANCEL_RE.search(user_text):
            s.form = None
            return self._remember(s, user_text, Reply(t(TEXTS["cancel"], s.lang)))

        if form.confirm_id is not None:  # гость видит итог
            if is_yes(user_text):
                return self._remember(s, user_text, self._finish(s, chat_id, username, now))
            form.confirm_id = None
            if is_no(user_text):
                form.asking = None
                return self._remember(s, user_text, Reply(t(TEXTS["edit"], s.lang)))
            # иначе это правка вроде «нет, на 20:00» — разбираем как обычное сообщение

        try:
            ext = await self._extract(s, user_text, now)
        except LLMUnavailable as e:
            log.error("нет ответа от моделей: %s", e)
            return Reply(t(TEXTS["unavailable"], s.lang))
        if ext is None:
            return self._remember(s, user_text, Reply(t(TEXTS["parse_failed"], s.lang)))

        found = {f: ext[f] for f in FORM_FIELDS if ext[f] is not None}
        if ext["intent"] == "other" and not found:
            if not any(form.data.values()) and form.asking is None:
                s.form = None  # слово «бронь» было, но заявки нет — обычный разговор
                return await self._free_chat(s, user_text, now)
            reply = await self._free_chat(s, user_text, now)  # вопрос посреди брони
            if s.form is form and form.asking:
                reply.text += "\n\n" + t(QUESTIONS[form.asking], s.lang)
            return reply

        form.data.update(found)
        problem = check_form(form.data, now)
        if problem:
            f, err = problem
            reason = t(BOOKING_ERRORS[err.code], s.lang).format(**err.kw)
            log.info("заявка: поле %s не прошло проверку: %s", f, err.code)
            if err.code == "guests_big":
                s.form = None
                return self._remember(s, user_text, Reply(reason[0].upper() + reason[1:] + "."))
            form.data[f] = None
            head = "Не получится" if s.lang == "ru" else "Болмайды"
            return self._remember(s, user_text, Reply(f"{head}: {reason}. {self._ask(s, f)}"))

        # модель вернула missing по одному сообщению; с учётом уже собранных данных пусто только то, чего нет нигде
        missing = [f for f in FORM_FIELDS if form.data[f] is None]
        if missing:
            return self._remember(s, user_text, Reply(self._ask(s, missing[0])))

        s.seq += 1
        form.confirm_id = s.seq
        form.asking = None
        b = form_to_booking(form.data)
        return self._remember(s, user_text, Reply(summary_text(b, s.lang), confirm_id=form.confirm_id))

    def _finish(self, s: Session, chat_id: int, username: str, now: datetime) -> Reply:
        b = form_to_booking(s.form.data)
        try:
            validate_booking(b, now)  # между итогом и «да» могло пройти время
        except BookingError as e:
            reason = t(BOOKING_ERRORS[e.code], s.lang).format(**e.kw)
            f = ERROR_FIELD[e.code]
            s.form.confirm_id = None
            s.form.data[f] = None
            return Reply(f"{'Не получится' if s.lang == 'ru' else 'Болмайды'}: {reason}. {self._ask(s, f)}")
        s.form = None
        if save_booking(b, chat_id, username, self.bookings_path, now):
            log.info("бронь сохранена: chat=%s %s %s, гостей %s", chat_id, b.day, b.time, b.guests)
        else:
            log.info("повтор брони, не дублирую: chat=%s", chat_id)
        return Reply(confirmed_text(b, s.lang), saved=b)

    # --- кнопки под итогом ---

    def is_current_confirm(self, chat_id: int, confirm_id: int) -> bool:
        s = self.session(chat_id)
        return s.form is not None and s.form.confirm_id == confirm_id

    def confirm(self, chat_id: int, confirm_id: int, username: str = "",
                now: datetime | None = None) -> Reply | None:
        """Кнопка «Подтвердить». None — кнопка устарела."""
        if not self.is_current_confirm(chat_id, confirm_id):
            return None
        s = self.session(chat_id)
        reply = self._finish(s, chat_id, username, now or datetime.now(TZ))
        return self._remember(s, "Подтверждаю (кнопка «Подтвердить»)", reply)

    def edit(self, chat_id: int, confirm_id: int) -> Reply | None:
        """Кнопка «Изменить». None — кнопка устарела."""
        if not self.is_current_confirm(chat_id, confirm_id):
            return None
        s = self.session(chat_id)
        s.form.confirm_id = None
        s.form.asking = None
        return self._remember(s, "Хочу изменить (кнопка «Изменить»)", Reply(t(TEXTS["edit"], s.lang)))
