FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN uv pip install --system .

EXPOSE 8000

CMD ["uvicorn", "uteki_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
