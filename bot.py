import asyncio
import logging
import os
import json
import csv
import re
from datetime import datetime, date
from pathlib import Path

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import google.generativeai as genai

from config import BOT_TOKEN, GEMINI_API_KEY, SEND_HOUR, SEND_MINUTE
from database import Database
from holidays_manager import HolidaysManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ─── Init ───────────────────────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db = Database("subscribers.json")
hm = HolidaysManager("holidays.json")

genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel("gemini-1.5-flash")


class UploadStates(StatesGroup):
    waiting_for_file = State()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def main_keyboard(subscribed: bool) -> ReplyKeyboardMarkup:
    sub_btn = "🔕 Отписаться от рассылки" if subscribed else "🔔 Подписаться на рассылку"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎉 Праздники сегодня")],
            [KeyboardButton(text=sub_btn)],
            [KeyboardButton(text="📁 Загрузить файл с праздниками")],
            [KeyboardButton(text="📅 Праздники на дату"), KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True
    )


async def get_holidays_message(target_date: date, use_ai: bool = True) -> str:
    """Build a formatted holiday message for a given date."""
    custom = hm.get_holidays(target_date)
    date_str = target_date.strftime("%d %B %Y")
    weekday_ru = [
        "Понедельник", "Вторник", "Среда", "Четверг",
        "Пятница", "Суббота", "Воскресенье"
    ][target_date.weekday()]

    if use_ai:
        try:
            prompt = (
                f"Сегодня {weekday_ru}, {date_str}. "
                f"Расскажи интересно и кратко (3-5 предложений) о праздниках, "
                f"памятных датах и событиях, которые отмечаются {date_str}. "
                f"Пиши по-русски, живо и с настроением. "
                f"Начни сразу с праздников без вступлений типа 'Конечно!'. "
                + (f"Также обязательно упомяни эти пользовательские праздники: {', '.join(custom)}. " if custom else "")
            )
            response = await asyncio.to_thread(
                lambda: gemini.generate_content(prompt).text
            )
            ai_text = response.strip()
        except Exception as e:
            logger.warning(f"Gemini error: {e}")
            ai_text = None
    else:
        ai_text = None

    lines = [f"🗓 *{weekday_ru}, {date_str}*\n"]

    if custom:
        lines.append("📌 *Ваши праздники:*")
        for h in custom:
            lines.append(f"  • {h}")
        lines.append("")

    if ai_text:
        lines.append("🤖 *Праздники дня:*")
        lines.append(ai_text)
    else:
        lines.append("🎉 *Праздники дня:*")
        lines.append("Сегодня много интересных праздников — исследуйте!")

    return "\n".join(lines)


# ─── Broadcast ───────────────────────────────────────────────────────────────

async def daily_broadcast():
    """Send daily holiday digest to all subscribers."""
    subscribers = db.get_all_subscribers()
    if not subscribers:
        logger.info("No subscribers, skipping broadcast.")
        return

    today = date.today()
    message = await get_holidays_message(today)
    logger.info(f"Broadcasting to {len(subscribers)} subscribers...")

    for chat_id in subscribers:
        try:
            await bot.send_message(chat_id, message, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Failed to send to {chat_id}: {e}")
            if "blocked" in str(e).lower() or "deactivated" in str(e).lower():
                db.remove_subscriber(chat_id)


# ─── Handlers ────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    subscribed = db.is_subscribed(message.chat.id)
    await message.answer(
        "👋 *Добро пожаловать в Holiday Bot!*\n\n"
        "Я буду присылать тебе праздники каждый день 🎊\n\n"
        "Выбери действие в меню ниже:",
        parse_mode="Markdown",
        reply_markup=main_keyboard(subscribed)
    )


@dp.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: types.Message):
    await message.answer(
        "📖 *Как пользоваться ботом:*\n\n"
        "🔔 *Подписаться* — получать праздники каждый день\n"
        f"   Рассылка приходит в {SEND_HOUR:02d}:{SEND_MINUTE:02d} по МСК\n\n"
        "🎉 *Праздники сегодня* — узнать праздники прямо сейчас\n\n"
        "📅 *Праздники на дату* — праздники на любой день\n"
        "   Введи дату в формате `ДД.ММ` или `ДД.ММ.ГГГГ`\n\n"
        "📁 *Загрузить файл* — добавить свои праздники\n"
        "   Поддерживаемые форматы:\n"
        "   • CSV: `дата,название` (напр. `25.12,Рождество`)\n"
        "   • TXT: `дата - название` (одна строка = один праздник)\n"
        "   • JSON: `{\"ДД.ММ\": [\"Праздник1\", ...]}`\n",
        parse_mode="Markdown"
    )


@dp.message(F.text == "🎉 Праздники сегодня")
async def today_holidays(message: types.Message):
    msg = await message.answer("⏳ Загружаю праздники...")
    text = await get_holidays_message(date.today())
    await msg.edit_text(text, parse_mode="Markdown")


@dp.message(F.text.in_(["🔔 Подписаться на рассылку", "🔕 Отписаться от рассылки"]))
async def toggle_subscription(message: types.Message):
    chat_id = message.chat.id
    if db.is_subscribed(chat_id):
        db.remove_subscriber(chat_id)
        await message.answer(
            "🔕 Вы отписались от рассылки.\n"
            "Вы всегда можете подписаться снова!",
            reply_markup=main_keyboard(False)
        )
    else:
        db.add_subscriber(chat_id)
        await message.answer(
            f"🔔 Вы подписались на рассылку!\n"
            f"Праздники будут приходить каждый день в {SEND_HOUR:02d}:{SEND_MINUTE:02d} 🎉",
            reply_markup=main_keyboard(True)
        )


@dp.message(F.text == "📅 Праздники на дату")
async def ask_date(message: types.Message, state: FSMContext):
    await state.set_state(UploadStates.waiting_for_file)
    await state.update_data(mode="date")
    await message.answer(
        "📅 Введите дату в формате `ДД.ММ` или `ДД.ММ.ГГГГ`\n"
        "Например: `25.12` или `09.05.2025`",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )


@dp.message(F.text == "📁 Загрузить файл с праздниками")
async def ask_file(message: types.Message, state: FSMContext):
    await state.set_state(UploadStates.waiting_for_file)
    await state.update_data(mode="file")
    await message.answer(
        "📁 Отправьте файл с праздниками.\n\n"
        "*Поддерживаемые форматы:*\n"
        "• *CSV*: `дата,название`\n"
        "• *TXT*: `дата - название`\n"
        "• *JSON*: `{\"ДД.ММ\": [\"Праздник\"]}`\n\n"
        "_Дата в формате ДД.ММ (напр. 01.01 или 25.12)_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )


@dp.message(UploadStates.waiting_for_file, F.text)
async def handle_date_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("mode") != "date":
        return

    text = message.text.strip()
    target = None

    try:
        if re.match(r"^\d{2}\.\d{2}$", text):
            day, month = map(int, text.split("."))
            target = date(date.today().year, month, day)
        elif re.match(r"^\d{2}\.\d{2}\.\d{4}$", text):
            target = datetime.strptime(text, "%d.%m.%Y").date()
        else:
            raise ValueError("Bad format")
    except Exception:
        subscribed = db.is_subscribed(message.chat.id)
        await state.clear()
        await message.answer(
            "❌ Неверный формат даты. Попробуйте `ДД.ММ` или `ДД.ММ.ГГГГ`",
            parse_mode="Markdown",
            reply_markup=main_keyboard(subscribed)
        )
        return

    await state.clear()
    subscribed = db.is_subscribed(message.chat.id)
    msg = await message.answer("⏳ Загружаю праздники...", reply_markup=main_keyboard(subscribed))
    holiday_text = await get_holidays_message(target)
    await msg.edit_text(holiday_text, parse_mode="Markdown")


@dp.message(UploadStates.waiting_for_file, F.document)
async def handle_file_upload(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("mode") != "file":
        return

    await state.clear()
    subscribed = db.is_subscribed(message.chat.id)
    doc = message.document
    fname = doc.file_name.lower()

    if not (fname.endswith(".csv") or fname.endswith(".txt") or fname.endswith(".json")):
        await message.answer(
            "❌ Неподдерживаемый формат. Пришлите CSV, TXT или JSON файл.",
            reply_markup=main_keyboard(subscribed)
        )
        return

    file = await bot.get_file(doc.file_id)
    file_bytes = await bot.download_file(file.file_path)
    content = file_bytes.read().decode("utf-8", errors="ignore")

    try:
        count = hm.import_from_text(content, fname)
        await message.answer(
            f"✅ Загружено праздников: *{count}*\n"
            f"Они будут включены в ежедневную рассылку! 🎉",
            parse_mode="Markdown",
            reply_markup=main_keyboard(subscribed)
        )
    except Exception as e:
        logger.error(f"File parse error: {e}")
        await message.answer(
            f"❌ Ошибка при разборе файла: {e}\n"
            "Проверьте формат и попробуйте снова.",
            reply_markup=main_keyboard(subscribed)
        )


@dp.message()
async def fallback(message: types.Message, state: FSMContext):
    await state.clear()
    subscribed = db.is_subscribed(message.chat.id)
    await message.answer(
        "Используйте кнопки меню 👇",
        reply_markup=main_keyboard(subscribed)
    )


# ─── Entry point ─────────────────────────────────────────────────────────────

async def main():
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        daily_broadcast,
        "cron",
        hour=SEND_HOUR,
        minute=SEND_MINUTE
    )
    scheduler.start()
    logger.info(f"Scheduler started. Daily broadcast at {SEND_HOUR:02d}:{SEND_MINUTE:02d} MSK")

    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
