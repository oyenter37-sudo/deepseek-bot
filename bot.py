import asyncio
import logging
import time

from openai import AsyncOpenAI
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

# ================= КОНФИГУРАЦИЯ =================
TELEGRAM_TOKEN = "8849412275:AAGoCjOMVFg0W74FUGcgAsDwT2w_lbiAk40"
NVIDIA_API_KEY = "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"
MODEL_NAME = "deepseek-ai/deepseek-v4-flash-0731"
# ================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

client = AsyncOpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY,
)


async def stream_nvidia(prompt: str, message: Message):
    """
    Стримит ответ от NVIDIA API.
    Во время фазы reasoning обновляет сообщение '💭 Thinking: Xs' каждые 3 сек.
    После завершения — редактирует сообщение, показывая время и полный ответ.
    """
    thinking_msg: Message | None = None
    start_thinking_time: float | None = None
    last_edit_time: float = 0.0

    reasoning_text = ""
    content_text = ""
    is_thinking_phase = True

    try:
        stream = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
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

            # --- Фаза размышления (reasoning) ---
            reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
            if reasoning:
                if start_thinking_time is None:
                    start_thinking_time = time.monotonic()
                    # Отправляем начальное сообщение
                    thinking_msg = await message.answer("💭 Thinking: 0s")
                    last_edit_time = time.monotonic()

                reasoning_text += reasoning

                # Обновляем сообщение каждые 3 секунды
                now = time.monotonic()
                if now - last_edit_time >= 3.0 and thinking_msg:
                    elapsed = int(now - start_thinking_time)
                    try:
                        await thinking_msg.edit_text(f"💭 Thinking: {elapsed}s")
                    except Exception:
                        pass  # Сообщение могло быть удалено пользователем
                    last_edit_time = now

            # --- Фаза основного контента ---
            if delta.content:
                content_text += delta.content

                # Если мы были в фазе мышления и получили первый токен контента —
                # фиксируем финальное время и прекращаем обновлять thinking-сообщение
                if is_thinking_phase and start_thinking_time is not None:
                    is_thinking_phase = False
                    final_elapsed = int(time.monotonic() - start_thinking_time)
                    if thinking_msg:
                        try:
                            await thinking_msg.edit_text(f"💭 Thinking: {final_elapsed}s")
                        except Exception:
                            pass

    except Exception as e:
        logger.exception("Error during NVIDIA streaming")
        error_text = f"❌ Ошибка при генерации: {e}"
        if thinking_msg:
            try:
                await thinking_msg.edit_text(error_text)
            except Exception:
                await message.answer(error_text)
        else:
            await message.answer(error_text)
        return

    # --- Финальный ответ ---
    if not content_text.strip():
        content_text = "*(Модель не вернула текстовый ответ)*"

    # Формируем итоговое сообщение
    header = ""
    if start_thinking_time is not None:
        total_seconds = int(time.monotonic() - start_thinking_time)
        header = f"🧠 *Думал {total_seconds} сек.*\n\n"

    full_response = header + content_text

    # Telegram лимит 4096 символов
    if len(full_response) <= 4096:
        if thinking_msg:
            try:
                await thinking_msg.edit_text(full_response)
            except Exception:
                await message.answer(full_response)
        else:
            await message.answer(full_response)
    else:
        # Если ответ слишком длинный — редактируем thinking-сообщение заголовком,
        # а остальное отправляем отдельными сообщениями
        first_part = full_response[:4096]
        if thinking_msg:
            try:
                await thinking_msg.edit_text(first_part)
            except Exception:
                await message.answer(first_part)
        else:
            await message.answer(first_part)

        remainder = full_response[4096:]
        for i in range(0, len(remainder), 4096):
            await message.answer(remainder[i : i + 4096])


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я бот с ИИ DeepSeek (thinking mode).\n"
        "Напиши вопрос — я буду думать вслух и покажу процесс!"
    )


@dp.message(F.text)
async def handle_message(message: Message):
    await bot.send_chat_action(message.chat.id, "typing")
    await stream_nvidia(message.text, message)


async def main():
    logger.info("Бот запущен (streaming + thinking mode)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
