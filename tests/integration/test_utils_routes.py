"""Интеграционный тест: backend-запросы iframe и виджетов, авторизованные по contextNonce."""

from __future__ import annotations

from app.domain.app_instance import AppStatus
from app.integrations.vendor_api import UserContextExchangeResult, VendorApiUserContext

from tests.conftest import FakeJsonApiFactory, FakeVendorApi, bootstrap_iframe, create_client
from tests.memory_repositories import MemoryAppInstanceRepository


def test_update_settings_changes_status_through_vendor_api(app_config):
    app_repository = MemoryAppInstanceRepository()
    vendor_api = FakeVendorApi()
    client = create_client(app_config, app_repository=app_repository, vendor_api=vendor_api)
    context_nonce = bootstrap_iframe(client)["contextNonce"]

    activated = client.post("/utils/update-settings", data={"contextNonce": context_nonce, "infoMessage": "hello", "store": "Основной склад"})
    settings_required = client.post("/utils/update-settings", data={"contextNonce": context_nonce, "infoMessage": "hello", "store": "   "})

    assert activated.get_json() == {
        "message": "Настройки обновлены",
        "status": {"badge": "green", "title": "Решение готово к работе", "showDetails": True, "infoMessage": "hello", "store": "Основной склад"},
    }
    assert settings_required.get_json()["status"]["title"] == "Требуется настройка"
    assert app_repository.load(app_config.app_id, "account-1").status == AppStatus.SETTINGS_REQUIRED
    assert [update[2] for update in vendor_api.status_updates] == ["Activated", "SettingsRequired"]


def test_backend_requests_require_context_nonce(app_config):
    client = create_client(app_config)
    bootstrap_iframe(client)

    # Старый контракт с contextKey после bootstrap не принимается.
    legacy = client.post("/utils/update-settings", data={"contextKey": "context-key-1", "infoMessage": "hello", "store": "Основной склад"})
    stale = client.post("/utils/get-object?entity=customerorder", json={"contextNonce": "stale", "objectId": "object-1"})

    assert legacy.status_code == 401
    assert stale.status_code == 401


def test_get_object_returns_entity_name(app_config):
    client = create_client(app_config)
    context_nonce = bootstrap_iframe(client)["contextNonce"]

    response = client.post("/utils/get-object?entity=customerorder", json={"contextNonce": context_nonce, "objectId": "object-1"})

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "Заказ покупателя Документ"
    assert response.headers.get("Set-Cookie") is None


def test_stores_returns_retry_count_for_success_and_failure(app_config):
    json_api_factory = FakeJsonApiFactory()
    json_api_factory.api.stores_retries = 2
    client = create_client(app_config, json_api_factory=json_api_factory)
    context_nonce = bootstrap_iframe(client)["contextNonce"]

    success = client.post("/utils/stores", data={"contextNonce": context_nonce})
    json_api_factory.api.stores_successful = False
    failure = client.post("/utils/stores", data={"contextNonce": context_nonce})

    assert success.status_code == 200
    assert success.get_json() == {"message": "Запрос выполнен", "success": True, "retries": 2}
    # Ответ всегда JSON, в том числе на 502: клиенту нужно число ретраев даже у неудачных запросов.
    assert failure.status_code == 502
    assert failure.get_json() == {"message": "Не удалось получить список складов", "success": False, "retries": 2}


def test_admin_only_routes_reject_regular_user(app_config):
    vendor_api = FakeVendorApi()
    vendor_api.exchange_result = UserContextExchangeResult(
        ok=True,
        status_code=200,
        data=VendorApiUserContext(account_id="account-1", user_id="user-id-1", user_uid="user-1", role="worker"),
    )
    client = create_client(app_config, vendor_api=vendor_api)
    context_nonce = bootstrap_iframe(client)["contextNonce"]

    stores = client.post("/utils/stores", data={"contextNonce": context_nonce})
    settings = client.post("/utils/update-settings", data={"contextNonce": context_nonce, "store": "Основной склад"})

    assert stores.status_code == 403
    assert stores.get_data(as_text=True) == "Недостаточно прав"
    assert settings.status_code == 403
