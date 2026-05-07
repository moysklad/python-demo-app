from __future__ import annotations

from urllib.parse import quote

from app.config import AppConfig
from app.domain.app_instance import AppInstance, AppInstanceRepository, AppStatus
from app.integrations.json_api import JsonApiFactory
from app.services.user_context import UserContextSessionEntry


class EntryService:
    def __init__(self, config: AppConfig, app_repository: AppInstanceRepository, json_api_factory: JsonApiFactory) -> None:
        self._config = config
        self._app_repository = app_repository
        self._json_api_factory = json_api_factory

    def iframe_view_model(self, context: UserContextSessionEntry) -> dict[str, object]:
        app = self._load_app(context.account_id)
        stores_values: list[str] = []
        if context.is_admin:
            stores_values = self._json_api_factory.create(app.access_token).store_names()

        is_settings_required = app.status != AppStatus.ACTIVATED
        return {
            "account_id": context.account_id,
            "is_admin": context.is_admin,
            "access_level": "администратор аккаунта" if context.is_admin else "простой пользователь",
            "uid": context.uid,
            "fio": context.fio,
            "context_key": context.context_key,
            "info_message": app.info_message,
            "store": app.store,
            "status_class": "status-required" if is_settings_required else "status-ready",
            "status_title": "ТРЕБУЕТСЯ НАСТРОЙКА" if is_settings_required else "РЕШЕНИЕ ГОТОВО К РАБОТЕ",
            "show_status_details": not is_settings_required,
            "stores_values": stores_values,
        }

    def widget_view_model(self, entity: str, context: UserContextSessionEntry) -> dict[str, object]:
        return {
            "uid": context.uid,
            "fio": context.fio,
            "context_key": context.context_key,
            "get_object_url": f"/utils/get-object?entity={quote(entity, safe='')}&contextKey={quote(context.context_key, safe='')}&objectId=",
        }

    def _load_app(self, account_id: str) -> AppInstance:
        return self._app_repository.load(self._config.app_id, account_id) or AppInstance(self._config.app_id, account_id)
