from __future__ import annotations

from urllib.parse import quote

from app.config import AppConfig, app_version
from app.domain.app_instance import AppInstance, AppInstanceRepository
from app.integrations.json_api import JsonApiFactory
# [feature:loyalty] программа лояльности: данные вкладки приходят из модуля app/loyalty.
from app.loyalty.service import LoyaltyService
from app.services.user_context import UserContextSessionEntry
from app.services.utils import describe_app_status


class EntryService:
    def __init__(
        self,
        config: AppConfig,
        app_repository: AppInstanceRepository,
        json_api_factory: JsonApiFactory,
        loyalty_service: LoyaltyService,
    ) -> None:
        self._config = config
        self._app_repository = app_repository
        self._json_api_factory = json_api_factory
        self._loyalty_service = loyalty_service

    def iframe_page_data(self, context: UserContextSessionEntry) -> dict[str, object]:
        app = self._load_app(context.account_id)
        stores_values: list[str] = []
        if context.is_admin:
            stores_values = self._json_api_factory.create(app.access_token).store_names()

        return {
            "accountId": context.account_id,
            "isAdmin": context.is_admin,
            "uid": context.uid,
            "fio": context.fio,
            "contextNonce": context.context_nonce,
            "appVersion": app_version(),
            "infoMessage": app.info_message or "",
            "store": app.store or "",
            "storesValues": stores_values,
            "status": describe_app_status(app),
            # [feature:loyalty] программа лояльности
            **self._loyalty_service.iframe_page_data(context.account_id),
        }

    def mobile_iframe_view_model(self, context: UserContextSessionEntry) -> dict[str, object]:
        return {
            "account_id": context.account_id,
            "is_admin": context.is_admin,
            "access_level": "администратор аккаунта" if context.is_admin else "простой пользователь",
            "uid": context.uid,
            "fio": context.fio,
            "context_nonce": context.context_nonce,
        }

    def widget_view_model(self, entity: str) -> dict[str, object]:
        return {
            "get_object_url": f"/utils/get-object?entity={quote(entity, safe='')}",
        }

    def _load_app(self, account_id: str) -> AppInstance:
        return self._app_repository.load(self._config.app_id, account_id) or AppInstance(self._config.app_id, account_id)
