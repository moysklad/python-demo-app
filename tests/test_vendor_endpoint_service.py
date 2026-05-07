from __future__ import annotations

from app.domain.app_instance import AppInstance, AppStatus
from app.repositories.memory import MemoryAppInstanceRepository
from app.services.vendor_endpoint import VendorEndpointService


def test_put_app_sets_settings_required_without_store():
    repository = MemoryAppInstanceRepository()
    service = VendorEndpointService(repository)

    response = service.put_app("app-1", "account-1", {"cause": "Install", "access": [{"access_token": "token"}]})
    app = repository.load("app-1", "account-1")

    assert response.json_body == {"status": "SettingsRequired"}
    assert app is not None
    assert app.status == AppStatus.SETTINGS_REQUIRED
    assert app.access_token == "token"


def test_put_app_resume_activates_when_store_exists():
    repository = MemoryAppInstanceRepository()
    repository.save(AppInstance("app-1", "account-1", store="Основной склад", status=AppStatus.SUSPENDED))
    service = VendorEndpointService(repository)

    response = service.put_app("app-1", "account-1", {"cause": "Resume"})

    assert response.json_body == {"status": "Activated"}
    assert repository.load("app-1", "account-1").status == AppStatus.ACTIVATED


def test_delete_app_suspend_clears_token():
    repository = MemoryAppInstanceRepository()
    repository.save(AppInstance("app-1", "account-1", access_token="token", status=AppStatus.ACTIVATED))
    service = VendorEndpointService(repository)

    response = service.delete_app("app-1", "account-1", {"cause": "Suspend"})

    assert response.status_code == 200
    app = repository.load("app-1", "account-1")
    assert app.status == AppStatus.SUSPENDED
    assert app.access_token == ""


def test_delete_app_rejects_unknown_cause():
    repository = MemoryAppInstanceRepository()
    repository.save(AppInstance("app-1", "account-1", status=AppStatus.ACTIVATED))
    service = VendorEndpointService(repository)

    response = service.delete_app("app-1", "account-1", {"cause": "Other"})

    assert response.status_code == 400
    assert response.text_body == "Invalid delete request"
