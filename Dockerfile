FROM python:3.13-slim

ENV TZ=America/Los_Angeles
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && ln -fs /usr/share/zoneinfo/$TZ /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY weather.py watering_logic.py bot.py ./

CMD ["python", "bot.py"]
