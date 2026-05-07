# Демо-приложение на Python для каталога решений МоегоСклада

Данное демо показывает основные способы взаимодействия решения с МоимСкладом по протоколу Vendor API. По функциональности оно повторяет Node.js пример из `/home/rlusnikov/repos/node-js-demo-app`, но реализовано на Flask.

В демо-приложении реализованы:
- Активация и деактивация решения через Vendor API
- Генерация `descriptor.xml` для публикации в каталоге
- Отображение iframe-страницы настроек решения
- Получение контекста пользователя для iframe/виджетов с кешированием в server-side сессии
- Сохранение настроек решения и обновление статуса во внешнем Vendor API
- Получение данных из JSON API 1.2 по токену установки
- Встраивание виджетов в Заказ покупателя и Счет покупателю
- Обработка кастомных кнопок в документе и списке Заказов покупателя
- Открытие кастомного popup из виджета и кнопки

ВНИМАНИЕ! Проект является демонстрационным. Вопросы production-hardening (полноценный мониторинг, отказоустойчивость, строгая политика хранения секретов, rate-limit защита) не являются целью данного репозитория.

## Быстрый старт

Порты:
- локальная разработка — `http://localhost:3000`
- Docker — `http://localhost:8085` при маппинге `8085:3000`

Локальный запуск:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m app
```

Проверка:

```bash
curl -sS http://localhost:3000/health
```

Production-режим локально:

```bash
gunicorn "app:create_app()" --bind 0.0.0.0:3000
```

Docker:

```bash
docker build -t python-demo-app:local .
docker run --rm -p 8085:3000 --env-file .env python-demo-app:local
```

## Конфигурация

Ключевые переменные окружения:
- `PORT` — порт, который слушает процесс внутри контейнера/локального процесса.
- `APP_BASE_URL` — публичный внешний URL приложения, который попадает в `descriptor.xml`.
- `APP_ID`, `APP_UID`, `APP_SECRET_KEY` — идентификаторы и секрет приложения Marketplace.
- `APP_ENCRYPT_KEY` — ключ шифрования чувствительных полей в SQLite, ровно 64 hex-символа.
- `SESSION_SECRET` — секрет подписи server-side сессии.
- `APP_DB_PATH` — путь к SQLite-файлу с состоянием приложения, server-side сессиями и replay-маркерами JWT.
- `TRUST_PROXY` — включает учет `X-Forwarded-*` через `ProxyFix`; локально без proxy можно ставить `0`.

Полный список runtime-переменных:
- `APP_ID` (`required`)
- `APP_UID` (`required`)
- `APP_SECRET_KEY` (`required`)
- `APP_ENCRYPT_KEY` (`required`)
- `APP_BASE_URL` (`required`)
- `SESSION_SECRET` (`required`)
- `PORT` (`optional`, default: `3000`)
- `LOG_LEVEL` (`optional`, default: `DEBUG`)
- `MOYSKLAD_VENDOR_API_ENDPOINT_URL` (`optional`, default: `https://apps-api.moysklad.ru/api/vendor/1.0`)
- `MOYSKLAD_JSON_API_ENDPOINT_URL` (`optional`, default: `https://api.moysklad.ru/api/remap/1.2`)
- `SESSION_COOKIE_SECURE` (`optional`, default: `true`)
- `SESSION_COOKIE_SAME_SITE` (`optional`, default: `none`)
- `SESSION_NAME` (`optional`, default: `connect.sid`)
- `TRUST_PROXY` (`optional`, default: `1`)
- `DATA_DIR` (`optional`, default: `./tmp/data`)
- `APP_DB_PATH` (`optional`, default: `./tmp/data/app.sqlite`)

Для локального HTTP удобно использовать:

```env
SESSION_COOKIE_SECURE=false
SESSION_COOKIE_SAME_SITE=lax
TRUST_PROXY=0
```

## Архитектурное правило

Flask views являются тонкими адаптерами request/response. Бизнес-логика живет в `app/services`, хранение состояния в `app/repositories`, интеграции с внешними API в `app/integrations`. Jinja templates получают готовые view models и только отображают данные.

Такая структура оставляет путь к FastAPI: services и repositories не зависят от Flask globals, а HTTP-слой можно заменить адаптерами FastAPI.

## CLI утилиты

- `python -m app.cli.generate_descriptor` — выводит `descriptor.xml` в stdout.
- `python -m app.cli.generate_jwt` — выводит service JWT для вызовов Vendor API.

## Основные HTTP routes

Service routes:
- `GET /health`
- `GET /descriptor.xml`

Entry routes:
- `GET /entry/iframe?contextKey=...`
- `GET /entry/widget-customerorder?contextKey=...`
- `GET /entry/widget-invoiceout?contextKey=...`
- `GET /entry/popup`

Backend utility routes:
- `POST /utils/update-settings`
- `GET /utils/get-object?entity=...&contextKey=...&objectId=...`

Vendor endpoint routes:
- `PUT /vendor-endpoint/api/moysklad/vendor/1.0/apps/<appId>/<accountId>`
- `DELETE /vendor-endpoint/api/moysklad/vendor/1.0/apps/<appId>/<accountId>`
- `PUT /vendor-endpoint/api/moysklad/vendor/1.0/apps/<appId>/<accountId>/event`
- `POST /vendor-endpoint/api/moysklad/vendor/1.0/apps/<appId>/<accountId>/button`

## Хранение состояния

Runtime-состояние хранится в SQLite-файле `APP_DB_PATH`:
- `account_application` — состояние установки по паре `appId`/`accountId`.
- `sessions` — server-side сессии Flask.
- `jwt` — replay-маркеры service JWT `jti` до истечения `exp`.

Access token и session payload сохраняются в базе в зашифрованном виде через `APP_ENCRYPT_KEY`. При смене ключа уже сохраненные данные не смогут расшифроваться.

## Проверки

```bash
python -m compileall app tests
pytest
```
