"""Интеграционный тест: страницы entry и обмен одноразового токена на контекст пользователя."""

from __future__ import annotations

import logging
import re
from dataclasses import replace

from app.integrations.vendor_api import UserContextExchangeResult, VendorApiUserContext

from tests.conftest import FakeVendorApi, bootstrap_iframe, create_client, vendor_auth_header


def test_entry_pages_are_served_without_user_context(app_config):
    # Страницы отдаются без персональных данных и без сессии; contextKey в URL игнорируется.
    client = create_client(app_config)

    iframe = client.get("/entry/iframe-main?contextKey=context-key-1")
    iframe_html = iframe.get_data(as_text=True)
    chat = client.get("/entry/iframe-chat")
    widget_html = client.get("/entry/widget-customerorder").get_data(as_text=True)

    assert iframe.status_code == 200
    assert re.search(r'<script type="module" src="/assets/app/iframe\.js\?v=[^"]+">', iframe_html) is not None
    assert "context-key-1" not in iframe_html
    assert "contextNonce" not in iframe_html
    assert iframe.headers.get("Set-Cookie") is None
    assert chat.status_code == 200
    assert "/assets/app/chat.js" in chat.get_data(as_text=True)
    assert "contextNonce=" not in re.search(r'data-get-object-url="([^"]+)"', widget_html).group(1)
    assert "js-widget-sdk@1.3.0" in widget_html
    with client.session_transaction() as session_data:
        assert "userContext" not in session_data


def test_token_exchange_returns_page_data_and_hides_token(app_config):
    vendor_api = FakeVendorApi()
    client = create_client(app_config, vendor_api=vendor_api)

    payload = bootstrap_iframe(client)
    widget_payload = bootstrap_iframe(client, page=None)

    assert vendor_api.exchanged_tokens == ["opaque-token-1", "opaque-token-1"]
    assert payload["user"] == {"accountId": "account-1", "userId": "user-id-1", "userUid": "user-1", "role": "admin", "isAdmin": True}
    assert payload["pageData"]["uid"] == "user-1"
    assert payload["pageData"]["contextNonce"] == payload["contextNonce"]
    assert payload["pageData"]["storesValues"] == ["Основной склад"]
    assert payload["pageData"]["status"]["badge"] == "orange"
    assert payload["pageData"]["loyalty"]["state"] == "not-connected"
    assert payload["pageData"]["defaultLoyaltyProviderUrl"] == "http://localhost:8080/loyalty"
    assert "opaque-token-1" not in str(payload)
    # Виджет контекст страницы не просит и получает только пользователя и nonce.
    assert "pageData" not in widget_payload
    assert widget_payload["contextNonce"] == payload["contextNonce"]
    with client.session_transaction() as session_data:
        assert "opaque-token-1" not in str(session_data)
        assert session_data["userContext"]["contextNonce"] == payload["contextNonce"]


def test_token_exchange_rejects_empty_token_and_reports_zeus_errors_without_body(app_config):
    vendor_api = FakeVendorApi()
    client = create_client(app_config, vendor_api=vendor_api)

    assert client.post("/entry/user-context", json={}).status_code == 400
    assert client.post("/entry/user-context", json={"token": "   "}).status_code == 400
    assert client.post("/entry/user-context", data={"token": "opaque-token-1"}).status_code == 400
    assert vendor_api.exchanged_tokens == []

    vendor_api.exchange_result = UserContextExchangeResult(ok=False, status_code=404, error_code="3007")
    not_found = client.post("/entry/user-context", json={"token": "opaque-token-1"})
    assert not_found.status_code == 404
    assert not_found.get_json() == {"message": "Не удалось получить контекст пользователя", "code": "3007"}

    # 401 от Zeus — ошибка вендора (битый service JWT), клиенту отдаётся как 502.
    vendor_api.exchange_result = UserContextExchangeResult(ok=False, status_code=401)
    unauthorized = client.post("/entry/user-context", json={"token": "opaque-token-1"})
    assert unauthorized.status_code == 502
    assert unauthorized.get_json() == {"message": "Не удалось получить контекст пользователя"}
    with client.session_transaction() as session_data:
        assert "userContext" not in session_data


def test_non_admin_role_gets_page_without_admin_data(app_config):
    vendor_api = FakeVendorApi()
    vendor_api.exchange_result = UserContextExchangeResult(
        ok=True,
        status_code=200,
        data=VendorApiUserContext(account_id="account-1", user_id="user-id-1", user_uid="user-1", role="individual"),
    )
    client = create_client(app_config, vendor_api=vendor_api)

    payload = bootstrap_iframe(client)

    assert payload["user"]["isAdmin"] is False
    assert payload["pageData"]["isAdmin"] is False
    assert payload["pageData"]["storesValues"] == []


def test_tokens_are_redacted_in_logs(app_config):
    # Ни одноразовый токен, ни access_token установки не должны попадать в логи, включая DEBUG request logging.
    # configure_logging() переустанавливает root-обработчики, поэтому caplog не подходит: свой handler после create_app.
    client = create_client(app_config=replace(app_config, log_level="DEBUG"))
    messages: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: messages.append(record.getMessage())
    logging.getLogger().addHandler(handler)

    try:
        context_nonce = bootstrap_iframe(client)["contextNonce"]
        install = client.put(
            "/api/moysklad/vendor/1.0/apps/app-1/account-1",
            headers=vendor_auth_header(app_config.secret_key, jti="jti-redact-install"),
            json={"cause": "Install", "access": [{"access_token": "token-123"}]},
        )
        update = client.post("/utils/update-settings", data={"contextNonce": context_nonce, "infoMessage": "hello", "store": "Основной склад"})
    finally:
        logging.getLogger().removeHandler(handler)

    log_text = "\n".join(messages)
    assert install.status_code == 200
    assert update.status_code == 200
    assert "HTTP request started POST /entry/user-context" in log_text
    assert "App settings updated appId=" in log_text
    assert "opaque-token-1" not in log_text
    assert "token-123" not in log_text


def test_mobile_iframe_exchanges_context_key_for_nonce(app_config):
    client = create_client(app_config)

    response = client.get("/entry/iframe-mobile?contextKey=context-key-1")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "context-key-1" not in html
    assert 'name="contextKey"' not in html
    assert re.search(r'name="contextNonce" value="([^"]+)"', html) is not None
    assert 'src="/assets/entry/iframe-mobile.js"' in html
    assert "WidgetSDK" not in html
    assert client.get("/entry/iframe-mobile").status_code == 401
