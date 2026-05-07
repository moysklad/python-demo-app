from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import jwt
import pytest

from app.config import AppConfig


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        app_id="local-dev-app-id",
        app_uid="local-dev-app-uid",
        secret_key="local-dev-secret-key-32-characters",
        encrypt_key="00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
        app_base_url="http://localhost:3000",
        session_secret="local-dev-session-secret-32-chars",
        session_cookie_secure=False,
        session_cookie_same_site="lax",
        trust_proxy=0,
        data_dir=tmp_path,
        app_db_path=tmp_path / "app.sqlite",
    )


class FakeVendorApi:
    def __init__(self) -> None:
        self.context_response: dict[str, Any] | None = {
            "uid": "user-1",
            "shortFio": "Иванов И.",
            "accountId": "account-1",
            "permissions": {"admin": {"view": "ALL"}},
        }
        self.status_updates: list[tuple[str, str, str]] = []
        self.update_status_result: dict[str, Any] | None = {}

    def context(self, context_key: str) -> dict[str, Any] | None:
        return self.context_response

    def update_app_status(self, app_id: str, account_id: str, status: str) -> dict[str, Any] | None:
        self.status_updates.append((app_id, account_id, status))
        return self.update_status_result


class FakeJsonApi:
    def __init__(self) -> None:
        self.object_response: dict[str, Any] | None = {"id": "object-1", "name": "Документ"}

    def store_names(self) -> list[str]:
        return ["Основной склад"]

    def get_object(self, entity: str, object_id: str) -> dict[str, Any] | None:
        return self.object_response


class FakeJsonApiFactory:
    def __init__(self) -> None:
        self.api = FakeJsonApi()

    def create(self, access_token: str) -> FakeJsonApi:
        return self.api


def vendor_auth_header(secret: str, jti: str = "jti-1") -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode({"sub": "local-dev-app-uid", "iat": now, "exp": now + 300, "jti": jti}, secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}
