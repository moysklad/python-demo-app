from __future__ import annotations

import re
from dataclasses import replace

import app.factory as factory_module
from app.factory import create_app
from app.repositories.memory import MemoryAppInstanceRepository, MemoryJwtReplayRepository

from tests.conftest import FakeJsonApiFactory, FakeVendorApi, vendor_auth_header


class CountingSessionRepository:
    def __init__(self) -> None:
        self.save_calls = 0
        self.delete_calls = 0

    def load(self, sid):
        return {}

    def save(self, sid, session_data, expires_at_ms):
        self.save_calls += 1

    def delete(self, sid):
        self.delete_calls += 1


def test_health_route(app_config):
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )

    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.get_json()["status"] == "healthy"


def test_vendor_endpoint_requires_auth(app_config):
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )

    response = app.test_client().put(
        "/vendor-endpoint/api/moysklad/vendor/1.0/apps/app-1/account-1",
        json={"cause": "Install"},
    )

    assert response.status_code == 401


def test_vendor_endpoint_accepts_valid_jwt(app_config):
    app_repository = MemoryAppInstanceRepository()
    app = create_app(
        app_config,
        app_repository=app_repository,
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )

    response = app.test_client().put(
        "/vendor-endpoint/api/moysklad/vendor/1.0/apps/app-1/account-1",
        headers=vendor_auth_header(app_config.secret_key),
        json={"cause": "Install", "access": [{"access_token": "token"}]},
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "SettingsRequired"}
    assert app_repository.load("app-1", "account-1").access_token == "token"


def test_static_assets_do_not_resave_loaded_session(app_config):
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )
    session_repository = CountingSessionRepository()
    app.session_interface._repository = session_repository
    signed_sid = app.session_interface._serializer.dumps("sid-1")
    client = app.test_client()
    client.set_cookie(app_config.session_name, signed_sid)

    response = client.get("/assets/entry/popup.css")

    assert response.status_code == 200
    assert session_repository.save_calls == 0
    assert session_repository.delete_calls == 0


def test_request_logging_is_not_registered_for_non_debug_level(app_config, monkeypatch):
    app_config = replace(app_config, log_level="INFO")
    called = False

    def fake_register_request_logging(app):
        nonlocal called
        called = True

    monkeypatch.setattr("app.factory._register_request_logging", fake_register_request_logging)

    create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )

    assert called is False


def test_vendor_request_log_writes_body_after_blank_line(app_config, monkeypatch):
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )
    captured: list[tuple[str, tuple[object, ...]]] = []

    def fake_debug(message: str, *args: object) -> None:
        captured.append((message, args))

    monkeypatch.setattr(factory_module.logger, "debug", fake_debug)

    response = app.test_client().put(
        "/vendor-endpoint/api/moysklad/vendor/1.0/apps/app-1/account-1",
        json={"cause": "Install"},
    )

    assert response.status_code == 401
    assert captured
    assert "body=" not in captured[0][0]
    assert captured[0][0].endswith("\nheaders=%s\n\n%s")
    assert "Content-Type" in captured[0][1][2]
    assert captured[0][1][-1] == {"cause": "Install"}
    assert captured[-1][0].endswith("\nheaders=%s")
    assert "Content-Type" in captured[-1][1][-1]


def test_entry_bootstrap_uses_context_nonce_after_context_key_exchange(app_config):
    app_repository = MemoryAppInstanceRepository()
    app = create_app(
        app_config,
        app_repository=app_repository,
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    entry_response = client.get("/entry/iframe?contextKey=context-key-1")
    html = entry_response.get_data(as_text=True)
    match = re.search(r'name="contextNonce" value="([^"]+)"', html)

    assert entry_response.status_code == 200
    assert "context-key-1" not in html
    assert 'name="contextKey"' not in html
    assert match is not None

    widget_response = client.get("/entry/widget-customerorder?contextKey=context-key-1")
    widget_html = widget_response.get_data(as_text=True)
    widget_match = re.search(r'data-get-object-url="([^"]+)"', widget_html)

    assert widget_response.status_code == 200
    assert widget_match is not None
    assert "contextNonce=" not in widget_match.group(1)
    assert 'data-context-nonce="' in widget_html

    update_response = client.post(
        "/utils/update-settings",
        data={"contextNonce": match.group(1), "infoMessage": "hello", "store": "Основной склад"},
    )

    assert update_response.status_code == 200
    assert app_repository.load(app_config.app_id, "account-1").store == "Основной склад"

    object_response = client.post(
        "/utils/get-object?entity=customerorder",
        json={"contextNonce": match.group(1), "objectId": "object-1"},
    )

    assert object_response.status_code == 200
    assert object_response.get_data(as_text=True) == "Заказ покупателя Документ"


def test_backend_context_rejects_context_key_after_bootstrap(app_config):
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    assert client.get("/entry/iframe?contextKey=context-key-1").status_code == 200
    response = client.post(
        "/utils/update-settings",
        data={"contextKey": "context-key-1", "infoMessage": "hello", "store": "Основной склад"},
    )

    assert response.status_code == 401
