# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=9082 \
    DATA_DIR=/app/tmp/data \
    APP_DB_PATH=/app/tmp/data/app.sqlite

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app \
    && install -d -m 700 -o app -g app /app/tmp/data

COPY pyproject.toml README.md ./
COPY app ./app
COPY templates ./templates
COPY static ./static

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir .

USER app

EXPOSE 9082

VOLUME ["/app/tmp/data"]

CMD ["sh", "-c", "gunicorn 'app:create_app()' --bind 0.0.0.0:${PORT}"]
