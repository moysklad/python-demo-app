from __future__ import annotations

import logging
import re
from dataclasses import replace

from app.domain.app_instance import AppInstance, AppStatus
from app.factory import create_app
from app.integrations.vendor_api import UserContextExchangeResult, VendorApiUserContext

from tests.conftest import FakeJsonApiFactory, FakeVendorApi, vendor_auth_header
from tests.memory_repositories import MemoryAppInstanceRepository, MemoryJwtReplayRepository


class CapturingLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def bootstrap_iframe(client, page: str | None = "iframe") -> dict:
    body: dict = {"token": "opaque-token-1"}
    if page is not None:
        body["page"] = page
    response = client.post("/entry/user-context", json=body)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


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

    assert suspend_response.status_code == 200
    assert suspended_app is not None
    assert suspended_app.status == AppStatus.SUSPENDED
    assert suspended_app.access_token == ""

    repeated_suspend_response = client.delete(
        "/api/moysklad/vendor/1.0/apps/app-1/account-1",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-suspend-2"),
        json={"cause": "Suspend"},
    )
    assert repeated_suspend_response.status_code == 204

    uninstall_response = client.delete(
        "/api/moysklad/vendor/1.0/apps/app-1/account-1",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-uninstall"),
        json={"cause": "Uninstall"},
    )
    uninstalled_app = app_repository.load("app-1", "account-1")

    assert uninstall_response.status_code == 200
    assert uninstalled_app is not None
    assert uninstalled_app.status == AppStatus.UNINSTALLED
    assert uninstalled_app.access_token == ""


def test_vendor_endpoint_delete_is_idempotent(app_config):
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

    def delete(cause: str, jti: str):
        return client.delete(
            "/api/moysklad/vendor/1.0/apps/app-1/account-1",
            headers=vendor_auth_header(app_config.secret_key, jti=jti),
            json={"cause": cause},
        )

    assert delete("Suspend", "jti-suspend-1").status_code == 200
    assert delete("Suspend", "jti-suspend-2").status_code == 204
    assert app_repository.load("app-1", "account-1").status == AppStatus.SUSPENDED

    assert delete("Uninstall", "jti-uninstall-1").status_code == 200
    assert app_repository.load("app-1", "account-1").status == AppStatus.UNINSTALLED
    assert delete("Uninstall", "jti-uninstall-2").status_code == 204
    assert app_repository.load("app-1", "account-1").status == AppStatus.UNINSTALLED

    missing = client.delete(
        "/api/moysklad/vendor/1.0/apps/app-missing/account-missing",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-missing-uninstall"),
        json={"cause": "Uninstall"},
    )
    missing_suspend = client.delete(
        "/api/moysklad/vendor/1.0/apps/app-missing/account-missing",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-missing-suspend"),
        json={"cause": "Suspend"},
    )
    assert missing.status_code == 204
    assert missing_suspend.status_code == 204

    unknown_cause = delete("Pause", "jti-unknown")
    assert unknown_cause.status_code == 400


def test_vendor_endpoint_reinstall_restores_settings(app_config):
    app_repository = MemoryAppInstanceRepository()
    app_repository.save(
        AppInstance("app-1", "account-1", store="Основной склад", access_token="token", status=AppStatus.ACTIVATED)
    )
    app = create_app(
        app_config,
        app_repository=app_repository,
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    uninstall_response = client.delete(
        "/api/moysklad/vendor/1.0/apps/app-1/account-1",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-uninstall-1"),
        json={"cause": "Uninstall"},
    )
    repeated_uninstall_response = client.delete(
        "/api/moysklad/vendor/1.0/apps/app-1/account-1",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-uninstall-2"),
        json={"cause": "Uninstall"},
    )
    install_response = client.put(
        "/api/moysklad/vendor/1.0/apps/app-1/account-1",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-reinstall"),
        json={"cause": "Install", "access": [{"access_token": "token-new"}]},
    )
    reinstalled_app = app_repository.load("app-1", "account-1")

    assert uninstall_response.status_code == 200
    assert repeated_uninstall_response.status_code == 204
    assert install_response.status_code == 200
    assert install_response.get_json() == {"status": "Activated"}
    assert reinstalled_app is not None
    assert reinstalled_app.status == AppStatus.ACTIVATED
    assert reinstalled_app.store == "Основной склад"
    assert reinstalled_app.access_token == "token-new"


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
        context_nonce = bootstrap_iframe(client)["contextNonce"]

        install_response = client.put(
            "/api/moysklad/vendor/1.0/apps/app-1/account-1",
            headers=vendor_auth_header(app_config.secret_key, jti="jti-redact-install"),
            json={"cause": "Install", "access": [{"access_token": "token-123"}]},
        )
        update_response = client.post(
            "/utils/update-settings",
            data={"contextNonce": context_nonce, "infoMessage": "hello", "store": "Основной склад"},
        )
    finally:
        root_logger.removeHandler(handler)

    assert install_response.status_code == 200
    assert update_response.status_code == 200
    assert update_response.get_json()["message"] == "Настройки обновлены"
    log_text = "\n".join(handler.messages)
    assert "token-123" not in log_text
    assert "opaque-token-1" not in log_text
    assert "App settings updated appId=" in log_text
    assert "status=Activated" in log_text


def test_iframe_main_is_served_without_user_context(app_config):
    vendor_api = FakeVendorApi()
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=vendor_api,
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    response = client.get("/entry/iframe-main")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert re.search(r'<script type="module" src="/assets/app/iframe\.js\?v=[^"]+">', html) is not None
    assert 'id="root"' in html
    assert "contextNonce" not in html
    assert response.headers.get("Set-Cookie") is None


def test_iframe_main_ignores_legacy_context_key(app_config):
    vendor_api = FakeVendorApi()
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=vendor_api,
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    response = client.get("/entry/iframe-main?contextKey=context-key-1")

    assert response.status_code == 200
    assert "context-key-1" not in response.get_data(as_text=True)
    assert response.headers.get("Set-Cookie") is None
    with client.session_transaction() as session_data:
        assert "userContext" not in session_data


def test_entry_bootstrap_uses_context_nonce_after_token_exchange(app_config):
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

    payload = bootstrap_iframe(client)
    context_nonce = payload["contextNonce"]

    assert vendor_api.exchanged_tokens == ["opaque-token-1"]
    assert payload["user"] == {
        "accountId": "account-1",
        "userId": "user-id-1",
        "userUid": "user-1",
        "role": "admin",
        "isAdmin": True,
    }
    assert payload["pageData"]["uid"] == "user-1"
    assert payload["pageData"]["accountId"] == "account-1"
    assert payload["pageData"]["isAdmin"] is True
    assert payload["pageData"]["contextNonce"] == context_nonce
    assert payload["pageData"]["storesValues"] == ["Основной склад"]
    assert payload["pageData"]["status"]["badge"] == "orange"
    assert payload["pageData"]["appVersion"]
    assert payload["pageData"]["loyalty"]["state"] == "not-connected"
    assert payload["pageData"]["defaultLoyaltyProviderUrl"] == "http://localhost:8080/loyalty"
    assert "opaque-token-1" not in str(payload)
    with client.session_transaction() as session_data:
        assert "opaque-token-1" not in str(session_data)
        assert session_data["userContext"]["contextNonce"] == context_nonce

    widget_response = client.get("/entry/widget-customerorder")
    widget_html = widget_response.get_data(as_text=True)
    widget_match = re.search(r'data-get-object-url="([^"]+)"', widget_html)

    assert widget_response.status_code == 200
    assert widget_match is not None
    assert "contextNonce=" not in widget_match.group(1)
    assert "data-context-nonce" not in widget_html
    assert "js-widget-sdk@1.3.0" in widget_html

    update_response = client.post(
        "/utils/update-settings",
        data={"contextNonce": context_nonce, "infoMessage": "hello", "store": "Основной склад"},
    )

    assert update_response.status_code == 200
    assert update_response.get_json() == {
        "message": "Настройки обновлены",
        "status": {
            "badge": "green",
            "title": "Решение готово к работе",
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
        json={"contextNonce": context_nonce, "objectId": "object-1"},
    )

    assert object_response.status_code == 200
    assert object_response.get_data(as_text=True) == "Заказ покупателя Документ"
    assert object_response.headers.get("Set-Cookie") is None


def test_user_context_for_widget_skips_page_data(app_config):
    json_api_factory = FakeJsonApiFactory()
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=json_api_factory,
    )
    client = app.test_client()

    payload = bootstrap_iframe(client, page=None)

    assert "pageData" not in payload
    assert payload["user"]["userUid"] == "user-1"
    assert payload["contextNonce"]


def test_user_context_requires_token(app_config):
    vendor_api = FakeVendorApi()
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=vendor_api,
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    assert client.post("/entry/user-context", json={}).status_code == 400
    assert client.post("/entry/user-context", json={"token": "   "}).status_code == 400
    assert client.post("/entry/user-context", data={"token": "opaque-token-1"}).status_code == 400
    assert vendor_api.exchanged_tokens == []


def test_user_context_maps_unknown_role_to_regular_user(app_config):
    vendor_api = FakeVendorApi()
    vendor_api.exchange_result = UserContextExchangeResult(
        ok=True,
        status_code=200,
        data=VendorApiUserContext(account_id="account-1", user_id="user-id-1", user_uid="user-1", role="individual"),
    )
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=vendor_api,
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    payload = bootstrap_iframe(client)

    assert payload["user"]["isAdmin"] is False
    assert payload["pageData"]["isAdmin"] is False
    assert payload["pageData"]["storesValues"] == []


def test_user_context_reports_zeus_errors_without_body(app_config):
    vendor_api = FakeVendorApi()
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=vendor_api,
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    vendor_api.exchange_result = UserContextExchangeResult(ok=False, status_code=404, error_code="3007")
    not_found = client.post("/entry/user-context", json={"token": "opaque-token-1"})
    assert not_found.status_code == 404
    assert not_found.get_json() == {"message": "Не удалось получить контекст пользователя", "code": "3007"}

    vendor_api.exchange_result = UserContextExchangeResult(ok=False, status_code=401)
    unauthorized = client.post("/entry/user-context", json={"token": "opaque-token-1"})
    assert unauthorized.status_code == 502
    assert unauthorized.get_json() == {"message": "Не удалось получить контекст пользователя"}

    with client.session_transaction() as session_data:
        assert "userContext" not in session_data


def test_user_context_token_is_redacted_in_debug_logs(app_config):
    app = create_app(
        replace(app_config, log_level="DEBUG"),
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
        bootstrap_iframe(client)
    finally:
        root_logger.removeHandler(handler)

    log_text = "\n".join(handler.messages)
    assert "HTTP request started POST /entry/user-context" in log_text
    assert "opaque-token-1" not in log_text


def test_mobile_iframe_uses_context_nonce_and_webview_controls(app_config):
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=FakeJsonApiFactory(),
    )
    client = app.test_client()

    response = client.get("/entry/iframe-mobile?contextKey=context-key-1")
    html = response.get_data(as_text=True)
    match = re.search(r'name="contextNonce" value="([^"]+)"', html)

    assert response.status_code == 200
    assert "context-key-1" not in html
    assert 'name="contextKey"' not in html
    assert 'data-context-nonce="' in html
    assert match is not None
    assert 'href="/assets/entry/iframe-mobile.css"' in html
    assert 'src="/assets/entry/iframe-mobile.js"' in html
    assert "WidgetSDK" not in html
    assert 'id="textInput"' in html
    assert 'id="textArea"' in html
    assert 'id="imagePicker"' in html
    assert 'id="videoPicker"' in html
    assert 'id="filePicker"' in html
    assert 'id="cameraPreview"' in html
    assert 'id="microphoneLevel"' in html
    assert 'id="locationOutput"' in html


def test_store_request_returns_retry_count(app_config):
    json_api_factory = FakeJsonApiFactory()
    json_api_factory.api.stores_retries = 2
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=json_api_factory,
    )
    client = app.test_client()
    context_nonce = bootstrap_iframe(client)["contextNonce"]
    response = client.post(
        "/utils/stores",
        data={"contextNonce": context_nonce},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "message": "Запрос выполнен",
        "success": True,
        "retries": 2,
    }
    assert response.headers.get("Set-Cookie") is None


def test_store_request_returns_upstream_failure_with_retry_count(app_config):
    json_api_factory = FakeJsonApiFactory()
    json_api_factory.api.stores_successful = False
    json_api_factory.api.stores_retries = 2
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=FakeVendorApi(),
        json_api_factory=json_api_factory,
    )
    client = app.test_client()
    context_nonce = bootstrap_iframe(client)["contextNonce"]
    response = client.post(
        "/utils/stores",
        data={"contextNonce": context_nonce},
    )

    assert response.status_code == 502
    assert response.get_json() == {
        "message": "Не удалось получить список складов",
        "success": False,
        "retries": 2,
    }


def test_store_request_is_available_only_to_admin(app_config):
    vendor_api = FakeVendorApi()
    vendor_api.exchange_result = UserContextExchangeResult(
        ok=True,
        status_code=200,
        data=VendorApiUserContext(account_id="account-1", user_id="user-id-1", user_uid="user-1", role="worker"),
    )
    json_api_factory = FakeJsonApiFactory()
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=vendor_api,
        json_api_factory=json_api_factory,
    )
    client = app.test_client()
    payload = bootstrap_iframe(client)
    context_nonce = payload["contextNonce"]

    assert payload["pageData"]["isAdmin"] is False

    response = client.post(
        "/utils/stores",
        data={"contextNonce": context_nonce},
    )

    assert response.status_code == 403
    assert response.get_data(as_text=True) == "Недостаточно прав"


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

    context_nonce = bootstrap_iframe(client)["contextNonce"]
    response = client.post(
        "/utils/update-settings",
        data={"contextNonce": context_nonce, "infoMessage": "hello", "store": "   "},
    )

    app_instance = app_repository.load(app_config.app_id, "account-1")
    assert response.status_code == 200
    assert response.get_json() == {
        "message": "Настройки обновлены",
        "status": {
            "badge": "orange",
            "title": "Требуется настройка",
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

    bootstrap_iframe(client)
    response = client.post(
        "/utils/update-settings",
        data={"contextKey": "context-key-1", "infoMessage": "hello", "store": "Основной склад"},
    )

    assert response.status_code == 401
