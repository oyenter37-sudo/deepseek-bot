import asyncio
import logging
import json

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import Message

# ================= КОНФИГУРАЦИЯ =================
TELEGRAM_TOKEN = "8849412275:AAGoCjOMVFg0W74FUGcgAsDwT2w_lbiAk40"
NVIDIA_API_KEY = "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"
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL_NAME = "deepseek-ai/deepseek-v4-flash-0731"
# ================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()


async def ask_nvidia(prompt: str) -> str:
    """Отправляет запрос к NVIDIA NIM API и возвращает ответ модели."""
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 1,
        "top_p": 0.95,
        "max_tokens": 16384,
        "chat_template_kwargs": {
            "thinking": False,
            "reasoning_effort": "none",
        },
        "stream": False,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(NVIDIA_API_URL, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"NVIDIA API error {resp.status}: {error_text}")
                    return f"❌ Ошибка API ({resp.status}). Попробуйте позже."
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
    except asyncio.TimeoutError:
        return "⏳ Таймаут: модель отвечала слишком долго."
    except Exception as e:
        logger.exception("Unexpected error calling NVIDIA API")
        return f"❌ Неизвестная ошибка: {e}"


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я бот с ИИ DeepSeek через NVIDIA API.\n"
        "Просто напиши мне сообщение, и я отвечу."
    )


@dp.message(F.text)
async def handle_message(message: Message):
    # Показываем индикатор «печатает...» пока ждём ответ от ИИ
    await bot.send_chat_action(message.chat.id, "typing")

    response = await ask_nvidia(message.text)

    # Telegram ограничивает длину сообщения 4096 символами
    if len(response) <= 4096:
        await message.answer(response)
    else:
        # Разбиваем длинный ответ на части
        for i in range(0, len(response), 4096):
            await message.answer(response[i : i + 4096])


async def main():
    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
