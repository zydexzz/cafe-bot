"""Telegram-бот кофейни qaz.su. Запуск: .venv\\Scripts\\python.exe bot.py"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
                      Update)
from telegram.constants import ChatAction, ParseMode
from telegram.error import Conflict
from telegram.ext import (Application, ApplicationBuilder, CallbackQueryHandler,
                          CommandHandler, ContextTypes, MessageHandler, filters)

from cafe import BASE_DIR, DEFAULT_MODELS, LLM, CafeAssistant, Reply, menu_for_telegram

log = logging.getLogger("bot")

BTN_MENU = "Меню"
BTN_BOOK = "Забронировать столик"
MAIN_KEYBOARD = ReplyKeyboardMarkup([[BTN_MENU, BTN_BOOK]], resize_keyboard=True, is_persistent=True)
MENU_RE = r"(?i)^\s*(меню|мәзір)\s*$"
BOOK_RE = rf"^\s*{BTN_BOOK}\s*$"

START_TEXT = (
    "Здравствуйте! Сәлеметсіз бе! ☕\n"
    "Я помощник кофейни qaz.su в Караганде: подскажу по меню и ценам, расскажу об акциях "
    "и забронирую столик. Пишите по-русски или по-казахски.\n\n"
    "Кнопки внизу: «Меню» — полное меню с ценами, «Забронировать столик» — бронь за минуту."
)
RESET_TEXT = "История диалога очищена, начнём заново. Чем могу помочь?\nДиалог тарихы тазартылды."


def setup_logging() -> None:
    (BASE_DIR / "logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file = RotatingFileHandler(BASE_DIR / "logs" / "bot.log", maxBytes=1_000_000,
                               backupCount=3, encoding="utf-8")
    console = logging.StreamHandler()
    for h in (file, console):
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[file, console])
    # httpx пишет в лог URL запросов, а в URL Telegram API есть токен бота
    logging.getLogger("httpx").setLevel(logging.WARNING)


def acquire_single_instance_lock():
    """Не даёт запустить вторую копию бота на этом компьютере. PID пишется в bot.pid."""
    f = open(BASE_DIR / "bot.pid", "a+")
    try:
        if os.name == "nt":
            import msvcrt
            # Блокируем байт далеко за концом файла: Windows не даёт читать диапазон,
            # который задевает блокировку, а PID должен читаться для Stop-Process.
            f.seek(1 << 30)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    return f


def assistant(context: ContextTypes.DEFAULT_TYPE) -> CafeAssistant:
    return context.application.bot_data["assistant"]


def confirm_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Подтвердить · Растау", callback_data=f"confirm:{draft_id}"),
        InlineKeyboardButton("✏️ Изменить · Өзгерту", callback_data=f"edit:{draft_id}"),
    ]])


@contextlib.asynccontextmanager
async def typing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает «печатает…», пока модель думает."""
    async def loop():
        while True:
            with contextlib.suppress(Exception):
                await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
            await asyncio.sleep(4)

    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        task.cancel()


async def drop_old_buttons(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    msg_id = context.chat_data.pop("draft_msg_id", None)
    if msg_id:
        with contextlib.suppress(Exception):
            await context.bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)


async def send_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, reply: Reply) -> None:
    chat_id = update.effective_chat.id
    if reply.confirm_id is not None or reply.saved is not None:
        await drop_old_buttons(context, chat_id)
    markup = confirm_keyboard(reply.confirm_id) if reply.confirm_id is not None else MAIN_KEYBOARD
    msg = await context.bot.send_message(chat_id, reply.text, reply_markup=markup)
    if reply.confirm_id is not None:
        context.chat_data["draft_msg_id"] = msg.message_id


async def ask_ai(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, set_lang: bool = True) -> None:
    a = assistant(context)
    chat = update.effective_chat
    user = update.effective_user
    async with a.session(chat.id).lock:
        async with typing(update, context):
            reply = await a.chat(chat.id, text, username=(user.username or "") if user else "",
                                 set_lang=set_lang)
        await send_reply(update, context, reply)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assistant(context).reset(update.effective_chat.id)
    await drop_old_buttons(context, update.effective_chat.id)
    await update.message.reply_text(START_TEXT, reply_markup=MAIN_KEYBOARD)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assistant(context).reset(update.effective_chat.id)
    await drop_old_buttons(context, update.effective_chat.id)
    await update.message.reply_text(RESET_TEXT, reply_markup=MAIN_KEYBOARD)


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(menu_for_telegram(), parse_mode=ParseMode.HTML,
                                    reply_markup=MAIN_KEYBOARD)


async def on_book(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ask_ai(update, context, BTN_BOOK, set_lang=False)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ask_ai(update, context, update.message.text)


async def on_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Пока я понимаю только текст. Напишите, пожалуйста, сообщением 🙂\n"
        "Әзірге тек мәтінді түсінемін.",
        reply_markup=MAIN_KEYBOARD,
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    action, _, raw_id = (q.data or "").partition(":")
    a = assistant(context)
    chat_id = update.effective_chat.id
    draft_id = int(raw_id) if raw_id.isdigit() else -1

    if not a.is_current_draft(chat_id, draft_id):
        await q.answer("Эта бронь уже неактуальна · Бұл брондау өзекті емес")
        with contextlib.suppress(Exception):
            await q.edit_message_reply_markup(reply_markup=None)
        return

    await q.answer()
    with contextlib.suppress(Exception):
        await q.edit_message_reply_markup(reply_markup=None)
    context.chat_data.pop("draft_msg_id", None)

    if action == "confirm":
        async with a.session(chat_id).lock:
            user = update.effective_user
            reply = a.confirm(chat_id, draft_id, username=(user.username or "") if user else "")
        if reply:
            await send_reply(update, context, reply)
    elif action == "edit":
        text = "Брондау деректерін өзгерткім келеді" if a.session(chat_id).lang == "kz" \
            else "Хочу изменить данные брони"
        await ask_ai(update, context, text, set_lang=False)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, Conflict):
        log.critical("С этим токеном уже работает другая копия бота (возможно, на другом компьютере). Останавливаюсь.")
        context.application.stop_running()
        return
    log.error("Ошибка при обработке обновления", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        with contextlib.suppress(Exception):
            await context.bot.send_message(
                update.effective_chat.id,
                "Ой, что-то пошло не так. Попробуйте ещё раз или нажмите /reset.",
            )


async def on_startup(app: Application) -> None:
    me = await app.bot.get_me()
    log.info("Подключился к Telegram как @%s", me.username)
    await app.bot.set_my_commands([
        ("start", "Начать сначала / Басынан бастау"),
        ("reset", "Очистить историю диалога / Тарихты тазарту"),
    ])


async def on_shutdown(app: Application) -> None:
    await app.bot_data["assistant"].llm.close()


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    setup_logging()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not token or not api_key:
        sys.exit("Заполните TELEGRAM_BOT_TOKEN и OPENROUTER_API_KEY в .env (образец — .env.example)")

    lock = acquire_single_instance_lock()
    if lock is None:
        sys.exit("Бот уже запущен на этом компьютере (см. bot.pid). Остановите его и запустите снова.")

    models = [m.strip() for m in os.getenv("OPENROUTER_MODELS", "").split(",") if m.strip()] or DEFAULT_MODELS
    log.info("Модели: %s", ", ".join(models))

    app = (ApplicationBuilder().token(token).concurrent_updates(True)
           .post_init(on_startup).post_shutdown(on_shutdown).build())
    app.bot_data["assistant"] = CafeAssistant(LLM(api_key, models))

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(MENU_RE), on_menu))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(BOOK_RE), on_book))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND & ~filters.StatusUpdate.ALL, on_other))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^(confirm|edit):\d+$"))
    app.add_error_handler(on_error)

    log.info("Бот запущен. Остановить: Ctrl+C")
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        lock.close()


if __name__ == "__main__":
    main()
