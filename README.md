# Демо-приложение на Python для каталога решений МоегоСклада

Данное демо реализовано на Flask и показывает основные способы взаимодействия решения с МоимСкладом по протоколу Vendor API. 

В демо-приложении реализованы:
- Активация и деактивация решения через Vendor API
- Генерация `descriptor.xml` для публикации в каталоге
- Отображение iframe-страницы настроек решения
- Получение контекста пользователя для iframe/виджетов с кешированием в server-side сессии
- Сохранение настроек решения и обновление статуса во внешнем Vendor API
- Получение данных из JSON API 1.2 по токену установки
- Встраивание виджетов в Заказ покупателя и Счет покупателю
- Обработка кастомных кнопок в документе и списке Заказов покупателя
- Открытие кастомного модального окна из виджета и кнопки

ВНИМАНИЕ! Проект является демонстрационным. Вопросы связанные с эксплуатацией на production: 
полноценный мониторинг, отказоустойчивость, строгая политика хранения секретов, rate-limit защита, не являются целью данного репозитория.

## Быстрый старт

Настройка локальной среды и запуск:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m app
```

Либо запустите решение в Docker:

```bash
docker build -t python-demo-app:local .
docker run --rm -p 8080:8080 --env-file .env python-demo-app:local
```

Проверка:

```bash
curl -sS http://localhost:8080/health
```

Генерация дескриптора решения:

```bash
python -m app.cli.generate_descriptor
```

## Конфигурация

Ключевые переменные окружения:
- `PORT` — порт, который слушает процесс внутри контейнера/локального процесса.
- `APP_BASE_URL` — публичный внешний URL приложения, который попадает в `descriptor.xml`.
- `APP_ID`, `APP_UID`, `APP_SECRET_KEY` — параметры идентификации решения из личного кабинета.
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
- `PORT` (`optional`, default: `8080`)
- `LOG_LEVEL` (`optional`, default: `DEBUG`)
- `MOYSKLAD_VENDOR_API_ENDPOINT_URL` (`optional`, default: `https://apps-api.moysklad.ru/api/vendor/1.0`)
- `MOYSKLAD_JSON_API_ENDPOINT_URL` (`optional`, default: `https://api.moysklad.ru/api/remap/1.2`)
- `SESSION_COOKIE_SECURE` (`optional`, default: `true`)
- `SESSION_COOKIE_SAME_SITE` (`optional`, default: `none`)
- `SESSION_NAME` (`optional`, default: `connect.sid`)
- `TRUST_PROXY` (`optional`, default: `1`)
- `DATA_DIR` (`optional`, default: `./tmp/data`)
- `APP_DB_PATH` (`optional`, default: `./tmp/data/app.sqlite`)

## CLI утилиты

- `python -m app.cli.generate_descriptor` — выводит `descriptor.xml` в stdout.
- `python -m app.cli.generate_jwt` — выводит service JWT для вызовов Vendor API.

## Основные HTTP эндпоинты

Сервисные:
- `GET /health` — проверка статуса: процесс запущен и готов к работе

Окна и виджеты:
- `GET /entry/iframe?contextKey=...`
- `GET /entry/widget-customerorder?contextKey=...`
- `GET /entry/widget-invoiceout?contextKey=...`
- `GET /entry/popup`

Backend-запросы из iframe/виджетов:
- `POST /utils/update-settings` — сохранение настроек из iframe, требует `contextNonce`
- `POST /utils/get-object?entity=...` — получение открытого объекта для виджета, параметры `contextNonce` и `objectId` передаются в теле запроса

Vendor API:
- `PUT /api/moysklad/vendor/1.0/apps/<appId>/<accountId>`
- `DELETE /api/moysklad/vendor/1.0/apps/<appId>/<accountId>`
- `PUT /api/moysklad/vendor/1.0/apps/<appId>/<accountId>/event`
- `POST /api/moysklad/vendor/1.0/apps/<appId>/<accountId>/button`

## Хранение состояния

Runtime-состояние хранится в SQLite-файле `APP_DB_PATH` в таблицах:
- `account_application` — состояние установки по паре `appId`/`accountId`: сообщение настроек, выбранный склад, access token, статус и дату обновления.
- `sessions` — server-side сессии Flask.
- `jwt` — replay-маркеры service JWT `jti` до истечения `exp`.

Access token и session payload сохраняются в базе в зашифрованном виде через `APP_ENCRYPT_KEY`. При смене ключа уже сохраненные данные не смогут расшифроваться.

SQLite-хранилища работают через SQLAlchemy. Приложение использует общий набор соединений; на время операции берется свободное соединение, а ожидание ограничено 5 секундами.

## Работа с контекстом пользователя

`contextKey` — это opaque-token, который МойСклад передает в URL iframe/виджета при открытии страницы. Приложение не должно разбирать его содержимое или использовать как постоянный идентификатор пользователя.

Последовательность работы:
- Хост-окно открывает `GET /entry/iframe?contextKey=...` или `GET /entry/widget-...?contextKey=...`.
- Приложение обращается к Vendor API, чтобы получить `uid`, `accountId` и права пользователя.
- Приложение сохраняет в server-side сессии активный контекст пользователя: `uid`, `accountId`, `fio`, `isAdmin`, `contextNonce`, `createdAt`, `expiresAt`.
- Исходный `contextKey` в сессии не хранится и больше не используется. В шаблоны iframe/виджета передается только `contextNonce`.
- Запросы из iframe/виджета (`POST /utils/update-settings`, `POST /utils/get-object`) передают `contextNonce`.
- Backend принимает запрос только если `contextNonce` совпадает с активным контекстом в текущей сессии. Если `contextNonce` отсутствует, устарел или не совпал, возвращается `401`.

Когда меняется `contextNonce`:
- Если повторно открыть iframe/виджет для того же `uid`, `accountId` и `isAdmin`, то `contextNonce` переиспользуется.
- Если изменился пользователь, аккаунт или признак администратора, `contextNonce` обновляется.

Когда завершается сессия:
- Исходное время жизни сессии (TTL) равно 2 часам (константа USER_CONTEXT_SESSION_TTL_SECONDS).
- TTL скользящий: пока iframe/виджет делает backend-запросы, сессия продлевается. Если пользователь не совершает никаких действий в течение TTL, то сессия завершается.

## Структура проекта

Основные entrypoints:
- `app/__main__.py` — запуск локального HTTP-сервера через `python -m app`
- `app/factory.py` — создание Flask-приложения, настройка middleware, repositories и services
- `app/web/routes.py` — регистрация HTTP routes и адаптация request/response к services

API и интеграции:
- `app/services/vendor_endpoint.py` — обработка lifecycle событий и button callbacks
- `app/services/buttons.py` — формирование action-ответов для кнопок
- `app/integrations/vendor_api.py` — клиент Vendor API (context/status)
- `app/integrations/json_api.py` — клиент JSON API 1.2

UI и entry:
- `templates/entry/*` — Jinja-шаблоны iframe/widget/popup страниц
- `static/assets/entry/*` — фронтенд-стили/скрипты
- `app/services/entry.py` — подготовка view models для entry-страниц

Состояние и безопасность:
- `app/domain/app_instance.py` — модель состояния установки приложения
- `app/repositories/sqlite.py` — SQLite-хранение установок, server-side сессий и replay-маркеров JWT
- `app/services/user_context.py` — bootstrap user context по `contextKey` и проверка backend-запросов по `contextNonce`
- `app/security/crypto.py` — утилиты шифрования чувствительных данных
- `app/security/jwt_tools.py` — генерация и проверка service JWT

Утилиты:
- `app/services/descriptor.py` — генерация `descriptor.xml`
- `app/services/utils.py` — backend endpoints настроек и чтения объектов
- `app/config.py` — загрузка и валидация runtime config из окружения/`.env`

CLI-утилиты:
- `app/cli/generate_jwt.py` — генерация service JWT для вызовов Vendor API.
- `app/cli/generate_descriptor.py` — генерация `descriptor.xml` в stdout.

## Запуск тестов

Проект включает в себя базовый набор проверок поведения. 
Для запуска тестов выполните команды:

```bash
python -m compileall app tests
pytest
```

## Создание черновика решения в личном кабинете

Перейдите в личный кабинет в раздел Решения https://apps.moysklad.ru/cabinet/application

Нажмите кнопку `Создать решение` и заполните необходимые поля. В качестве дескриптора можно использовать заглушку вида:

```xml
<ServerApplication xsi:schemaLocation="https://apps-api.moysklad.ru/xml/ns/appstore/app/v2 https://apps-api.moysklad.ru/xml/ns/appstore/app/v2/application-v2.xsd" xmlns="https://apps-api.moysklad.ru/xml/ns/appstore/app/v2" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <access>
        <resource>https://online.moysklad.ru/api/remap/1.2</resource>
        <scope>admin</scope>
    </access>
    <vendorApi>
        <endpointBase>https://example.com/vendor</endpointBase>
    </vendorApi>
</ServerApplication>
```

Сохраните черновик и скопируйте значения `APP_ID`, `APP_UID`, `APP_SECRET_KEY` с вкладки Учетные данные в .env файл.

## Отладка черновика через cloudflared

Скачайте и установите последнюю версию клиента https://github.com/cloudflare/cloudflared

Создайте Quick Tunnel, выполнив в отдельном терминале 

```bash
cloudflared tunnel --protocol http2 --edge-ip-version 4 --url http://localhost:8080
```

Сохраните выданный временный адрес в переменной `APP_BASE_URL` в .env файле. Пример: 

```
APP_BASE_URL=https://gateway-mazda-titled-easy.trycloudflare.com 
```

Сгенерируйте дескриптор через `app.cli.generate_descriptor` и сохраните его в личном кабинете в карточке черновика.

После этого можно устанавливать и отлаживать решение в каталоге МоегоСклада, перейдя по адресу `https://online.moysklad.ru/app/#apps?id=<APP_ID>`.