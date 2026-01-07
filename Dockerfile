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
COPY src /app/src

WORKDIR /app/src
