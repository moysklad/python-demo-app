from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from app.domain.app_instance import AppInstance, AppStatus
from app.repositories.models import SessionRow
from app.repositories.sqlite import (
    SqliteAppInstanceRepository,
    SqliteJwtReplayRepository,
    SqliteSessionRepository,
    create_sqlite_engine,
    create_sqlite_session_factory,
)


def test_sqlite_session_repository_supports_parallel_saves(app_config):
    repository = SqliteSessionRepository(app_config.app_db_path, app_config.encrypt_key)
    expires_at_ms = int(time.time() * 1000) + 60_000

    def save_session(index: int) -> None:
        repository.save("sid-1", {"value": index}, expires_at_ms)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(save_session, range(50)))

    loaded = repository.load("sid-1")
    assert loaded is not None
    assert loaded["value"] in range(50)


def test_sqlite_app_instance_repository_saves_loads_and_deletes(app_config):
    repository = SqliteAppInstanceRepository(app_config.app_db_path, app_config.encrypt_key)
    app = AppInstance(
        app_id="app-1",
        account_id="account-1",
        info_message="settings",
        store="main",
        access_token="token",
        status=AppStatus.SETTINGS_REQUIRED,
    )

    repository.save(app)
    loaded = repository.load("app-1", "account-1")

    assert loaded == AppInstance(
        app_id="app-1",
        account_id="account-1",
        info_message="settings",
        store="main",
        access_token="token",
        status=AppStatus.SETTINGS_REQUIRED,
        updated_at=loaded.updated_at,
    )
    assert loaded.updated_at > 0

    repository.delete("app-1", "account-1")

    assert repository.load("app-1", "account-1") is None


def test_sqlite_jwt_replay_repository_rejects_duplicate_jti(app_config):
    repository = SqliteJwtReplayRepository(app_config.app_db_path)
    expires_at = int(time.time()) + 60

    # Первый jti сохраняется, а повторная регистрация того же jti считается replay.
    assert repository.register("jti-1", expires_at) is True
    assert repository.register("jti-1", expires_at) is False


def test_sqlite_session_repository_deletes_expired_session_on_load(app_config):
    engine = create_sqlite_engine(app_config.app_db_path)
    session_factory = create_sqlite_session_factory(engine)
    repository = SqliteSessionRepository(app_config.app_db_path, app_config.encrypt_key, session_factory)
    repository.save("sid-1", {"value": "expired"}, int(time.time() * 1000) - 1)

    # load() не должен возвращать истекшую сессию
    assert repository.load("sid-1") is None
    with session_factory() as session:
        # и load() должен удалить устаревшую строку из хранилища
        assert session.get(SessionRow, "sid-1") is None
