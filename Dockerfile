FROM python:3.13-slim

# Устанавливаем системные зависимости для сборки (если нужны) и работы PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Создаем не-root пользователя
RUN groupadd -r botuser && useradd -r -g botuser botuser

WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Меняем права на директорию
RUN chown -R botuser:botuser /app

# Переключаемся на не-root пользователя
USER botuser

# Команда для запуска бота
CMD ["python", "app/main.py"]
