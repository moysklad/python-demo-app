from __future__ import annotations

from app.domain.app_instance import AppInstance


class MemoryAppInstanceRepository:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], AppInstance] = {}

    def load(self, app_id: str, account_id: str) -> AppInstance | None:
        app = self.items.get((app_id, account_id))
        if app is None:
            return None
        return AppInstance(**app.__dict__)

    def save(self, app: AppInstance) -> None:
        self.items[(app.app_id, app.account_id)] = AppInstance(**app.__dict__)

    def delete(self, app_id: str, account_id: str) -> None:
        self.items.pop((app_id, account_id), None)


class MemoryJwtReplayRepository:
    def __init__(self) -> None:
        self.items: set[str] = set()

    def register(self, jti: str, exp_unix_seconds: int) -> bool:
        if jti in self.items:
            return False
        self.items.add(jti)
        return True
