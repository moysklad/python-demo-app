from __future__ import annotations

from typing import Any

from app.config import AppConfig
from app.integrations.http_client import HttpClient
from app.security.jwt_tools import build_vendor_api_jwt


class VendorApi:
    def __init__(self, config: AppConfig, http_client: HttpClient | None = None) -> None:
        self._config = config
        self._http_client = http_client or HttpClient()

    def get_context(self, context_key: str) -> dict[str, Any] | None:
        body = {}
        return self._http_client.request_json(
            "POST",
            f"{self._config.moysklad_vendor_api_endpoint_url}/context/{context_key}",
            build_vendor_api_jwt(self._config),
            body,
            service_name="vendor-api",
        )

    def update_app_status(self, app_id: str, account_id: str, status: str) -> bool:
        body = {"status": status}
        return self._http_client.execute(
            "PUT",
            f"{self._config.moysklad_vendor_api_endpoint_url}/apps/{app_id}/{account_id}/status",
            build_vendor_api_jwt(self._config),
            body,
            service_name="vendor-api",
        )
