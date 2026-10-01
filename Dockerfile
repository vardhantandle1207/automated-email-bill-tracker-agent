FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --create-home app && chown -R app /app
USER app

# Cloud Run injects PORT (default 8080). Secrets come from env vars / Secret Manager mounts, never the image.
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
