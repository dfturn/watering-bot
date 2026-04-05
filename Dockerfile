FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY weather.py watering_logic.py bot.py ./

CMD ["python", "bot.py"]
