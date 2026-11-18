from __future__ import annotations

import os
import secrets
import time
from typing import Any, Iterator

import jwt
import pytest
from flask import Flask
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import AppConfig
from app.integrations.http_client import HttpJsonResponse
from app.integrations.vendor_api import UserContextExchangeResult, VendorApiUserContext
from app.repositories import migrations
from app.repositories.migrations import apply_migrations, create_postgres_engine

TEST_DB = {
    "db_host": os.environ.get("APP_DB_HOST", "localhost"),
    "db_port": int(os.environ.get("APP_DB_PORT", "5432")),
    "db_name": os.environ.get("APP_DB_NAME", "python_demo_app"),
    "db_user": os.environ.get("APP_DB_USER", "python_demo_app"),
    "db_password": os.environ.get("APP_DB_PASSWORD", "python_demo_app"),
}

_created_apps: list[Flask] = []


@pytest.fixture(autouse=True)
def _fail_fast_without_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migrations, "STARTUP_CONNECT_ATTEMPTS", 1)


def _drop_schema(engine: Engine, schema: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(f"drop schema if exists {schema} cascade"))


@pytest.fixture
def app_config() -> Iterator[AppConfig]:
    """Каждый тест работает в своей схеме PostgreSQL, после теста схема удаляется."""
    config = AppConfig(
        app_id="local-dev-app-id",
        app_uid="local-dev-app-uid",
        secret_key="local-dev-secret-key-32-characters",
        encrypt_key="00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
        app_base_url="http://localhost:8080",
        session_secret="local-dev-session-secret-32-chars",
        session_cookie_secure=False,
        session_cookie_same_site="lax",
        trust_proxy=0,
        db_schema=f"test_{secrets.token_hex(4)}",
        **TEST_DB,
    )
    yield config

    if _created_apps:
        _drop_schema(_created_apps[0].extensions["db_engine"], config.db_schema)
    for flask_app in _created_apps:
        flask_app.extensions["db_engine"].dispose()
    _created_apps.clear()


@pytest.fixture
def db_engine(app_config: AppConfig) -> Iterator[Engine]:
    engine = create_postgres_engine(app_config)
    apply_migrations(engine, app_config.db_schema)
    yield engine
    _drop_schema(engine, app_config.db_schema)
    engine.dispose()


class FakeVendorApi:
    def __init__(self) -> None:
        self.context_response: dict[str, Any] | None = {
            "uid": "user-1",
            "shortFio": "Иванов И.",
            "accountId": "account-1",
            "permissions": {"admin": {"view": "ALL"}},
        }
        self.status_updates: list[tuple[str, str, str]] = []
        self.update_status_result = True
        self.exchange_result = UserContextExchangeResult(
            ok=True,
            status_code=200,
            data=VendorApiUserContext(account_id="account-1", user_id="user-id-1", user_uid="user-1", role="admin"),
        )
        self.exchanged_tokens: list[str] = []

    def exchange_user_context(self, token: str) -> UserContextExchangeResult:
        self.exchanged_tokens.append(token)
        return self.exchange_result

    def get_context(self, context_key: str) -> dict[str, Any] | None:
        return self.context_response

    def update_app_status(self, app_id: str, account_id: str, status: str) -> bool:
        self.status_updates.append((app_id, account_id, status))
        return self.update_status_result


class FakeJsonApi:
    def __init__(self) -> None:
        self.object_response: dict[str, Any] | None = {"id": "object-1", "name": "Документ"}
        self.object_status: int | None = 200
        self.requested_entities: list[str] = []
        self.stores_successful = True
        self.stores_retries = 0

    def store_names(self) -> list[str]:
        return ["Основной склад"]

    def get_object(self, entity: str, object_id: str) -> dict[str, Any] | None:
        return self.object_response

    def get_scenario_object(self, entity: str, object_id: str) -> HttpJsonResponse:
        self.requested_entities.append(entity)
        if self.object_status is None:
            return HttpJsonResponse(status_code=None, json_body=None, successful=False)
        return HttpJsonResponse(status_code=self.object_status, json_body=self.object_response, successful=self.object_status < 300)

    def stores_with_retries(self) -> tuple[dict[str, Any] | None, int]:
        stores = {"rows": []} if self.stores_successful else None
        return stores, self.stores_retries


class FakeJsonApiFactory:
    def __init__(self) -> None:
        self.api = FakeJsonApi()

    def create(self, access_token: str) -> FakeJsonApi:
        return self.api


def vendor_auth_header(secret: str, jti: str = "jti-1") -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode({"sub": "local-dev-app-uid", "iat": now, "exp": now + 300, "jti": jti}, secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def create_client(
    app_config: AppConfig,
    *,
    app_repository: Any = None,
    vendor_api: FakeVendorApi | None = None,
    json_api_factory: FakeJsonApiFactory | None = None,
    **extra: Any,
):
    """Flask test client с фейками вместо внешних API: общая склейка для интеграционных тестов."""
    from app.factory import create_app

    from tests.memory_repositories import MemoryAppInstanceRepository, MemoryJwtReplayRepository

    app = create_app(
        app_config,
        app_repository=app_repository or MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=vendor_api or FakeVendorApi(),
        json_api_factory=json_api_factory or FakeJsonApiFactory(),
        **extra,
    )
    _created_apps.append(app)
    return app.test_client()


def bootstrap_iframe(client, page: str | None = "iframe") -> dict:
    """Обмен одноразового токена на контекст: ответ POST /entry/user-context с pageData страницы."""
    body: dict = {"token": "opaque-token-1"}
    if page is not None:
        body["page"] = page
    response = client.post("/entry/user-context", json=body)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()
