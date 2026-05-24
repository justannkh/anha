FROM python:3.11-slim

WORKDIR /app

# Зависимости отдельным слоем (кэшируются при пересборке)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY . .

# Директория для БД (можно примонтировать volume)
RUN mkdir -p /app/data
ENV DB_PATH=/app/data/bot.db

CMD ["python", "main.py"]
