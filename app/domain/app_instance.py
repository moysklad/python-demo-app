from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol


class AppStatus(IntEnum):
    UNKNOWN = 0
    SETTINGS_REQUIRED = 1
    SUSPENDED = 2
    ACTIVATED = 3


@dataclass
class AppInstance:
    app_id: str
    account_id: str
    info_message: str = ""
    store: str = ""
    access_token: str = ""
    status: AppStatus = AppStatus.UNKNOWN
    updated_at: int = 0

    def get_status_name(self) -> str | None:
        if self.status == AppStatus.SETTINGS_REQUIRED:
            return "SettingsRequired"
        if self.status == AppStatus.ACTIVATED:
            return "Activated"
        return None

    def is_installed(self) -> bool:
        return self.status != AppStatus.UNKNOWN


class AppInstanceRepository(Protocol):
    def load(self, app_id: str, account_id: str) -> AppInstance | None:
        ...

    def save(self, app: AppInstance) -> None:
        ...

    def delete(self, app_id: str, account_id: str) -> None:
        ...
