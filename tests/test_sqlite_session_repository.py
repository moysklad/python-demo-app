from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from app.repositories.sqlite import SqliteSessionRepository


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
