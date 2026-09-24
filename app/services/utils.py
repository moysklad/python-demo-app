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


def has_required_settings(app: AppInstance) -> bool:
    """
    Пример проверки для готовности установки решения к работе
    :param app: экземпляр установки решения
    :return: true если решение уже полностью настроено
    """
    return app.store.strip() != ""


def describe_app_status(app: AppInstance) -> dict[str, object]:
    """
    Состояние решения для карточки статуса в основном iframe
    :param app: экземпляр установки решения
    :return: цвет бейджа, заголовок и сохраненные настройки
    """
    is_settings_required = app.status != AppStatus.ACTIVATED
    return {
        "badge": "orange" if is_settings_required else "green",
        "title": "Требуется настройка" if is_settings_required else "Решение готово к работе",
        "showDetails": not is_settings_required,
        "infoMessage": app.info_message or "",
        "store": app.store or "",
    }


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

    def update_settings(self, session_data: dict[str, Any], context_nonce: str | None, info_message: str, store: str) -> ServiceResponse:
        auth_context = self._user_context_service.resolve_backend_context(session_data, context_nonce)
        if not auth_context:
            return ServiceResponse(status_code=401, text_body="Ошибка авторизации: откройте iframe заново.")

        if not auth_context.is_admin:
            return ServiceResponse(status_code=403, text_body="Недостаточно прав")

        normalized_info_message = info_message.strip()
        normalized_store = store.strip()

        app = self._app_repository.load(self._config.app_id, auth_context.account_id) or AppInstance(self._config.app_id, auth_context.account_id)
        app.info_message = normalized_info_message
        app.store = normalized_store
        app.status = AppStatus.ACTIVATED if has_required_settings(app) else AppStatus.SETTINGS_REQUIRED
        logger.debug("App settings updating: %s", app)

        status_updated = self._vendor_api.update_app_status(self._config.app_id, auth_context.account_id, app.get_status_name())
        if not status_updated:
            return ServiceResponse(status_code=502, text_body="Не удалось обновить статус приложения во внешнем Vendor API")

        self._app_repository.save(app)
        logger.info(
            "App settings updated appId=%s accountId=%s status=%s store=%s",
            app.app_id,
            app.account_id,
            app.get_status_name(),
            app.store,
        )

        return ServiceResponse(json_body={"message": "Настройки обновлены", "status": describe_app_status(app)})

    def get_object(self, session_data: dict[str, Any], context_nonce: str | None, entity: str, object_id: str) -> ServiceResponse:
        auth_context = self._user_context_service.resolve_backend_context(session_data, context_nonce)
        if not auth_context:
            return ServiceResponse(status_code=401, text_body="Ошибка авторизации: откройте iframe/виджет заново.")

        if not is_supported_entity(entity):
            return ServiceResponse(status_code=400, text_body="Неподдерживаемая сущность")

        if object_id == "":
            return ServiceResponse(status_code=400, text_body="objectId обязателен")

        app = self._app_repository.load(self._config.app_id, auth_context.account_id) or AppInstance(self._config.app_id, auth_context.account_id)
        obj = self._json_api_factory.create(app.access_token).get_object(entity, object_id)
        if not obj or not obj.get("name"):
            return ServiceResponse(status_code=502, text_body="Не удалось получить объект")

        return ServiceResponse(text_body=f"{ENTITIES_MAP[entity]} {obj['name']}")

    def request_stores(
        self,
        session_data: dict[str, Any],
        context_nonce: str | None,
    ) -> ServiceResponse:
        auth_context = self._user_context_service.resolve_backend_context(session_data, context_nonce)
        if not auth_context:
            return ServiceResponse(status_code=401, text_body="Ошибка авторизации: откройте iframe заново.")

        if not auth_context.is_admin:
            return ServiceResponse(status_code=403, text_body="Недостаточно прав")

        app = self._app_repository.load(self._config.app_id, auth_context.account_id) or AppInstance(
            self._config.app_id,
            auth_context.account_id,
        )
        stores, retries = self._json_api_factory.create(app.access_token).stores_with_retries()
        successful = stores is not None
        return ServiceResponse(
            status_code=200 if successful else 502,
            json_body={
                "message": "Запрос выполнен" if successful else "Не удалось получить список складов",
                "success": successful,
                "retries": retries,
            },
        )
