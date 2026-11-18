from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from app.config import AppConfig
from app.loyalty.installation import LoyaltyInstallation, LoyaltyInstallationRepository, describe_loyalty_connection
from app.loyalty.vendor_api import LoyaltyVendorApi
from app.services.common import ServiceResponse

logger = logging.getLogger(__name__)


class LoyaltyService:
    def __init__(self, config: AppConfig, repository: LoyaltyInstallationRepository, vendor_api: LoyaltyVendorApi) -> None:
        self._config = config
        self._repository = repository
        self._vendor_api = vendor_api

    def default_provider_url(self) -> str:
        return f"{self._config.app_base_url.rstrip('/')}/loyalty"

    def iframe_page_data(self, account_id: str) -> dict[str, Any]:
        """Данные вкладки «Программа лояльности» для основного iframe."""
        return {
            "loyalty": describe_loyalty_connection(self._repository.load(self._config.app_id, account_id)),
            "defaultLoyaltyProviderUrl": self.default_provider_url(),
        }

    def _finish_update(self, account_id: str, finish: Callable[[LoyaltyInstallation], None]) -> LoyaltyInstallation:
        """
        Завершает попытку под той же блокировкой, что и ее начало. Состояние читается заново:
        пока шел вызов Vendor API, его могла изменить другая попытка.
        """

        def change(current: LoyaltyInstallation) -> bool:
            finish(current)
            return True

        return self._repository.update_locked(self._config.app_id, account_id, change)

    def find_by_token(self, token: str) -> LoyaltyInstallation | None:
        token = token.strip()
        return None if token == "" else self._repository.find_by_token(token)

    def connect(self, account_id: str, raw_provider_url: Any, raw_provider_token: Any, external_search: bool) -> ServiceResponse:
        """
        Передает настройки в МойСклад через Vendor API. Новый токен сначала сохраняется как ожидающий:
        провайдер принимает его вместе с действующим, пока МойСклад не подтвердит настройки. Так решение
        не получит 401, если МойСклад уже переключился на новый токен, и не сломает работающее подключение,
        если переключения не было.
        """
        provider_url = self._parse_provider_url(raw_provider_url)
        if provider_url is None:
            return ServiceResponse(status_code=400, json_body={"message": "Укажите корректный HTTP(S) URL провайдера Loyalty API"})

        app_id = self._config.app_id
        provider_token = raw_provider_token.strip() if isinstance(raw_provider_token, str) else ""
        pending_before: tuple[str | None, bool] | None = None

        def begin_update(installation: LoyaltyInstallation) -> bool:
            nonlocal pending_before
            if not installation.can_begin_update(provider_token or None):
                return False
            pending_before = installation.pending_settings()
            installation.begin_update(provider_token or None, external_search)
            return True

        installation = self._repository.update_locked(app_id, account_id, begin_update)
        if pending_before is None:
            return ServiceResponse(
                status_code=409,
                json_body={
                    "message": "Исход предыдущего подключения еще не известен: МойСклад мог принять отправленный тогда токен. "
                    "Повторите подключение с пустым полем токена, чтобы отправить его еще раз."
                },
            )

        sent = installation.pending_settings()
        result = self._vendor_api.update_settings(app_id, account_id, provider_url, sent[0] or "", external_search)
        if result.outcome == "unknown":
            logger.warning("Loyalty settings outcome is unknown for accountId=%s: %s", account_id, result.message)
            return ServiceResponse(
                status_code=502,
                json_body={
                    "message": "Не удалось подтвердить, что МойСклад принял настройки Loyalty API. "
                    f"{result.message}. Повторите подключение: до этого решение принимает и прежний, и новый токен."
                },
            )

        if result.outcome == "rejected":
            self._finish_update(account_id, lambda current: current.discard_update(sent, pending_before))
            code = f"Ошибка {result.code}: " if result.code is not None else ""
            return ServiceResponse(
                status_code=502,
                json_body={"message": f"Не удалось передать настройки Loyalty API. {code}{result.message}"},
            )

        installation = self._finish_update(account_id, lambda current: current.confirm_update(sent))
        logger.info("Loyalty settings sent to MoySklad for accountId=%s, externalSearch=%s", account_id, external_search)
        return ServiceResponse(
            json_body={
                "message": "Настройки переданы в МойСклад через Vendor API",
                "loyalty": describe_loyalty_connection(installation),
            }
        )

    def on_install(self, app_id: str, account_id: str) -> None:
        self._reset_connection(app_id, account_id)

    def on_uninstall(self, app_id: str, account_id: str) -> None:
        self._reset_connection(app_id, account_id)

    def _reset_connection(self, app_id: str, account_id: str) -> None:
        """
        МойСклад удаляет настройки лояльности при Uninstall, поэтому признак подключения сбрасывается
        и при удалении, и при повторной установке. Suspend настройки не удаляет — на него модуль не реагирует.
        """
        installation = self._repository.load(app_id, account_id)
        if installation is None or (not installation.is_connected() and installation.pending_provider_token is None):
            return

        installation.mark_disconnected()
        self._repository.save(installation)
        logger.info("Loyalty connection reset for appId=%s on accountId=%s", app_id, account_id)

    def _parse_provider_url(self, value: Any) -> str | None:
        raw = value.strip() if isinstance(value, str) and value.strip() else self.default_provider_url()
        try:
            parts = urlsplit(raw)
        except ValueError:
            return None

        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return None
        if parts.username or parts.password or parts.query or parts.fragment:
            return None

        return raw.rstrip("/")
