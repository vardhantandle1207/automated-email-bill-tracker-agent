# CONCEPT 9: DEPLOYMENT. This file packs the agent into a container that runs anywhere.

# Step 1: Start from a small Python image.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Step 2: Install the libraries.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Step 3: Copy the code and run as a normal user, not as root.
COPY . .
RUN useradd --create-home app && chown -R app /app
USER app

# Step 4: Start the web service. The host tells us the port (default 8080).
#         Secrets such as GEMINI_API_KEY are passed in as environment variables, never baked in.
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
