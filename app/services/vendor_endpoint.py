from __future__ import annotations

from typing import Any

from app.domain.app_instance import AppInstance, AppInstanceRepository, AppStatus
from app.logging import log_message
from app.services.buttons import process_document_button_click, process_list_button_click
from app.services.common import ServiceResponse


class VendorEndpointService:
    def __init__(self, app_repository: AppInstanceRepository) -> None:
        self._app_repository = app_repository

    def put_app(self, app_id: str, account_id: str, body: dict[str, Any]) -> ServiceResponse:
        cause = str(body.get("cause", "") or "")
        access_items = body.get("access") if isinstance(body.get("access"), list) else []
        first_access = access_items[0] if access_items else {}
        access_token = str(first_access.get("access_token", "") or "") if isinstance(first_access, dict) else ""
        app = self._load_app(app_id, account_id)
        has_required_settings = app.store.strip() != ""

        if access_token:
            app.access_token = access_token

        if cause == "Resume":
            app.status = AppStatus.ACTIVATED if has_required_settings else AppStatus.SETTINGS_REQUIRED
        elif cause in {"TariffChanged", "Autoprolongation"}:
            pass
        elif app.get_status_name() is None:
            app.status = AppStatus.ACTIVATED if has_required_settings else AppStatus.SETTINGS_REQUIRED

        self._app_repository.save(app)
        status = app.get_status_name()
        log_message("INFO", f"App appId={app_id} installed on accountId={account_id}. Status: {status}")
        return ServiceResponse(json_body={"status": status})

    def delete_app(self, app_id: str, account_id: str, body: dict[str, Any]) -> ServiceResponse:
        app = self._app_repository.load(app_id, account_id) or AppInstance(app_id, account_id)
        if not app.is_installed():
            log_message("INFO", f"App appId={app_id} not installed on accountId={account_id}")
            return ServiceResponse(status_code=204)

        cause = body.get("cause")
        if cause == "Uninstall":
            self._app_repository.delete(app_id, account_id)
            log_message("INFO", f"App appId={app_id} deleted on accountId={account_id}, cause={cause}")
        elif cause == "Suspend":
            app.status = AppStatus.SUSPENDED
            app.access_token = ""
            self._app_repository.save(app)
            log_message("INFO", f"App appId={app_id} suspended on accountId={account_id}, cause={cause}")
        else:
            return ServiceResponse(status_code=400, text_body="Invalid delete request")

        return ServiceResponse(status_code=200)

    def app_event(self, app_id: str, account_id: str, body: dict[str, Any]) -> ServiceResponse:
        app = self._app_repository.load(app_id, account_id) or AppInstance(app_id, account_id)
        if not app.is_installed():
            log_message("INFO", f"App appId={app_id} not installed on accountId={account_id}")
            return ServiceResponse(status_code=204)

        if body.get("cause") == "PermissionsChanged":
            access = body.get("access")
            log_message(
                "INFO",
                f"Permissions changed for appId={app_id} on accountId={account_id}",
                {"accessItems": len(access) if isinstance(access, list) else 0},
            )

        return ServiceResponse(status_code=200)

    def button(self, body: dict[str, Any]) -> ServiceResponse:
        button_name = str(body.get("buttonName", "") or "")
        extension_point = str(body.get("extensionPoint", "") or "")
        object_id = body.get("objectId")
        selected = body.get("selected")

        if button_name and isinstance(object_id, str) and object_id:
            return ServiceResponse(json_body=process_document_button_click(button_name, extension_point, object_id, _dict_or_none(body.get("user"))))

        if button_name == "show-notification" and isinstance(selected, list):
            objects = [item for item in selected if isinstance(item, dict)]
            return ServiceResponse(json_body=process_list_button_click(button_name, extension_point, objects))

        return ServiceResponse(json_body={})

    def _load_app(self, app_id: str, account_id: str) -> AppInstance:
        return self._app_repository.load(app_id, account_id) or AppInstance(app_id, account_id)


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None
