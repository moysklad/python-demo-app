from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from queue import Empty, LifoQueue
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domain.app_instance import AppInstance, AppStatus
from app.security.crypto import decrypt_sensitive, encrypt_sensitive, ensure_private_dir


PRUNE_INTERVAL_MS = 60_000
PRUNE_MAX_ROWS_PER_RUN = 500
SQLITE_POOL_SIZE = 5
SQLITE_CONNECTION_CHECKOUT_TIMEOUT_SECONDS = 5.0


def connect_database(filename: Path) -> sqlite3.Connection:
    ensure_private_dir(filename.parent)
    connection = sqlite3.connect(filename, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


class SqliteConnectionPool:
    def __init__(
        self,
        filename: Path,
        size: int = SQLITE_POOL_SIZE,
        checkout_timeout_seconds: float = SQLITE_CONNECTION_CHECKOUT_TIMEOUT_SECONDS,
    ) -> None:
        self._checkout_timeout_seconds = checkout_timeout_seconds
        self._connections: LifoQueue[sqlite3.Connection] = LifoQueue(maxsize=size)
        for _ in range(size):
            self._connections.put(connect_database(filename))

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = self._connections.get(timeout=self._checkout_timeout_seconds)
        except Empty as error:
            raise SqliteConnectionPoolExhausted("SQLite connection pool exhausted") from error

        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        finally:
            self._connections.put(connection)

    def close(self) -> None:
        while not self._connections.empty():
            self._connections.get_nowait().close()


class SqliteConnectionPoolExhausted(RuntimeError):
    pass


class SqliteAppInstanceRepository:
    def __init__(self, filename: Path, encrypt_key: str, pool: SqliteConnectionPool | None = None) -> None:
        self._pool = pool or SqliteConnectionPool(filename)
        self._encrypt_key = encrypt_key
        with self._pool.connection() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS account_application (
                    account_id TEXT NOT NULL,
                    application_id TEXT NOT NULL,
                    status INTEGER,
                    access_token TEXT,
                    info_message TEXT,
                    store TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, application_id)
                )
                """
            )
            db.commit()

    def load(self, app_id: str, account_id: str) -> AppInstance | None:
        with self._pool.connection() as db:
            row = db.execute(
                """
                SELECT application_id, account_id, info_message, store, access_token, status, updated_at
                FROM account_application
                WHERE application_id = ? AND account_id = ?
                LIMIT 1
                """,
                (app_id, account_id),
            ).fetchone()

        if row is None:
            return None

        return AppInstance(
            app_id=row["application_id"],
            account_id=row["account_id"],
            info_message=row["info_message"] or "",
            store=row["store"] or "",
            access_token=decrypt_sensitive(row["access_token"], self._encrypt_key) if row["access_token"] else "",
            status=_known_status(row["status"]),
            updated_at=_parse_timestamp_ms(row["updated_at"]),
        )

    def save(self, app: AppInstance) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        access_token = _nullable(app.access_token)
        with self._pool.connection() as db:
            db.execute(
                """
                INSERT INTO account_application (
                    account_id, application_id, status, access_token, info_message, store, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, application_id) DO UPDATE SET
                    status = excluded.status,
                    access_token = excluded.access_token,
                    info_message = excluded.info_message,
                    store = excluded.store,
                    updated_at = excluded.updated_at
                """,
                (
                    app.account_id,
                    app.app_id,
                    int(app.status),
                    encrypt_sensitive(access_token, self._encrypt_key) if access_token else None,
                    _nullable(app.info_message),
                    _nullable(app.store),
                    timestamp,
                    timestamp,
                ),
            )
            db.commit()

    def delete(self, app_id: str, account_id: str) -> None:
        with self._pool.connection() as db:
            db.execute(
                "DELETE FROM account_application WHERE application_id = ? AND account_id = ?",
                (app_id, account_id),
            )
            db.commit()


class SqliteJwtReplayRepository:
    def __init__(self, filename: Path, pool: SqliteConnectionPool | None = None) -> None:
        self._pool = pool or SqliteConnectionPool(filename)
        self._last_prune_at = 0
        with self._pool.connection() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS jwt (
                    jti TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    PRIMARY KEY (jti)
                )
                """
            )
            db.commit()

    def register(self, jti: str, exp_unix_seconds: int) -> bool:
        with self._pool.connection() as db:
            self._maybe_prune_expired_jti(db)
            cursor = db.execute(
                "INSERT OR IGNORE INTO jwt (jti, expires_at) VALUES (?, ?)",
                (jti, exp_unix_seconds * 1000),
            )
            db.commit()
            return cursor.rowcount == 1

    def _maybe_prune_expired_jti(self, db: sqlite3.Connection) -> None:
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_prune_at < PRUNE_INTERVAL_MS:
            return

        self._last_prune_at = now_ms
        db.execute(
            "DELETE FROM jwt WHERE jti IN (SELECT jti FROM jwt WHERE expires_at <= ? LIMIT ?)",
            (now_ms, PRUNE_MAX_ROWS_PER_RUN),
        )
        db.commit()


class SqliteSessionRepository:
    def __init__(self, filename: Path, encrypt_key: str, pool: SqliteConnectionPool | None = None) -> None:
        self._pool = pool or SqliteConnectionPool(filename)
        self._encrypt_key = encrypt_key
        self._last_prune_at = 0
        with self._pool.connection() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    sid TEXT PRIMARY KEY,
                    session_json TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            db.commit()

    def load(self, sid: str) -> dict[str, Any] | None:
        with self._pool.connection() as db:
            row = db.execute(
                "SELECT session_json, expires_at FROM sessions WHERE sid = ? LIMIT 1",
                (sid,),
            ).fetchone()

            if row is None:
                return None

            now_ms = int(time.time() * 1000)
            if row["expires_at"] <= now_ms:
                db.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
                db.commit()
                return None

            return json.loads(decrypt_sensitive(row["session_json"], self._encrypt_key))

    def save(self, sid: str, session_data: dict[str, Any], expires_at_ms: int) -> None:
        with self._pool.connection() as db:
            self._maybe_prune_expired_sessions(db)
            db.execute(
                """
                INSERT INTO sessions (sid, session_json, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(sid) DO UPDATE SET
                    session_json = excluded.session_json,
                    expires_at = excluded.expires_at
                """,
                (sid, encrypt_sensitive(json.dumps(session_data), self._encrypt_key), expires_at_ms),
            )
            db.commit()

    def delete(self, sid: str) -> None:
        with self._pool.connection() as db:
            db.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
            db.commit()

    def _maybe_prune_expired_sessions(self, db: sqlite3.Connection) -> None:
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_prune_at < PRUNE_INTERVAL_MS:
            return

        self._last_prune_at = now_ms
        db.execute(
            "DELETE FROM sessions WHERE sid IN (SELECT sid FROM sessions WHERE expires_at <= ? LIMIT ?)",
            (now_ms, PRUNE_MAX_ROWS_PER_RUN),
        )
        db.commit()


def _nullable(value: str) -> str | None:
    normalized = value.strip()
    return normalized or None


def _known_status(value: Any) -> AppStatus:
    try:
        return AppStatus(int(value))
    except (TypeError, ValueError):
        return AppStatus.UNKNOWN


def _parse_timestamp_ms(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1000)
    except ValueError:
        return 0
