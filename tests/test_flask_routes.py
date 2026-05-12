from __future__ import annotations

from dataclasses import replace

from app.factory import create_app
from app.repositories.memory import MemoryAppInstanceRepository, MemoryJwtReplayRepository

from tests.conftest import FakeJsonApiFactory, FakeVendorApi, vendor_auth_header


class CountingSessionRepository:
    def __init__(self) -> None:
        self.save_calls = 0
        self.delete_calls = 0

    def load(self, sid):
        return {"userContext": {"byContextKey": {}, "contextKeyStack": []}}

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
