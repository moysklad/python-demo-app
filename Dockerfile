# syntax=docker/dockerfile:1.7

# Собираем основной iframe (React + @moysklad/uikit) из frontend/ в static/assets/app
FROM node:24-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN NODE_ENV=production npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    DATA_DIR=/app/tmp/data \
    APP_DB_PATH=/app/tmp/data/app.sqlite

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app \
    && install -d -m 700 -o app -g app /app/tmp/data

COPY pyproject.toml README.md ./
COPY app ./app
COPY templates ./templates
COPY static ./static
COPY --from=frontend /app/static/assets/app ./static/assets/app

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir .

USER app

EXPOSE 8080

VOLUME ["/app/tmp/data"]

CMD ["sh", "-c", "exec gunicorn 'app:create_app()' --bind 0.0.0.0:${PORT} --threads ${GUNICORN_THREADS:-5}"]
