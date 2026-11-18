"""Интеграционный тест: подключение Loyalty API через Vendor API и заглушка провайдера."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from app.integrations.vendor_api import UserContextExchangeResult, VendorApiUserContext
from app.loyalty.installation import LoyaltyInstallation
from app.loyalty.repository import PostgresLoyaltyInstallationRepository
from app.loyalty.service import LoyaltyService
from app.loyalty.vendor_api import LoyaltySettingsResult
from app.repositories.postgres import create_session_factory

from tests.conftest import FakeVendorApi, bootstrap_iframe, create_client as create_app_client, vendor_auth_header

TOKEN_HEADER = "Lognex-Discount-API-Auth-Token"


class FakeLoyaltyVendorApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str, bool]] = []
        self.result = LoyaltySettingsResult(outcome="ok")
        # Выполняется один раз, пока МойСклад «обрабатывает» запрос: так тест вклинивает параллельные попытки.
        self.before_reply: Callable[[], None] | None = None

    def update_settings(self, app_id: str, account_id: str, url: str, token: str, external_search: bool) -> LoyaltySettingsResult:
        self.calls.append((app_id, account_id, url, token, external_search))
        before_reply, self.before_reply = self.before_reply, None
        if before_reply is not None:
            before_reply()
        return self.result


def create_client(app_config, vendor_api: FakeVendorApi, loyalty_vendor_api: FakeLoyaltyVendorApi):
    return create_app_client(app_config, vendor_api=vendor_api, loyalty_vendor_api=loyalty_vendor_api)


def bootstrap(client) -> str:
    return bootstrap_iframe(client)["contextNonce"]


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
    assert connect(client, context_nonce, providerToken="provider-token-2", externalSearch=True).status_code == 502
    assert client.post("/loyalty/counterparty/detail", headers={TOKEN_HEADER: "provider-token-1"}).status_code == 200
    assert client.post("/loyalty/counterparty/detail", headers={TOKEN_HEADER: "provider-token-2"}).status_code == 200

    assert connect(client, context_nonce, providerToken="provider-token-3").status_code == 409
    assert client.post("/loyalty/counterparty/detail", headers={TOKEN_HEADER: "provider-token-3"}).status_code == 401

    loyalty_vendor_api.result = LoyaltySettingsResult(outcome="rejected", code=2007, message="Решение еще устанавливается")
    assert connect(client, context_nonce, externalSearch=False).status_code == 502
    assert client.get("/loyalty/counterparty?search=ivanov", headers={TOKEN_HEADER: "provider-token-2"}).status_code == 200

    loyalty_vendor_api.result = LoyaltySettingsResult(outcome="ok")
    assert connect(client, context_nonce).status_code == 200
    assert loyalty_vendor_api.calls[-1][3] == "provider-token-2"
    assert client.post("/loyalty/counterparty/detail", headers={TOKEN_HEADER: "provider-token-1"}).status_code == 401
    assert client.post("/loyalty/counterparty/detail", headers={TOKEN_HEADER: "provider-token-2"}).status_code == 200


def test_late_reply_of_previous_attempt_keeps_pending_token_of_new_one(app_config, db_engine):
    # Две попытки с одним токеном идут параллельно. После ответа первой начинается подключение с другим токеном,
    # и только потом приходит ответ второй: он не должен стереть токен, который МойСклад мог принять.
    repository = PostgresLoyaltyInstallationRepository(app_config.encrypt_key, create_session_factory(db_engine))
    vendor_api = FakeLoyaltyVendorApi()
    service = LoyaltyService(app_config, repository, vendor_api)

    def parallel_attempts() -> None:
        assert service.connect("account-1", None, "token-a", False).status_code == 200
        vendor_api.result = LoyaltySettingsResult(outcome="unknown", message="timeout")
        assert service.connect("account-1", None, "token-b", False).status_code == 502
        vendor_api.result = LoyaltySettingsResult(outcome="ok")

    vendor_api.before_reply = parallel_attempts
    assert service.connect("account-1", None, "token-a", False).status_code == 200

    stored = repository.load(app_config.app_id, "account-1")
    assert stored is not None
    assert stored.provider_token == "token-a"
    assert stored.pending_provider_token == "token-b"


def test_token_accepted_after_parallel_attempt_was_rejected_stays_pending():
    # Отказ параллельной попытке убрал общий ожидающий токен, но эту МойСклад принял: провайдер обязан принимать ее токен.
    installation = LoyaltyInstallation("app-1", "account-1", provider_token="current-token", connected_at="2026-01-01T00:00:00+00:00")

    installation.confirm_update(("token-a", True))

    assert installation.provider_token == "current-token"
    assert installation.pending_settings() == ("token-a", True)
    assert installation.accepts_token("token-a")


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


def test_loyalty_tokens_of_another_encrypt_key_are_treated_as_missing(app_config, db_engine):
    # После смены APP_ENCRYPT_KEY Install и Uninstall читают подключение: оно не должно ронять их ошибкой расшифровки.
    session_factory = create_session_factory(db_engine)
    PostgresLoyaltyInstallationRepository("0" * 64, session_factory).save(
        LoyaltyInstallation("app-1", "account-1", provider_token="old", connected_at="2026-01-01T00:00:00+00:00", pending_provider_token="pending")
    )
    repository = PostgresLoyaltyInstallationRepository(app_config.encrypt_key, session_factory)

    loaded = repository.load("app-1", "account-1")

    assert loaded is not None
    assert loaded.provider_token is None
    assert loaded.pending_provider_token is None
    assert repository.find_by_token("old") is None


def test_concurrent_loyalty_updates_of_one_account_keep_single_pending_token(app_config, db_engine):
    # Два одновременных подключения с разными токенами: второе должно увидеть ожидающий токен первого, а не затереть его.
    repository = PostgresLoyaltyInstallationRepository(app_config.encrypt_key, create_session_factory(db_engine))
    def begin_update(token: str) -> str | None:
        def change(installation: LoyaltyInstallation) -> bool:
            if not installation.can_begin_update(token):
                return False
            installation.begin_update(token, False)
            return True

        return repository.update_locked("app-1", "account-1", change).pending_provider_token

    # Тест держит блокировку аккаунта, пока оба потока не встанут на нее, затем отпускает.
    with ThreadPoolExecutor(max_workers=2) as executor, db_engine.connect() as connection:
        connection.execute(text("select pg_advisory_xact_lock(hashtext('loyalty:app-1:account-1'))"))
        results = [executor.submit(begin_update, token) for token in ("token-a", "token-b")]
        deadline = time.monotonic() + 10
        blocked = 0
        while blocked < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
            blocked = connection.execute(
                text(
                    "select count(*) from pg_locks where locktype = 'advisory' and not granted"
                    " and database = (select oid from pg_database where datname = current_database())"
                )
            ).scalar_one()
        connection.rollback()
        first, second = (result.result() for result in results)

    assert blocked == 2
    assert first == second
    stored = repository.load("app-1", "account-1")
    assert stored is not None
    assert stored.pending_provider_token == first

