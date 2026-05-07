from __future__ import annotations

from app.factory import create_app
from app.repositories.memory import MemoryAppInstanceRepository, MemoryJwtReplayRepository

from tests.conftest import FakeJsonApiFactory, FakeVendorApi, vendor_auth_header


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
