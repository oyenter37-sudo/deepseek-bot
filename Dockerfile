FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей
RUN pip install --no-cache-dir aiogram httpx

# Копирование кода бота
COPY bot.py .

# Запуск бота
CMD ["python", "bot.py"]
