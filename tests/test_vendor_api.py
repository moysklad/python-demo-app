from __future__ import annotations

from typing import Any

from app.integrations.http_client import HttpJsonResponse
from app.integrations.vendor_api import VendorApi


class FakeHttpClient:
    def __init__(self, response: HttpJsonResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def request_json_detailed(self, method: str, url: str, bearer_token: str, data: Any = None, **options: Any) -> HttpJsonResponse:
        self.calls.append({"method": method, "url": url, "data": data, **options})
        return self.response


def test_exchange_user_context_posts_token_without_logging_body(app_config):
    http_client = FakeHttpClient(
        HttpJsonResponse(
            status_code=200,
            json_body={"accountId": "account-1", "userId": "user-id-1", "userUid": "user-1", "role": "cashier"},
            successful=True,
        )
    )

    result = VendorApi(app_config, http_client).exchange_user_context("opaque-token-1")

    assert result.ok is True
    assert result.data is not None
    assert result.data.account_id == "account-1"
    assert result.data.user_uid == "user-1"
    assert result.data.role == "cashier"
    call = http_client.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/context/user")
    assert call["data"] == {"token": "opaque-token-1"}
    assert call["log_body"] is False
    assert call["retryable"] is False


def test_exchange_user_context_normalizes_unknown_role(app_config):
    http_client = FakeHttpClient(
        HttpJsonResponse(
            status_code=200,
            json_body={"accountId": "account-1", "userId": "user-id-1", "userUid": "user-1", "role": "owner"},
            successful=True,
        )
    )

    result = VendorApi(app_config, http_client).exchange_user_context("opaque-token-1")

    assert result.ok is True
    assert result.data is not None
    assert result.data.role == "individual"


def test_exchange_user_context_returns_zeus_status_and_code(app_config):
    http_client = FakeHttpClient(
        HttpJsonResponse(status_code=404, json_body={"errors": [{"code": 3007, "error": "not found"}]}, successful=False)
    )

    result = VendorApi(app_config, http_client).exchange_user_context("opaque-token-1")

    assert result.ok is False
    assert result.status_code == 404
    assert result.error_code == "3007"


def test_exchange_user_context_treats_transport_error_and_bad_body_as_502(app_config):
    transport_error = FakeHttpClient(HttpJsonResponse(status_code=None, json_body=None, successful=False))
    bad_body = FakeHttpClient(HttpJsonResponse(status_code=200, json_body={"accountId": "account-1"}, successful=True))

    assert VendorApi(app_config, transport_error).exchange_user_context("t").status_code == 502
    assert VendorApi(app_config, bad_body).exchange_user_context("t").status_code == 502
