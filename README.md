# Демо-приложение на Python для каталога решений МоегоСклада

Данное демо реализовано на Flask и показывает основные способы взаимодействия решения с МоимСкладом по протоколу Vendor API. 

В демо-приложении реализованы:
- Активация и деактивация решения через Vendor API
- Генерация `descriptor.xml` для публикации в каталоге
- Основной iframe на React и `@moysklad/uikit`: настройки решения, программа лояльности, примеры UI Kit
- Окно чатов на том же протоколе контекста пользователя: состояние решения и журнал действий из сценариев
- Обработка действий из сценариев МоегоСклада (модуль `app/scenario`, см. [README](app/scenario/README.md))
- Отображение мобильной iframe-страницы для проверки возможностей WebView
- Получение контекста пользователя для iframe/виджетов по одноразовому токену из JS Widget SDK с кешированием в server-side сессии
- Сохранение настроек решения и обновление статуса во внешнем Vendor API
- Сохранение пользовательских настроек при приостановке и удалении решения с восстановлением при возобновлении и повторной установке
- Получение данных из JSON API 1.2 по токену установки
- Проверка обработки `X-Lognex-Retry-After` серией запросов к JSON API 1.2
- Встраивание виджетов в Заказ покупателя и Счет покупателю
- Обработка кастомных кнопок в документе и списке Заказов покупателя
- Открытие кастомного модального окна из виджета и кнопки
- Подключение программы лояльности через Vendor API и заглушка провайдера Loyalty API (модуль `app/loyalty`, см. [README](app/loyalty/README.md))

ВНИМАНИЕ! Проект является демонстрационным. Вопросы связанные с эксплуатацией на production: 
полноценный мониторинг, отказоустойчивость, строгая политика хранения секретов, rate-limit защита, не являются целью данного репозитория.

## Быстрый старт

Настройка локальной среды и запуск:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
(cd frontend && npm ci && npm run build)
python -m app
```

Основной iframe собирается из `frontend/` (Node.js 24) в `static/assets/app`. При правках фронта
держите запущенной пересборку: `cd frontend && npm run watch`.

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
- `GUNICORN_THREADS` (`optional`, default: `5`; JSON API разрешает не более 5 параллельных запросов от пользователя, поэтому число потоков ограничивает и параллельность обращений к API)
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
- `GET /entry/iframe-main`
- `GET /entry/iframe-chat`
- `GET /entry/iframe-mobile?contextKey=...`
- `GET /entry/widget-customerorder`
- `GET /entry/widget-invoiceout`
- `GET /entry/popup`
- `POST /entry/user-context` — принимает одноразовый токен только в JSON body и поднимает server-side сессию

Backend-запросы из iframe/виджетов:
- `POST /utils/update-settings` — сохранение настроек из iframe, требует `contextNonce`
- `POST /utils/get-object?entity=...` — получение открытого объекта для виджета, параметры `contextNonce` и `objectId` передаются в теле запроса
- `POST /utils/stores` — один запрос списка складов с количеством ретраев; iframe вызывает endpoint от 1 до 1000 раз, требуется право администратора и `contextNonce`
- `POST /utils/connect-loyalty` — передача настроек Loyalty API в МойСклад, требуется право администратора и `contextNonce`
- `POST /utils/scenario-events` — журнал действий из сценариев для окна чатов, требует `contextNonce`

Loyalty API (вызывает МойСклад, авторизация по заголовку `Lognex-Discount-API-Auth-Token`):
- `POST /loyalty/counterparty`, `GET /loyalty/counterparty?search=...`, `POST /loyalty/counterparty/detail`
- `POST /loyalty/retaildemand/recalc`, `POST /loyalty/retaildemand`, `POST /loyalty/retailsalesreturn`

Vendor API:
- `PUT /api/moysklad/vendor/1.0/apps/<appId>/<accountId>`
- `DELETE /api/moysklad/vendor/1.0/apps/<appId>/<accountId>`
- `PUT /api/moysklad/vendor/1.0/apps/<appId>/<accountId>/event`
- `POST /api/moysklad/vendor/1.0/apps/<appId>/<accountId>/button`
- `POST /api/moysklad/vendor/1.0/apps/<appId>/<accountId>/scenario`

## Хранение состояния

Runtime-состояние хранится в SQLite-файле `APP_DB_PATH` в таблицах:
- `account_application` — состояние установки по паре `appId`/`accountId`: сообщение настроек, выбранный склад, access token, статус и дату обновления.
- `sessions` — server-side сессии Flask.
- `jwt` — replay-маркеры service JWT `jti` до истечения `exp`.
- `loyalty_installation` — подключение программы лояльности: токен провайдера, режим внешнего поиска и момент, когда МойСклад принял настройки.
- `scenario_event` — последние 50 срабатываний действий из сценариев на аккаунт: действие, тип события, объект и ответ решения.

Access token, токен провайдера лояльности и session payload сохраняются в базе в зашифрованном виде через `APP_ENCRYPT_KEY`. При смене ключа уже сохраненные данные не смогут расшифроваться.

SQLite-хранилища работают через SQLAlchemy. Приложение использует общий набор соединений; на время операции берется свободное соединение, а ожидание ограничено 5 секундами.

## Сохранение пользовательских настроек

Демо сохраняет настройки установки (`info_message`, `store`) и при приостановке решения, и при его удалении с аккаунта — чтобы пользователю не приходилось настраивать решение заново.

| Событие Vendor API | Что делает демо | Статус установки |
|---|---|---|
| `DELETE cause=Suspend` | останавливает работу решения, стирает access token, настройки оставляет | `SUSPENDED` |
| `PUT cause=Resume` | сохраняет новый access token и продолжает работу с прежней конфигурацией | `ACTIVATED`, если настройки на месте, иначе `SETTINGS_REQUIRED` |
| `DELETE cause=Uninstall` | помечает установку удаленной, стирает access token, настройки оставляет | `UNINSTALLED` |
| `PUT cause=Install` | восстанавливает сохраненные настройки предыдущей установки | `ACTIVATED`, если настройки на месте, иначе `SETTINGS_REQUIRED` |

Приостановка (`Suspend`) — временное состояние, не равнозначное удалению, поэтому статус `SettingsRequired` при возобновлении возвращается только тогда, когда пользователю действительно нужно перенастроить решение.

Сохранение настроек при удалении (`Uninstall`) — рекомендация, а не требование. Если политика хранения данных требует удалять данные установки при отключении решения, вызовите в обработчике `Uninstall` метод `AppInstanceRepository.delete()` вместо `uninstall()` — он полностью удаляет строку установки (`app/services/vendor_endpoint.py`, `app/repositories/sqlite.py`).

Повторный `DELETE` идемпотентен: `204 No Content`, если состояние уже соответствует запросу. Первый `Suspend` и `Uninstall` (в том числе после `Suspend`) возвращают `200`, потому что статус установки меняется. Неизвестный `cause` — `400`.

## Работа с контекстом пользователя

Основной iframe, окно чатов и виджеты используют протокол `user-context`: в дескрипторе у них указаны
`<uses><user-context/></uses>` и атрибут `useContextKey="false"`, поэтому МойСклад не передает `contextKey` в URL.

Последовательность работы:
- Хост-окно открывает `GET /entry/iframe-main`, `GET /entry/iframe-chat` или `GET /entry/widget-...` без параметров. Страница отдается без персональных данных.
- После загрузки браузер вызывает `requestUserContextToken()` из `@moysklad/js-widget-sdk` (версия 1.3.0 и новее).
- Одноразовый opaque-токен немедленно помещается в JSON body `{ "token": "..." }` запроса `POST /entry/user-context`. Токен нигде не отображается, браузерная переменная очищается сразу после создания запроса.
- Backend вызывает `POST {MOYSKLAD_VENDOR_API_ENDPOINT_URL}/context/user` под service JWT. Тело этого запроса в логи не пишется.
- Zeus возвращает `{accountId, userId, userUid, role}`. Известные роли: `admin`, `cashier`, `worker`, `individual`. Неизвестная роль не ломает обмен: пользователь считается не-админом.
- Backend сохраняет в server-side сессии активный контекст пользователя: `uid`, `accountId`, `fio`, `isAdmin`, `contextNonce`, `createdAt`, `expiresAt` и возвращает UI контекст пользователя, `contextNonce` и данные страницы для основного iframe (`"page": "iframe"` в запросе) или окна чатов (`"page": "chat"`). Токен не сохраняется и не возвращается.
- Запросы из iframe/виджета (`POST /utils/update-settings`, `POST /utils/get-object`, `POST /utils/stores`, `POST /utils/scenario-events`) передают `contextNonce`.
- Backend принимает запрос только если `contextNonce` совпадает с активным контекстом в текущей сессии. Если `contextNonce` отсутствует, устарел или не совпал, возвращается `401`.

`isAdmin` равен `true` только для роли `admin`. ФИО в новом ответе Vendor API нет, поэтому в интерфейсе показывается `uid`.

Ошибки Zeus передаются в UI без тела ответа и без токена: сохраняется HTTP-статус и код ошибки, если он есть. `401` от Zeus (битый service JWT) отдается клиенту как `502`, чтобы не смешивать ошибку решения с ошибкой пользователя. Виджет, получивший `Open` до завершения обмена, откладывает запрос объекта до появления `contextNonce`.

Мобильный iframe (`GET /entry/iframe-mobile?contextKey=...`) получает контекст по `contextKey` из URL: мобильный хост протокол `user-context` не поддерживает. `contextKey` в сессии не хранится и после bootstrap заменяется на `contextNonce`. Без `contextKey` или с устаревшим ключом страница отвечает `401` с HTML-пояснением, что решение нужно открыть заново из мобильного приложения.

Страница мобильного iframe — набор ручных проверок WebView (клавиатура и буфер обмена, изображения, видео и файлы, камера, микрофон, геолокация). Метка карточки показывает итог последней проверки: «Не проверено», «Работает», «Ошибка» или «Нет API», если браузер не дает нужный API. Внизу — параметры окружения (userAgent, размеры окна и видимой области, safe area, защищённый контекст) и кнопка «Скопировать отчёт»: окружение и итоги проверок одним текстом. Страница написана на чистом JS/CSS (`static/assets/entry/iframe-mobile.*`) без сборки фронта.

Когда меняется `contextNonce`:
- Если повторно открыть iframe/виджет для того же `uid`, `accountId` и `isAdmin`, то `contextNonce` переиспользуется.
- Если изменился пользователь, аккаунт или признак администратора, `contextNonce` обновляется.

Когда завершается сессия:
- Исходное время жизни сессии (TTL) равно 2 часам (константа USER_CONTEXT_SESSION_TTL_SECONDS).
- TTL скользящий: пока iframe/виджет делает backend-запросы, сессия продлевается. Если пользователь не совершает никаких действий в течение TTL, то сессия завершается.

## Окно чатов

После перехода решения в статус `Activated` МойСклад показывает его окно в разделе «Чаты». В дескрипторе окно
описано как `<iframe type="chat" sourceUrl=".../entry/iframe-chat" useContextKey="false">` с `<uses><user-context/></uses>`:
контекст пользователя оно получает так же, как основной iframe, а другие сервисы хост-окна (попапы, навигация,
стандартные диалоги) в чатах недоступны.

Отличия от основного iframe, которые учитывает страница (`frontend/src/chat/`):
- ширина не больше 1096px, горизонтального скролла быть не должно;
- хост не подстраивает высоту окна: `autoResizeIframe()` не вызывается, страница скроллится сама;
- окно видно всем пользователям аккаунта, поэтому на нем только чтение: состояние решения и журнал действий из сценариев.

## Действия в сценариях

Блок `<scenario>` дескриптора объявляет действия, которые администратор аккаунта может выбрать на странице
сценариев МоегоСклада. При срабатывании сценария МойСклад вызывает `POST .../apps/<appId>/<accountId>/scenario`
под service JWT и передает `actionName`, `actionType` (`ADD`, `MODIFY`, `CHANGE_STATUS`, `OVERDUE`,
`CHANGE_PRODUCTION_STATE`), `objectId` и `objectType`.

Демо-действия и ответы решения:
- `log-event` — записывает срабатывание в журнал и отвечает `200`;
- `fetch-object` — запрашивает объект через JSON API по `objectType`/`objectId`, сохраняет его название; если объект получить не удалось, отвечает `502`, и МойСклад повторит действие по политике retry;
- `reject` — отвечает `400` с объектом `error`: сообщение `errorMessage` пользователь увидит в истории выполнения сценария.

Ответить нужно быстрее 10 секунд: иначе МойСклад считает попытку неуспешной и повторяет запрос. Журнал последних
срабатываний показывает окно чатов. Подробности в [README модуля](app/scenario/README.md).

## Структура проекта

Основные entrypoints:
- `app/__main__.py` — запуск локального HTTP-сервера через `python -m app`
- `app/factory.py` — создание Flask-приложения, настройка middleware, repositories и services
- `app/web/routes.py` — регистрация HTTP routes и адаптация request/response к services

API и интеграции:
- `app/services/vendor_endpoint.py` — обработка lifecycle событий и button callbacks
- `app/scenario/` — обработчик действий из сценариев и журнал для окна чатов, см. [README](app/scenario/README.md)
- `app/services/buttons.py` — формирование action-ответов для кнопок
- `app/integrations/vendor_api.py` — клиент Vendor API (обмен токена user-context, context по `contextKey` для мобильного iframe, status)
- `app/integrations/json_api.py` — клиент JSON API 1.2

UI и entry:
- `frontend/` — основной iframe и окно чатов на React и `@moysklad/uikit`, сборка esbuild в `static/assets/app`
- `frontend/src/chat/` — окно чатов: состояние решения и журнал действий из сценариев (`frontend/src/scenario/`)
- `frontend/src/ui/prevent-focus-scroll.ts` — отключает прокрутку по фокусу: autoFocus в дропдаунах кита иначе скроллит страницу МоегоСклада
- `frontend/src/uikit-examples/` — вкладка «Примеры UI Kit», см. [README](frontend/src/uikit-examples/README.md)
- `templates/entry/*` — Jinja-шаблоны iframe, окна чатов, widget и popup страниц
- `static/assets/entry/*` — стили и скрипты виджетов, popup и мобильного iframe
- `app/services/entry.py` — подготовка view models для entry-страниц

Программа лояльности:
- `app/loyalty/` — подключение Loyalty API и заглушка провайдера, см. [README](app/loyalty/README.md)

Состояние и безопасность:
- `app/domain/app_instance.py` — модель состояния установки приложения
- `app/repositories/sqlite.py` — SQLite-хранение установок, server-side сессий и replay-маркеров JWT
- `app/services/user_context.py` — bootstrap user context по одноразовому токену и проверка backend-запросов по `contextNonce`
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

Тесты — спецификация публичного контракта, а не цель покрытия: на контракт и важный отказ хватает
одного-двух тестов. Контракты модулей лежат рядом с модулями (`tests/loyalty/`, `tests/scenario/`),
склейка приложения, HTTP и SQLite — в `tests/integration/`, остальное в корне `tests/`
(подробнее в [AGENTS.md](AGENTS.md)). Для запуска выполните команды:

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
