from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.config import AppConfig
from app.integrations.http_client import HttpClient
from app.security.jwt_tools import build_vendor_api_jwt


logger = logging.getLogger(__name__)

USER_CONTEXT_ROLES = ("admin", "cashier", "worker", "individual")


@dataclass(frozen=True)
class VendorApiUserContext:
    account_id: str
    user_id: str
    user_uid: str
    role: str


@dataclass(frozen=True)
class UserContextExchangeResult:
    ok: bool
    status_code: int = 502
    error_code: str | None = None
    data: VendorApiUserContext | None = None


class VendorApi:
    def __init__(self, config: AppConfig, http_client: HttpClient | None = None) -> None:
        self._config = config
        self._http_client = http_client or HttpClient()

    def exchange_user_context(self, token: str) -> UserContextExchangeResult:
        response = self._http_client.request_json_detailed(
            "POST",
            f"{self._config.moysklad_vendor_api_endpoint_url}/context/user",
            build_vendor_api_jwt(self._config),
            {"token": token},
            service_name="vendor-api",
            retryable=False,
            log_body=False,
        )
        if not response.successful:
            status_code = response.status_code if response.status_code is not None and 400 <= response.status_code <= 599 else 502
            return UserContextExchangeResult(ok=False, status_code=status_code, error_code=_parse_error_code(response.json_body))

        context = _normalize_user_context(response.json_body)
        if context is None:
            logger.warning("Vendor API returned an invalid user context response service=vendor-api")
            return UserContextExchangeResult(ok=False, status_code=502)

        return UserContextExchangeResult(ok=True, status_code=response.status_code or 200, data=context)

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


def parse_user_context_role(value: Any) -> str:
    if isinstance(value, str) and value in USER_CONTEXT_ROLES:
        return value
    return "individual"


def _normalize_user_context(value: Any) -> VendorApiUserContext | None:
    if not isinstance(value, dict):
        return None

    account_id = str(value.get("accountId", "") or "").strip()
    user_id = str(value.get("userId", "") or "").strip()
    user_uid = str(value.get("userUid", "") or "").strip()
    if account_id == "" or user_id == "" or user_uid == "":
        return None

    return VendorApiUserContext(
        account_id=account_id,
        user_id=user_id,
        user_uid=user_uid,
        role=parse_user_context_role(value.get("role")),
    )


def _parse_error_code(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None

    errors = body.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict) and errors[0].get("code") is not None:
        return str(errors[0]["code"])

    code = body.get("code")
    return None if code is None else str(code)
