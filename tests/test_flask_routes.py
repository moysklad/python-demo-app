from __future__ import annotations

import logging
import re

from app.domain.app_instance import AppInstance, AppStatus
from app.factory import create_app

from tests.conftest import FakeJsonApiFactory, FakeVendorApi, vendor_auth_header
from tests.memory_repositories import MemoryAppInstanceRepository, MemoryJwtReplayRepository


class CapturingLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


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
        "/api/moysklad/vendor/1.0/apps/app-1/account-1",
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
        "/api/moysklad/vendor/1.0/apps/app-1/account-1",
        headers=vendor_auth_header(app_config.secret_key),
        json={"cause": "Install", "access": [{"access_token": "token"}]},
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "SettingsRequired"}
    assert app_repository.load("app-1", "account-1").access_token == "token"


def test_vendor_endpoint_rejects_replayed_jwt(app_config):
    # повторный JWT должен отбрасываться.
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()
    headers = vendor_auth_header(app_config.secret_key, jti="jti-replay")

    first_response = client.put(
        "/api/moysklad/vendor/1.0/apps/app-1/account-1",
        headers=headers,
        json={"cause": "Install"},
    )
    second_response = client.put(
        "/api/moysklad/vendor/1.0/apps/app-1/account-1",
        headers=headers,
        json={"cause": "Install"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 401


def test_vendor_endpoint_resume_activates_when_store_exists(app_config):
    app_repository = MemoryAppInstanceRepository()
    app_repository.save(AppInstance("app-1", "account-1", store="Основной склад", status=AppStatus.SUSPENDED))
    app = create_app(
        app_config,
        app_repository=app_repository,
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    response = client.put(
        "/api/moysklad/vendor/1.0/apps/app-1/account-1",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-resume"),
        json={"cause": "Resume"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "Activated"}
    assert app_repository.load("app-1", "account-1").status == AppStatus.ACTIVATED


def test_vendor_endpoint_suspend_then_uninstall_flow(app_config):
    app_repository = MemoryAppInstanceRepository()
    app_repository.save(AppInstance("app-1", "account-1", access_token="token", status=AppStatus.ACTIVATED))
    app = create_app(
        app_config,
        app_repository=app_repository,
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    suspend_response = client.delete(
        "/api/moysklad/vendor/1.0/apps/app-1/account-1",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-suspend"),
        json={"cause": "Suspend"},
    )
    suspended_app = app_repository.load("app-1", "account-1")
    uninstall_response = client.delete(
        "/api/moysklad/vendor/1.0/apps/app-1/account-1",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-uninstall"),
        json={"cause": "Uninstall"},
    )

    assert suspend_response.status_code == 200
    assert suspended_app is not None
    assert suspended_app.status == AppStatus.SUSPENDED
    assert suspended_app.access_token == ""
    assert uninstall_response.status_code == 200
    assert app_repository.load("app-1", "account-1") is None


def test_vendor_endpoint_app_event_handles_permissions_changed(app_config):
    app_repository = MemoryAppInstanceRepository()
    app = create_app(
        app_config,
        app_repository=app_repository,
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    app_repository.save(AppInstance("app-1", "account-1", status=AppStatus.ACTIVATED))
    response = client.put(
        "/api/moysklad/vendor/1.0/apps/app-1/account-1/event",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-event-2"),
        json={"cause": "PermissionsChanged"},
    )

    assert response.status_code == 200


def test_vendor_button_actions_return_expected_json(app_config):
    # Проверяется нажатие кнопки в карточке и в списке.
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    document_response = client.post(
        "/api/moysklad/vendor/1.0/apps/app-1/account-1/button",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-button-doc"),
        json={
            "buttonName": "show-popup",
            "extensionPoint": "customerorder",
            "objectId": "object-1",
            "user": {"role": "admin"},
        },
    )
    list_response = client.post(
        "/api/moysklad/vendor/1.0/apps/app-1/account-1/button",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-button-list"),
        json={
            "buttonName": "show-notification",
            "extensionPoint": "customerorder",
            "selected": [{"id": "object-1"}, {"id": "object-2"}],
        },
    )

    assert document_response.status_code == 200
    assert document_response.get_json()["action"] == "showPopup"
    assert list_response.status_code == 200
    assert list_response.get_json()["action"] == "showNotification"


def test_update_settings_redacts_access_token_in_logs(app_config):
    # Решение не должно светить access_token ни в request logging, ни в обычном info-логе.
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()
    root_logger = logging.getLogger()
    handler = CapturingLogHandler()
    root_logger.addHandler(handler)
    try:
        entry_response = client.get("/entry/iframe?contextKey=context-key-1")
        nonce_match = re.search(r'name="contextNonce" value="([^"]+)"', entry_response.get_data(as_text=True))
        assert nonce_match is not None

        install_response = client.put(
            "/api/moysklad/vendor/1.0/apps/app-1/account-1",
            headers=vendor_auth_header(app_config.secret_key, jti="jti-redact-install"),
            json={"cause": "Install", "access": [{"access_token": "token-123"}]},
        )
        update_response = client.post(
            "/utils/update-settings",
            data={"contextNonce": nonce_match.group(1), "infoMessage": "hello", "store": "Основной склад"},
        )
    finally:
        root_logger.removeHandler(handler)

    assert install_response.status_code == 200
    assert update_response.status_code == 200
    assert update_response.get_json()["message"] == "Настройки обновлены"
    log_text = "\n".join(handler.messages)
    assert "token-123" not in log_text
    assert "App settings updated appId=" in log_text
    assert "status=Activated" in log_text


def test_entry_bootstrap_uses_context_nonce_after_context_key_exchange(app_config):
    app_repository = MemoryAppInstanceRepository()
    vendor_api = FakeVendorApi()
    app = create_app(
        app_config,
        app_repository=app_repository,
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=vendor_api,
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    entry_response = client.get("/entry/iframe?contextKey=context-key-1")
    html = entry_response.get_data(as_text=True)
    match = re.search(r'name="contextNonce" value="([^"]+)"', html)

    assert entry_response.status_code == 200
    assert "context-key-1" not in html
    assert 'name="contextKey"' not in html
    assert 'id="settingsForm"' in html
    assert 'data-update-url="/utils/update-settings"' in html
    assert 'id="settingsResult"' in html
    assert 'id="appStatus"' in html
    assert 'id="appStatusTitle"' in html
    assert 'id="appStatusDetails"' in html
    assert 'src="/assets/entry/iframe.js"' in html
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
    assert update_response.get_json() == {
        "message": "Настройки обновлены",
        "status": {
            "className": "status-ready",
            "title": "РЕШЕНИЕ ГОТОВО К РАБОТЕ",
            "showDetails": True,
            "infoMessage": "hello",
            "store": "Основной склад",
        },
    }
    app_instance = app_repository.load(app_config.app_id, "account-1")
    assert app_instance.store == "Основной склад"
    assert app_instance.status == AppStatus.ACTIVATED
    assert vendor_api.status_updates[-1] == (app_config.app_id, "account-1", "Activated")

    object_response = client.post(
        "/utils/get-object?entity=customerorder",
        json={"contextNonce": match.group(1), "objectId": "object-1"},
    )

    assert object_response.status_code == 200
    assert object_response.get_data(as_text=True) == "Заказ покупателя Документ"


def test_update_settings_sets_settings_required_without_store(app_config):
    app_repository = MemoryAppInstanceRepository()
    vendor_api = FakeVendorApi()
    app = create_app(
        app_config,
        app_repository=app_repository,
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=vendor_api,
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    entry_response = client.get("/entry/iframe?contextKey=context-key-1")
    match = re.search(r'name="contextNonce" value="([^"]+)"', entry_response.get_data(as_text=True))

    assert match is not None
    response = client.post(
        "/utils/update-settings",
        data={"contextNonce": match.group(1), "infoMessage": "hello", "store": "   "},
    )

    app_instance = app_repository.load(app_config.app_id, "account-1")
    assert response.status_code == 200
    assert response.get_json() == {
        "message": "Настройки обновлены",
        "status": {
            "className": "status-required",
            "title": "ТРЕБУЕТСЯ НАСТРОЙКА",
            "showDetails": False,
            "infoMessage": "hello",
            "store": "",
        },
    }
    assert app_instance.store == ""
    assert app_instance.status == AppStatus.SETTINGS_REQUIRED
    assert vendor_api.status_updates[-1] == (app_config.app_id, "account-1", "SettingsRequired")


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
