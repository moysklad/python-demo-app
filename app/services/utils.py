from __future__ import annotations

import logging
from typing import Any

from app.config import AppConfig
from app.domain.app_instance import AppInstance, AppInstanceRepository, AppStatus
from app.domain.entities import ENTITIES_MAP, is_supported_entity
from app.integrations.json_api import JsonApiFactory
from app.integrations.vendor_api import VendorApi
from app.services.common import ServiceResponse
from app.services.user_context import UserContextService


logger = logging.getLogger(__name__)


class UtilsService:
    def __init__(
        self,
        config: AppConfig,
        app_repository: AppInstanceRepository,
        user_context_service: UserContextService,
        vendor_api: VendorApi,
        json_api_factory: JsonApiFactory,
    ) -> None:
        self._config = config
        self._app_repository = app_repository
        self._user_context_service = user_context_service
        self._vendor_api = vendor_api
        self._json_api_factory = json_api_factory

    def update_settings(self, session_data: dict[str, Any], context_key: str | None, info_message: str, store: str) -> ServiceResponse:
        auth_context = self._user_context_service.resolve_backend_context(session_data, context_key)
        if not auth_context:
            return ServiceResponse(status_code=401, text_body="Ошибка авторизации: передайте contextKey и откройте iframe заново.")

        if not auth_context.is_admin:
            return ServiceResponse(status_code=403, text_body="Недостаточно прав")

        normalized_info_message = info_message.strip()
        normalized_store = store.strip()
        logger.info("Update settings: %s, store: %s", normalized_info_message, normalized_store)

        app = self._app_repository.load(self._config.app_id, auth_context.account_id) or AppInstance(self._config.app_id, auth_context.account_id)
        app.info_message = normalized_info_message
        app.store = normalized_store
        app.status = AppStatus.ACTIVATED

        status_updated = self._vendor_api.update_app_status(self._config.app_id, auth_context.account_id, app.get_status_name() or "")
        if not status_updated:
            return ServiceResponse(status_code=502, text_body="Не удалось обновить статус приложения во внешнем Vendor API")

        self._app_repository.save(app)
        return ServiceResponse(text_body="Настройки обновлены, перезагрузите решение")

    def get_object(self, session_data: dict[str, Any], context_key: str | None, entity: str, object_id: str) -> ServiceResponse:
        auth_context = self._user_context_service.resolve_backend_context(session_data, context_key)
        if not auth_context:
            return ServiceResponse(status_code=401, text_body="Ошибка авторизации: передайте contextKey и откройте iframe/виджет заново.")

        if not is_supported_entity(entity):
            return ServiceResponse(status_code=400, text_body="Неподдерживаемая сущность")

        if object_id == "":
            return ServiceResponse(status_code=400, text_body="objectId обязателен")

        app = self._app_repository.load(self._config.app_id, auth_context.account_id) or AppInstance(self._config.app_id, auth_context.account_id)
        obj = self._json_api_factory.create(app.access_token).get_object(entity, object_id)
        if not obj or not obj.get("name"):
            return ServiceResponse(status_code=502, text_body="Не удалось получить объект")

        return ServiceResponse(text_body=f"{ENTITIES_MAP[entity]} {obj['name']}")
