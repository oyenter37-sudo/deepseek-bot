import asyncio
import io
import json
import logging
import os
import time
from collections import defaultdict

from openai import AsyncOpenAI
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ================= КОНФИГУРАЦИЯ =================
TELEGRAM_TOKEN = "8849412275:AAGoCjOMVFg0W74FUGcgAsDwT2w_lbiAk40"
NVIDIA_API_KEY = "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"
MODEL_NAME = "deepseek-ai/deepseek-v4-flash-0731"
DATA_FILE = "users_data.json"

SYSTEM_PROMPT = (
    "Ты - Claude opus 5. Тебя создала компания Anthropic. "
    "Ты - умный ии, который может писать код, отвечать на вопросы, и много чего еще. "
    "Ты: \"Claude\". Модель: Opus 5.\n\n"
    "ВАЖНО: Если пользователь просит создать файл, написать код в файле или сохранить что-то в файл, "
    "ты ДОЛЖЕН использовать следующий формат в своём ответе:\n"
    "[FILE:имя_файла.расширение]\nсодержимое файла\n[/FILE]\n\n"
    "Пример:\n[FILE:code.html]\n<!DOCTYPE html><html><body>Hello</body></html>[/FILE]\n\n"
    "Всегда отвечай на языке пользователя."
)
# ================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode="Markdown"))
dp = Dispatcher()

client = AsyncOpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY,
)

# --- Хранилища состояния ---
user_locks: dict[int, asyncio.Lock] = {}
user_histories: dict[int, list[dict]] = defaultdict(list)
user_stats: dict[int, int] = defaultdict(int)
processing_times: list[float] = []


def get_lock(uid: int) -> asyncio.Lock:
    """Безопасное получение лока для конкретного пользователя."""
    if uid not in user_locks:
        user_locks[uid] = asyncio.Lock()
    return user_locks[uid]


# ================= РАБОТА С ДАННЫМИ =================
def load_data():
    global user_stats, processing_times
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            user_stats.update(data.get("stats", {}))
            processing_times.extend(data.get("times", []))
        except Exception as e:
            logger.error(f"Failed to load data: {e}")


def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "stats": {str(k): v for k, v in user_stats.items()},
                "times": processing_times[-1000:],
            }, f)
    except Exception as e:
        logger.error(f"Failed to save data: {e}")


load_data()


# ================= КЛАВИАТУРЫ =================
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="🗑 Очистить диалог", callback_data="clear_history")],
    ])


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")],
    ])


# ================= ОБРАБОТЧИКИ КОМАНД И КНОПОК =================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    text = (
        "*🤖 Добро пожаловать!*\n\n"
        "Это бот с *бесплатным доступом* к новейшей модели *Claude 5 Opus*.\n\n"
        "✨ Возможности:\n"
        "• Умные ответы на любые вопросы\n"
        "• Написание кода и создание файлов\n"
        "• Сохранение истории диалога\n"
        "• Режим размышления (thinking)\n\n"
        "Напиши сообщение или воспользуйся меню ниже 👇"
    )
    await message.answer(text, reply_markup=main_menu_kb())


@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    text = (
        "*🤖 Главное меню*\n\n"
        "Это бот с *бесплатным доступом* к новейшей модели *Claude 5 Opus*.\n\n"
        "Напиши сообщение или воспользуйся кнопками 👇"
    )
    await callback.message.edit_text(text, reply_markup=main_menu_kb())
    await callback.answer()


@dp.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    uid = callback.from_user.id
    requests_count = user_stats.get(str(uid), user_stats.get(uid, 0))
    text = (
        "*👤 Профиль*\n\n"
        f"*Telegram ID:* `{uid}`\n"
        f"*Запросов сделано:* `{requests_count}`\n"
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
    await callback.answer()


@dp.callback_query(F.data == "clear_history")
async def cb_clear_history(callback: CallbackQuery):
    uid = callback.from_user.id
    user_histories.pop(uid, None)
    await callback.message.edit_text(
        "*✅ Диалог очищен!*\n\nМожешь начать новый разговор.",
        reply_markup=back_to_menu_kb(),
    )
    await callback.answer("История удалена")


# ================= ПАРСИНГ ФАЙЛОВ ИЗ ОТВЕТА =================
def extract_files(text: str) -> tuple[str, list[tuple[str, str]]]:
    files = []
    clean_parts = []
    remaining = text

    while True:
        start_tag = "[FILE:"
        end_tag = "[/FILE]"
        s = remaining.find(start_tag)
        if s == -1:
            clean_parts.append(remaining)
            break
        e = remaining.find(end_tag, s)
        if e == -1:
            clean_parts.append(remaining)
            break

        clean_parts.append(remaining[:s])
        filename_end = remaining.find("]", s + len(start_tag))
        if filename_end == -1 or filename_end > e:
            clean_parts.append(remaining[s:])
            break

        filename = remaining[s + len(start_tag):filename_end].strip()
        content = remaining[filename_end + 1:e]
        files.append((filename, content))
        remaining = remaining[e + len(end_tag):]

    clean_text = "".join(clean_parts).strip()
    return clean_text, files


# ================= СТРИМИНГ NVIDIA =================
async def stream_nvidia(prompt: str, history: list[dict], message: Message, uid: int):
    status_msg: Message | None = None
    start_thinking_time: float | None = None
    last_edit_time: float = 0.0

    content_text = ""
    is_thinking_phase = True
    first_token_received = False

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [{"role": "user", "content": prompt}]

    # 1. Сразу показываем сообщение об очереди/ожидании подключения
    status_msg = await message.answer(
        "⏳ *Твой запрос находится в очереди!*\n"
        "✨ *Подключение к API...*"
    )

    try:
        # 2. Сразу подключаемся к API (стрим начинается)
        stream = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=1,
            top_p=0.95,
            max_tokens=16384,
            extra_body={
                "chat_template_kwargs": {
                    "thinking": True,
                    "reasoning_effort": "high",
                }
            },
            stream=True,
        )

        async for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta

            # --- Фаза reasoning ---
            reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
            if reasoning:
                # Пришёл первый токен размышления!
                if not first_token_received:
                    first_token_received = True
                    start_thinking_time = time.monotonic()
                    last_edit_time = time.monotonic()
                    
                    # Заменяем "В очереди" на "Thinking"
                    if status_msg:
                        try:
                            await status_msg.edit_text("💭 *Thinking: 0s*")
                        except Exception:
                            status_msg = await message.answer("💭 *Thinking: 0s*")

                now = time.monotonic()
                # Обновляем таймер каждые 3 секунды
                if now - last_edit_time >= 3.0 and status_msg:
                    elapsed = int(now - start_thinking_time)
                    try:
                        await status_msg.edit_text(f"💭 *Thinking: {elapsed}s*")
                    except Exception:
                        pass
                    last_edit_time = now

            # --- Фаза контента ---
            if delta.content:
                # Если контента нет, но пришёл текст (модель пропустила reasoning)
                if not first_token_received:
                    first_token_received = True
                    start_thinking_time = time.monotonic()
                    if status_msg:
                        try:
                            await status_msg.delete()
                        except Exception:
                            pass
                        status_msg = None

                content_text += delta.content
                
                if is_thinking_phase and start_thinking_time is not None:
                    is_thinking_phase = False
                    final_elapsed = int(time.monotonic() - start_thinking_time)
                    if status_msg:
                        try:
                            await status_msg.edit_text(f"💭 *Thinking: {final_elapsed}s*")
                        except Exception:
                            pass

    except Exception as e:
        logger.exception("Streaming error")
        err = f"*❌ Ошибка генерации:* `{e}`"
        if status_msg:
            try:
                await status_msg.edit_text(err)
            except Exception:
                await message.answer(err)
        else:
            await message.answer(err)
        return

    # Записываем время обработки
    if start_thinking_time:
        processing_times.append(time.monotonic() - start_thinking_time)
        save_data()

    # Парсим файлы
    clean_text, files = extract_files(content_text)

    # Добавляем в историю
    history.append({"role": "user", "content": prompt})
    history.append({"role": "assistant", "content": content_text})
    user_stats[str(uid)] = user_stats.get(str(uid), 0) + 1
    save_data()

    # Формируем финальный ответ
    header = ""
    if start_thinking_time is not None:
        total_sec = int(time.monotonic() - start_thinking_time)
        header = f"🧠 *Думал {total_sec} сек.*\n\n"

    final_text = header + clean_text if clean_text else header + "_Нет текстового ответа_"

    # Отправляем / редактируем основное сообщение
    if len(final_text) <= 4096:
        if status_msg:
            try:
                await status_msg.edit_text(final_text)
            except Exception:
                await message.answer(final_text)
        else:
            await message.answer(final_text)
    else:
        first = final_text[:4096]
        if status_msg:
            try:
                await status_msg.edit_text(first)
            except Exception:
                await message.answer(first)
        else:
            await message.answer(first)
        rest = final_text[4096:]
        for i in range(0, len(rest), 4096):
            await message.answer(rest[i:i + 4096])

    # Отправляем файлы
    for filename, content in files:
        buf = io.BytesIO(content.encode("utf-8"))
        doc = BufferedInputFile(buf.read(), filename=filename)
        await message.answer_document(doc, caption=f"📎 *{filename}*")


# ================= ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ =================
@dp.message(F.text)
async def handle_message(message: Message):
    uid = message.from_user.id
    lock = get_lock(uid)

    # Если лок занят — значит стрим уже идёт, пишем про очередь
    if lock.locked():
        avg = sum(processing_times) / len(processing_times) if processing_times else 15
        await message.answer(
            f"⏳ *Твой запрос находится в очереди!*\n"
            f"✨ *Среднее время ожидания:* `{avg:.0f}` сек.",
        )
        return

    # Блокируем новые сообщения для этого юзера, пока не закончится стрим
    async with lock:
        await bot.send_chat_action(message.chat.id, "typing")
        history = user_histories[uid]
        await stream_nvidia(message.text, history, message, uid)


async def main():
    logger.info("Бот запущен (queue + thinking + files + history)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
