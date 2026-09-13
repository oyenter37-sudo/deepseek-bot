import asyncio
import logging
import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import Message

# --- КОНФИГУРАЦИЯ (ТОКЕНЫ В КОДЕ) ---
TELEGRAM_TOKEN = "8849412275:AAGoCjOMVFg0W74FUGcgAsDwT2w_lbiAk40"
NVIDIA_API_KEY = "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"
NVIDIA_MODEL = "deepseek-ai/deepseek-v4-flash-0731"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()


async def get_ai_response(user_message: str) -> str:
    """Отправляет запрос к NVIDIA API и возвращает ответ."""
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": NVIDIA_MODEL,
        "messages": [{"role": "user", "content": user_message}],
        "temperature": 1,
        "top_p": 0.95,
        "max_tokens": 16384,
        "chat_template_kwargs": {
            "thinking": False,
            "reasoning_effort": "none"
        },
        "stream": False
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(NVIDIA_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Ошибка при запросе к NVIDIA API: {e}")
        return f"⚠️ Ошибка при обращении к ИИ: {str(e)}"


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Привет! Отправь мне сообщение, и я передам его нейросети DeepSeek.")


@dp.message()
async def handle_message(message: Message):
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовое сообщение.")
        return

    # Показываем статус "печатает..." пока ждем ответа от ИИ
    await bot.send_chat_action(message.chat.id, "typing")
    
    ai_reply = await get_ai_response(message.text)
    await message.answer(ai_reply)


async def main():
    logger.info("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
