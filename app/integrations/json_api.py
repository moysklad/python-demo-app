from __future__ import annotations

from typing import Any

from app.config import AppConfig
from app.integrations.http_client import HttpClient


class JsonApi:
    def __init__(self, config: AppConfig, access_token: str, http_client: HttpClient | None = None) -> None:
        self._config = config
        self._access_token = access_token
        self._http_client = http_client or HttpClient()

    def stores(self) -> dict[str, Any] | None:
        return self._http_client.request_json(
            "GET",
            f"{self._config.moysklad_json_api_endpoint_url}/entity/store",
            self._access_token,
            service_name="json-api",
            retryable=True,
        )

    def store_names(self) -> list[str]:
        stores = self.stores()
        rows = stores.get("rows") if isinstance(stores, dict) else None
        if not isinstance(rows, list):
            return []
        return [item["name"] for item in rows if isinstance(item, dict) and item.get("name")]

    def get_object(self, entity: str, object_id: str) -> dict[str, Any] | None:
        return self._http_client.request_json(
            "GET",
            f"{self._config.moysklad_json_api_endpoint_url}/entity/{entity}/{object_id}",
            self._access_token,
            service_name="json-api",
            retryable=True,
        )


class JsonApiFactory:
    def __init__(self, config: AppConfig, http_client: HttpClient | None = None) -> None:
        self._config = config
        self._http_client = http_client or HttpClient()

    def create(self, access_token: str) -> JsonApi:
        return JsonApi(self._config, access_token, self._http_client)
