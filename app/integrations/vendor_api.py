from __future__ import annotations

from typing import Any

from app.config import AppConfig
from app.integrations.http_client import HttpClient
from app.security.jwt_tools import build_vendor_api_jwt


class VendorApi:
    def __init__(self, config: AppConfig, http_client: HttpClient | None = None) -> None:
        self._config = config
        self._http_client = http_client or HttpClient()

    def context(self, context_key: str) -> dict[str, Any] | None:
        return self._request("POST", f"/context/{context_key}", {})

    def update_app_status(self, app_id: str, account_id: str, status: str) -> dict[str, Any] | None:
        return self._http_client.request_json(
            "PUT",
            f"{self._config.moysklad_vendor_api_endpoint_url}/apps/{app_id}/{account_id}/status",
            build_vendor_api_jwt(self._config),
            {"status": status},
            service_name="vendor-api",
            retryable=True,
            allow_empty_success_response=True,
        )

    def _request(self, method: str, path: str, body: Any = None) -> dict[str, Any] | None:
        return self._http_client.request_json(
            method,
            f"{self._config.moysklad_vendor_api_endpoint_url}{path}",
            build_vendor_api_jwt(self._config),
            body,
            service_name="vendor-api",
            retryable=method.upper() != "POST",
        )
