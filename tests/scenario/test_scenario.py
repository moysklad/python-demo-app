"""Интеграционный тест: действия из сценариев через Vendor endpoint и журнал в окне чатов."""

from __future__ import annotations

from tests.conftest import FakeJsonApiFactory, create_client, vendor_auth_header

SCENARIO_URL = "/api/moysklad/vendor/1.0/apps/local-dev-app-id/account-1/scenario"


def scenario_request(action_name: str, **overrides) -> dict:
    return {
        "actionName": action_name,
        "actionType": "ADD",
        "objectId": "624b7f4d-9c1b-11ef-0a83-18f5000001ec",
        "objectType": "CustomerOrder",
        **overrides,
    }


def journal(client) -> dict:
    bootstrap = client.post("/entry/user-context", json={"token": "opaque-token-1", "page": "chat"})
    assert bootstrap.status_code == 200
    page_data = bootstrap.get_json()["pageData"]
    response = client.post("/utils/scenario-events", json={"contextNonce": page_data["contextNonce"]})
    assert response.status_code == 200
    assert response.get_json()["scenarioEvents"] == page_data["scenarioEvents"]
    return response.get_json()


def test_scenario_requires_vendor_auth(app_config):
    client = create_client(app_config)

    assert client.post(SCENARIO_URL, json=scenario_request("log-event")).status_code == 401


def test_scenario_log_event_is_recorded_for_chat_window(app_config):
    client = create_client(app_config)

    response = client.post(SCENARIO_URL, headers=vendor_auth_header(app_config.secret_key), json=scenario_request("log-event", actionType="MODIFY"))

    assert response.status_code == 200
    assert response.get_data() == b""
    result = journal(client)
    assert [action["name"] for action in result["scenarioActions"]] == ["log-event", "fetch-object", "reject"]
    (event,) = result["scenarioEvents"]
    assert event["actionName"] == "log-event"
    assert event["actionTitle"] == "Записать событие в журнал решения"
    assert event["actionType"] == "MODIFY"
    assert event["objectType"] == "CustomerOrder"
    assert event["outcome"] == "ok"
    assert event["createdAt"]


def test_scenario_reject_returns_error_for_user(app_config):
    client = create_client(app_config)

    response = client.post(SCENARIO_URL, headers=vendor_auth_header(app_config.secret_key), json=scenario_request("reject"))

    assert response.status_code == 400
    error = response.get_json()["error"]
    assert error["code"] == 1001
    assert "CustomerOrder 624b7f4d-9c1b-11ef-0a83-18f5000001ec" in error["errorMessage"]
    (event,) = journal(client)["scenarioEvents"]
    assert event["outcome"] == "rejected"
    assert event["message"] == error["errorMessage"]


def test_scenario_fetch_object_stores_object_name(app_config):
    json_api_factory = FakeJsonApiFactory()
    json_api_factory.api.object_response = {"id": "624b7f4d", "name": "00042"}
    client = create_client(app_config, json_api_factory=json_api_factory)

    response = client.post(SCENARIO_URL, headers=vendor_auth_header(app_config.secret_key), json=scenario_request("fetch-object"))

    assert response.status_code == 200
    (event,) = journal(client)["scenarioEvents"]
    assert event["outcome"] == "ok"
    assert event["objectName"] == "00042"


def test_scenario_fetch_object_failure_asks_for_retry_only_when_it_can_help(app_config):
    json_api_factory = FakeJsonApiFactory()
    json_api_factory.api.object_status = 429
    client = create_client(app_config, json_api_factory=json_api_factory)

    response = client.post(SCENARIO_URL, headers=vendor_auth_header(app_config.secret_key), json=scenario_request("fetch-object"))
    assert response.status_code == 502

    json_api_factory.api.object_status = 404
    json_api_factory.api.object_response = {"errors": [{"error": "Объект не найден"}]}
    response = client.post(
        SCENARIO_URL,
        headers=vendor_auth_header(app_config.secret_key, jti="jti-2"),
        json=scenario_request("fetch-object", objectType="Company"),
    )
    assert response.status_code == 400
    assert "404" in response.get_json()["error"]["errorMessage"]
    assert json_api_factory.api.requested_entities == ["customerorder", "counterparty"]
    assert [event["outcome"] for event in journal(client)["scenarioEvents"]] == ["failed", "failed"]


def test_scenario_rejects_unknown_action_and_incomplete_body(app_config):
    client = create_client(app_config)

    unknown = client.post(SCENARIO_URL, headers=vendor_auth_header(app_config.secret_key, jti="jti-unknown"), json=scenario_request("explode"))
    incomplete = client.post(SCENARIO_URL, headers=vendor_auth_header(app_config.secret_key, jti="jti-incomplete"), json={"actionName": "log-event"})

    assert unknown.status_code == 400
    assert "explode" in unknown.get_json()["error"]["errorMessage"]
    assert incomplete.status_code == 400
    assert journal(client)["scenarioEvents"] == []


def test_scenario_journal_keeps_latest_events_first(app_config):
    client = create_client(app_config)
    for index in range(3):
        response = client.post(
            SCENARIO_URL,
            headers=vendor_auth_header(app_config.secret_key, jti=f"jti-{index}"),
            json=scenario_request("log-event", objectId=f"object-{index}"),
        )
        assert response.status_code == 200

    events = journal(client)["scenarioEvents"]

    assert [event["objectId"] for event in events] == ["object-2", "object-1", "object-0"]


def test_scenario_journal_requires_context_nonce(app_config):
    client = create_client(app_config)

    assert client.post("/utils/scenario-events", json={}).status_code == 401
    assert client.post("/utils/scenario-events", json={"contextNonce": "stale"}).status_code == 401


def test_chat_window_is_served_without_user_context(app_config):
    client = create_client(app_config)

    response = client.get("/entry/iframe-chat")

    assert response.status_code == 200
    assert "/assets/app/chat.js" in response.get_data(as_text=True)
    assert "account-1" not in response.get_data(as_text=True)
