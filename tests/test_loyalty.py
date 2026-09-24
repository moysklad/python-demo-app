from __future__ import annotations

from app.factory import create_app
from app.integrations.vendor_api import UserContextExchangeResult, VendorApiUserContext
from app.loyalty.vendor_api import LoyaltySettingsResult

from tests.conftest import FakeJsonApiFactory, FakeVendorApi, vendor_auth_header
from tests.memory_repositories import MemoryAppInstanceRepository, MemoryJwtReplayRepository

TOKEN_HEADER = "Lognex-Discount-API-Auth-Token"


class FakeLoyaltyVendorApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str, bool]] = []
        self.result = LoyaltySettingsResult(outcome="ok")

    def update_settings(self, app_id: str, account_id: str, url: str, token: str, external_search: bool) -> LoyaltySettingsResult:
        self.calls.append((app_id, account_id, url, token, external_search))
        return self.result


def create_client(app_config, vendor_api: FakeVendorApi, loyalty_vendor_api: FakeLoyaltyVendorApi):
    app = create_app(
        app_config,
        app_repository=MemoryAppInstanceRepository(),
        jwt_replay_repository=MemoryJwtReplayRepository(),
        vendor_api=vendor_api,
        json_api_factory=FakeJsonApiFactory(),
        loyalty_vendor_api=loyalty_vendor_api,
    )
    return app.test_client()


def bootstrap(client) -> str:
    response = client.post("/entry/user-context", json={"token": "opaque-token-1", "page": "iframe"})
    assert response.status_code == 200
    return response.get_json()["contextNonce"]


def connect(client, context_nonce: str, **body):
    return client.post("/utils/connect-loyalty", json={"contextNonce": context_nonce, **body})


def test_connect_loyalty_then_provider_accepts_token_until_uninstall(app_config):
    loyalty_vendor_api = FakeLoyaltyVendorApi()
    client = create_client(app_config, FakeVendorApi(), loyalty_vendor_api)
    context_nonce = bootstrap(client)

    response = connect(client, context_nonce, providerToken="provider-token-1", externalSearch=True)

    assert response.status_code == 200
    assert response.get_json()["loyalty"]["state"] == "connected"
    assert loyalty_vendor_api.calls == [
        (app_config.app_id, "account-1", "http://localhost:8080/loyalty", "provider-token-1", True),
    ]

    assert client.get("/loyalty/counterparty?search=ivan").status_code == 401
    search = client.get("/loyalty/counterparty?search=ivanov", headers={TOKEN_HEADER: "provider-token-1"})
    assert search.status_code == 200
    assert [row["name"] for row in search.get_json()["rows"]] == ["Иванов Иван"]
    assert client.post("/loyalty/retaildemand", headers={TOKEN_HEADER: "provider-token-1"}).status_code == 201

    uninstall = client.delete(
        f"/api/moysklad/vendor/1.0/apps/{app_config.app_id}/account-1",
        json={"cause": "Uninstall"},
        headers=vendor_auth_header(app_config.secret_key),
    )
    assert uninstall.status_code in {200, 204}

    page_data = client.post("/entry/user-context", json={"token": "opaque-token-2", "page": "iframe"}).get_json()["pageData"]
    assert page_data["loyalty"]["state"] == "reconnect-required"
    assert client.post("/loyalty/counterparty/detail", headers={TOKEN_HEADER: "provider-token-1"}).status_code == 200


def test_rejected_reconnect_keeps_working_connection(app_config):
    loyalty_vendor_api = FakeLoyaltyVendorApi()
    client = create_client(app_config, FakeVendorApi(), loyalty_vendor_api)
    context_nonce = bootstrap(client)
    assert connect(client, context_nonce, providerToken="provider-token-1").status_code == 200

    loyalty_vendor_api.result = LoyaltySettingsResult(outcome="rejected", code=2006, message="Нет доступа. Добавьте элемент <loyaltyApi/>")
    response = connect(client, context_nonce, providerToken="provider-token-2", externalSearch=True)

    assert response.status_code == 502
    assert "Ошибка 2006" in response.get_json()["message"]
    assert client.post("/loyalty/counterparty/detail", headers={TOKEN_HEADER: "provider-token-1"}).status_code == 200
    assert client.post("/loyalty/counterparty/detail", headers={TOKEN_HEADER: "provider-token-2"}).status_code == 401
    assert client.get("/loyalty/counterparty", headers={TOKEN_HEADER: "provider-token-1"}).status_code == 404
    page_data = client.post("/entry/user-context", json={"token": "opaque-token-2", "page": "iframe"}).get_json()["pageData"]
    assert page_data["loyalty"]["state"] == "connected"


def test_unknown_reconnect_outcome_accepts_both_tokens_until_confirmed(app_config):
    loyalty_vendor_api = FakeLoyaltyVendorApi()
    client = create_client(app_config, FakeVendorApi(), loyalty_vendor_api)
    context_nonce = bootstrap(client)
    assert connect(client, context_nonce, providerToken="provider-token-1").status_code == 200

    loyalty_vendor_api.result = LoyaltySettingsResult(outcome="unknown", message="Vendor API не ответил")
    assert connect(client, context_nonce, providerToken="provider-token-2").status_code == 502
    assert client.post("/loyalty/counterparty/detail", headers={TOKEN_HEADER: "provider-token-1"}).status_code == 200
    assert client.post("/loyalty/counterparty/detail", headers={TOKEN_HEADER: "provider-token-2"}).status_code == 200

    loyalty_vendor_api.result = LoyaltySettingsResult(outcome="ok")
    assert connect(client, context_nonce, providerToken="provider-token-2").status_code == 200
    assert client.post("/loyalty/counterparty/detail", headers={TOKEN_HEADER: "provider-token-1"}).status_code == 401
    assert client.post("/loyalty/counterparty/detail", headers={TOKEN_HEADER: "provider-token-2"}).status_code == 200


def test_connect_loyalty_is_available_only_to_admin(app_config):
    vendor_api = FakeVendorApi()
    vendor_api.exchange_result = UserContextExchangeResult(
        ok=True,
        status_code=200,
        data=VendorApiUserContext(account_id="account-1", user_id="user-id-2", user_uid="user-2", role="worker"),
    )
    loyalty_vendor_api = FakeLoyaltyVendorApi()
    client = create_client(app_config, vendor_api, loyalty_vendor_api)

    response = connect(client, bootstrap(client), providerToken="provider-token-1")

    assert response.status_code == 403
    assert loyalty_vendor_api.calls == []
