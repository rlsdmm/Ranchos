FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# O Cloud Run informa a porta em $PORT. Timeout vem do gunicorn.conf.py.
CMD exec gunicorn -w 2 --threads 4 -b 0.0.0.0:${PORT:-8080} app:app
