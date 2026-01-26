FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Poetry
RUN pip install --no-cache-dir poetry

# Copy dependency files first for better Docker caching
COPY pyproject.toml poetry.lock* /app/

# Install dependencies into the container (no venv in container)
RUN poetry config virtualenvs.create false \
 && poetry install --no-interaction --no-ansi

# Copy the Django project
COPY src/ /app/src
RUN echo "==== /app/src contents ====" && ls -la /app/src && echo "==== find scripts ====" && find /app/src -maxdepth 3 -type d -name scripts -print

WORKDIR /app/src

# Start the web service
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000}"]
