from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.config import AppConfig
from app.integrations.http_client import HttpClient
from app.security.jwt_tools import build_vendor_api_jwt

VENDOR_API_ERROR_HINTS = {
    2004: "Проверьте, что решение установлено на этом аккаунте и APP_ID совпадает с решением в кабинете вендора",
    2006: "Добавьте элемент <loyaltyApi/> в дескриптор решения в кабинете вендора",
    2007: "Дождитесь, пока решение завершит установку, и повторите попытку",
}


@dataclass(frozen=True)
class LoyaltySettingsResult:
    # rejected — МойСклад точно не принял настройки; unknown — ответа нет или 5xx, настройки могли примениться
    outcome: Literal["ok", "rejected", "unknown"]
    code: int | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome == "ok"


class LoyaltyVendorApi:
    def __init__(self, config: AppConfig, http_client: HttpClient) -> None:
        self._config = config
        self._http_client = http_client

    def update_settings(self, app_id: str, account_id: str, url: str, token: str, external_search: bool) -> LoyaltySettingsResult:
        """Передает настройки Loyalty API в МойСклад: PUT /apps/{appId}/{accountId}/loyalty."""
        # Тело содержит токен провайдера, поэтому в лог его не пишем.
        response = self._http_client.request_json_detailed(
            "PUT",
            f"{self._config.moysklad_vendor_api_endpoint_url}/apps/{app_id}/{account_id}/loyalty",
            build_vendor_api_jwt(self._config),
            {"url": url, "token": token, "externalSearch": external_search},
            service_name="vendor-api",
            log_body=False,
        )
        if response.successful:
            return LoyaltySettingsResult(outcome="ok")

        if response.status_code is None or response.status_code >= 500:
            return LoyaltySettingsResult(outcome="unknown", message="Vendor API не ответил или ответил ошибкой сервера")

        body = response.json_body
        errors = body.get("errors") if isinstance(body, dict) else None
        error = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else None
        if error is None or not error.get("error"):
            return LoyaltySettingsResult(outcome="rejected", message=f"Vendor API ответил статусом {response.status_code}")

        code = error.get("code") if isinstance(error.get("code"), int) else None
        hint = VENDOR_API_ERROR_HINTS.get(code) if code is not None else None
        message = f"{error['error']}. {hint}" if hint else str(error["error"])
        return LoyaltySettingsResult(outcome="rejected", code=code, message=message)
