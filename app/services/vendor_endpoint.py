from __future__ import annotations

import logging
from typing import Any, Literal, TypedDict

from app.domain.app_instance import AppInstance, AppInstanceRepository, AppStatus
from app.services.buttons import process_document_button_click, process_list_button_click
from app.services.common import ServiceResponse
from app.services.utils import has_required_settings

logger = logging.getLogger(__name__)

ActivationCause = Literal["Install", "Resume", "TariffChanged", "Autoprolongation"]
DeactivationCause = Literal["Uninstall", "Suspend"]
EventCause = Literal["PermissionsChanged"]


class AccessItem(TypedDict, total=False):
    resource: str
    scope: list[str]
    permissions: dict[str, Any]
    access_token: str


class Subscription(TypedDict, total=False):
    tariffId: str
    trial: bool
    tariffName: str
    expiryMoment: str
    notForResale: bool
    partner: bool


class ActivationBody(TypedDict, total=False):
    appUid: str
    accountName: str
    cause: ActivationCause
    access: list[AccessItem]
    subscription: Subscription
    additional: dict[str, Any]


class DeactivationBody(TypedDict, total=False):
    appUid: str
    accountName: str
    cause: DeactivationCause


class AdditionalEventBody(TypedDict, total=False):
    appUid: str
    accountName: str
    cause: EventCause
    access: list[AccessItem]


class VendorButtonBody(TypedDict, total=False):
    buttonName: str
    extensionPoint: str
    objectId: str
    selected: list[dict[str, Any]]
    user: dict[str, Any]


class VendorEndpointService:
    def __init__(self, app_repository: AppInstanceRepository) -> None:
        self._app_repository = app_repository

    def put_app(self, app_id: str, account_id: str, body: ActivationBody) -> ServiceResponse:
        """
        Обработка события активации решения
        :param app_id: ИД решения
        :param account_id: ИД аккаунта
        :param body: тело запроса
        :return: тело ответа
        """
        cause = str(body.get("cause", "") or "")
        access_items = body.get("access") if isinstance(body.get("access"), list) else []
        first_access = access_items[0] if access_items else {}
        access_token = str(first_access.get("access_token", "") or "") if isinstance(first_access, dict) else ""
        app = self._load_app(app_id, account_id)

        if access_token:
            app.access_token = access_token

        if cause == "Install":
            app.status = AppStatus.ACTIVATED if has_required_settings(app) else AppStatus.SETTINGS_REQUIRED
            logger.info("App appId=%s installed on accountId=%s. Status: %s", app_id, account_id, app.status)
        elif cause == "Resume":
            app.status = AppStatus.ACTIVATED if has_required_settings(app) else AppStatus.SETTINGS_REQUIRED
            logger.info("App appId=%s resumed on accountId=%s. Status: %s", app_id, account_id, app.status)
        elif cause in {"TariffChanged", "Autoprolongation"}:
            # При смене и пролонгации тарифа сейчас ничего не делаем.
            # В реальном проекте можно хранить ИД тарифа в БД и обновлять при необходимости
            logger.info("Additional event for appId=%s on accountId=%s. Cause: %s", app_id, account_id, cause)
        else:
            return ServiceResponse(status_code=400, text_body="Invalid install request")

        self._app_repository.save(app)
        status = app.get_status_name()
        return ServiceResponse(json_body={"status": status})

    def delete_app(self, app_id: str, account_id: str, body: DeactivationBody) -> ServiceResponse:
        """
        Обработка события деактивации решения
        :param app_id: ИД решения
        :param account_id: ИД аккаунта
        :param body: тело запроса
        :return: статус обработки
        """
        app = self._app_repository.load(app_id, account_id) or AppInstance(app_id, account_id)
        if not app.is_installed():
            logger.info("App appId=%s not installed on accountId=%s", app_id, account_id)
            return ServiceResponse(status_code=204)

        cause = body.get("cause")
        if cause == "Uninstall":
            self._app_repository.delete(app_id, account_id)
            logger.info("App appId=%s deleted on accountId=%s", app_id, account_id)
        elif cause == "Suspend":
            app.status = AppStatus.SUSPENDED
            app.access_token = ""
            self._app_repository.save(app)
            logger.info("App appId=%s suspended on accountId=%s", app_id, account_id)
        else:
            return ServiceResponse(status_code=400, text_body="Invalid delete request")

        return ServiceResponse(status_code=200)

    def app_event(self, app_id: str, account_id: str, body: AdditionalEventBody) -> ServiceResponse:
        """
        Обработка дополнительных событий
        :param app_id: ИД решения
        :param account_id: ИД аккаунта
        :param body: тело запроса
        :return: статус обработки
        """
        app = self._app_repository.load(app_id, account_id) or AppInstance(app_id, account_id)
        if not app.is_installed():
            logger.info("App appId=%s not installed on accountId=%s", app_id, account_id)
            return ServiceResponse(status_code=204)

        if body.get("cause") == "PermissionsChanged":
            access = body.get("access")
            logger.info(
                "Permissions changed for appId=%s on accountId=%s, %s",
                app_id,
                account_id,
                {"accessItems": len(access) if isinstance(access, list) else 0},
            )

        return ServiceResponse(status_code=200)

    def button(self, app_id: str, account_id: str, body: VendorButtonBody) -> ServiceResponse:
        """
        Обработка нажатия кастомной кнопки
        :param app_id: ИД решения
        :param account_id: ИД аккаунта
        :param body: тело запроса
        :return: тело ответа
        """
        button_name = str(body.get("buttonName", "") or "")
        extension_point = str(body.get("extensionPoint", "") or "")
        object_id = body.get("objectId")
        selected = body.get("selected")

        logger.info("Button clicked for appId=%s on accountId=%s: %s", app_id, account_id, button_name)

        if button_name and isinstance(object_id, str) and object_id:
            return ServiceResponse(json_body=process_document_button_click(button_name, extension_point, object_id,
                                                                           _dict_or_none(body.get("user"))))

        if button_name == "show-notification" and isinstance(selected, list):
            objects = [item for item in selected if isinstance(item, dict)]
            return ServiceResponse(json_body=process_list_button_click(button_name, extension_point, objects))

        return ServiceResponse(json_body={})

    def _load_app(self, app_id: str, account_id: str) -> AppInstance:
        return self._app_repository.load(app_id, account_id) or AppInstance(app_id, account_id)


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None
