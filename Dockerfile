FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# requirements first, so this layer is cached when only the code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --create-home app && chown -R app /app
USER app

# Cloud Run sets PORT. Secrets come in as environment variables, never in the image.
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
