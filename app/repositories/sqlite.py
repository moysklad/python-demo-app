from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domain.app_instance import AppInstance, AppStatus
from app.security.crypto import decrypt_sensitive, encrypt_sensitive, ensure_private_dir


PRUNE_INTERVAL_MS = 60_000
PRUNE_MAX_ROWS_PER_RUN = 500


def connect_database(filename: Path) -> sqlite3.Connection:
    ensure_private_dir(filename.parent)
    connection = sqlite3.connect(filename, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


class SqliteAppInstanceRepository:
    def __init__(self, filename: Path, encrypt_key: str) -> None:
        self._db = connect_database(filename)
        self._encrypt_key = encrypt_key
        self._db.execute(
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
        self._db.commit()

    def load(self, app_id: str, account_id: str) -> AppInstance | None:
        row = self._db.execute(
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
        self._db.execute(
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
        self._db.commit()

    def delete(self, app_id: str, account_id: str) -> None:
        self._db.execute(
            "DELETE FROM account_application WHERE application_id = ? AND account_id = ?",
            (app_id, account_id),
        )
        self._db.commit()


class SqliteJwtReplayRepository:
    def __init__(self, filename: Path) -> None:
        self._db = connect_database(filename)
        self._last_prune_at = 0
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS jwt (
                jti TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                PRIMARY KEY (jti)
            )
            """
        )
        self._db.commit()

    def register(self, jti: str, exp_unix_seconds: int) -> bool:
        self._maybe_prune_expired_jti()
        cursor = self._db.execute(
            "INSERT OR IGNORE INTO jwt (jti, expires_at) VALUES (?, ?)",
            (jti, exp_unix_seconds * 1000),
        )
        self._db.commit()
        return cursor.rowcount == 1

    def _maybe_prune_expired_jti(self) -> None:
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_prune_at < PRUNE_INTERVAL_MS:
            return

        self._last_prune_at = now_ms
        self._db.execute(
            "DELETE FROM jwt WHERE jti IN (SELECT jti FROM jwt WHERE expires_at <= ? LIMIT ?)",
            (now_ms, PRUNE_MAX_ROWS_PER_RUN),
        )
        self._db.commit()


class SqliteSessionRepository:
    def __init__(self, filename: Path, encrypt_key: str) -> None:
        self._db = connect_database(filename)
        self._encrypt_key = encrypt_key
        self._last_prune_at = 0
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                sid TEXT PRIMARY KEY,
                session_json TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            )
            """
        )
        self._db.commit()

    def load(self, sid: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT session_json, expires_at FROM sessions WHERE sid = ? LIMIT 1",
            (sid,),
        ).fetchone()

        if row is None:
            return None

        now_ms = int(time.time() * 1000)
        if row["expires_at"] <= now_ms:
            self.delete(sid)
            return None

        return json.loads(decrypt_sensitive(row["session_json"], self._encrypt_key))

    def save(self, sid: str, session_data: dict[str, Any], expires_at_ms: int) -> None:
        self._maybe_prune_expired_sessions()
        self._db.execute(
            """
            INSERT INTO sessions (sid, session_json, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(sid) DO UPDATE SET
                session_json = excluded.session_json,
                expires_at = excluded.expires_at
            """,
            (sid, encrypt_sensitive(json.dumps(session_data), self._encrypt_key), expires_at_ms),
        )
        self._db.commit()

    def delete(self, sid: str) -> None:
        self._db.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
        self._db.commit()

    def _maybe_prune_expired_sessions(self) -> None:
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_prune_at < PRUNE_INTERVAL_MS:
            return

        self._last_prune_at = now_ms
        self._db.execute(
            "DELETE FROM sessions WHERE sid IN (SELECT sid FROM sessions WHERE expires_at <= ? LIMIT ?)",
            (now_ms, PRUNE_MAX_ROWS_PER_RUN),
        )
        self._db.commit()


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
