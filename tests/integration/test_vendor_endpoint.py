"""Интеграционный тест: жизненный цикл решения и callbacks через Vendor endpoint."""

from __future__ import annotations

from app.domain.app_instance import AppInstance, AppStatus

from tests.conftest import create_client, vendor_auth_header
from tests.memory_repositories import MemoryAppInstanceRepository

APP_URL = "/api/moysklad/vendor/1.0/apps/app-1/account-1"


def test_vendor_endpoint_requires_fresh_service_jwt(app_config):
    app_repository = MemoryAppInstanceRepository()
    client = create_client(app_config, app_repository=app_repository)
    headers = vendor_auth_header(app_config.secret_key, jti="jti-install")
    body = {"cause": "Install", "access": [{"access_token": "token"}]}

    assert client.put(APP_URL, json=body).status_code == 401

    installed = client.put(APP_URL, headers=headers, json=body)
    replayed = client.put(APP_URL, headers=headers, json=body)

    assert installed.status_code == 200
    assert installed.get_json() == {"status": "SettingsRequired"}
    assert app_repository.load("app-1", "account-1").access_token == "token"
    assert replayed.status_code == 401


def test_suspend_and_resume_keep_settings(app_config):
    app_repository = MemoryAppInstanceRepository()
    app_repository.save(AppInstance("app-1", "account-1", store="Основной склад", access_token="token", status=AppStatus.ACTIVATED))
    client = create_client(app_config, app_repository=app_repository)

    suspend = client.delete(APP_URL, headers=vendor_auth_header(app_config.secret_key, jti="jti-suspend"), json={"cause": "Suspend"})
    suspended = app_repository.load("app-1", "account-1")
    repeated_suspend = client.delete(APP_URL, headers=vendor_auth_header(app_config.secret_key, jti="jti-suspend-2"), json={"cause": "Suspend"})
    resume = client.put(APP_URL, headers=vendor_auth_header(app_config.secret_key, jti="jti-resume"), json={"cause": "Resume", "access": [{"access_token": "token-2"}]})
    resumed = app_repository.load("app-1", "account-1")

    assert suspend.status_code == 200
    assert suspended.status == AppStatus.SUSPENDED
    assert suspended.access_token == ""
    assert suspended.store == "Основной склад"
    # Повторный DELETE для уже приостановленного решения — 204, как требует Vendor API.
    assert repeated_suspend.status_code == 204
    assert resume.get_json() == {"status": "Activated"}
    assert resumed.status == AppStatus.ACTIVATED
    assert resumed.access_token == "token-2"


def test_uninstall_keeps_settings_and_reinstall_restores_them(app_config):
    app_repository = MemoryAppInstanceRepository()
    app_repository.save(AppInstance("app-1", "account-1", store="Основной склад", access_token="token", status=AppStatus.ACTIVATED))
    client = create_client(app_config, app_repository=app_repository)

    uninstall = client.delete(APP_URL, headers=vendor_auth_header(app_config.secret_key, jti="jti-uninstall"), json={"cause": "Uninstall"})
    uninstalled = app_repository.load("app-1", "account-1")
    repeated_uninstall = client.delete(APP_URL, headers=vendor_auth_header(app_config.secret_key, jti="jti-uninstall-2"), json={"cause": "Uninstall"})
    unknown_cause = client.delete(APP_URL, headers=vendor_auth_header(app_config.secret_key, jti="jti-unknown"), json={"cause": "Pause"})
    install = client.put(APP_URL, headers=vendor_auth_header(app_config.secret_key, jti="jti-reinstall"), json={"cause": "Install", "access": [{"access_token": "token-new"}]})
    reinstalled = app_repository.load("app-1", "account-1")

    assert uninstall.status_code == 200
    assert uninstalled.status == AppStatus.UNINSTALLED
    assert uninstalled.access_token == ""
    assert repeated_uninstall.status_code == 204
    assert unknown_cause.status_code == 400
    assert install.get_json() == {"status": "Activated"}
    assert reinstalled.store == "Основной склад"
    assert reinstalled.access_token == "token-new"


def test_app_event_and_button_callbacks(app_config):
    app_repository = MemoryAppInstanceRepository()
    app_repository.save(AppInstance("app-1", "account-1", status=AppStatus.ACTIVATED))
    client = create_client(app_config, app_repository=app_repository)

    event = client.put(f"{APP_URL}/event", headers=vendor_auth_header(app_config.secret_key, jti="jti-event"), json={"cause": "PermissionsChanged"})
    document_button = client.post(
        f"{APP_URL}/button",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-button-doc"),
        json={"buttonName": "show-popup", "extensionPoint": "customerorder", "objectId": "object-1", "user": {"role": "admin"}},
    )
    list_button = client.post(
        f"{APP_URL}/button",
        headers=vendor_auth_header(app_config.secret_key, jti="jti-button-list"),
        json={"buttonName": "show-notification", "extensionPoint": "customerorder", "selected": [{"id": "object-1"}, {"id": "object-2"}]},
    )

    assert event.status_code == 200
    assert document_button.get_json()["action"] == "showPopup"
    assert list_button.get_json()["action"] == "showNotification"
