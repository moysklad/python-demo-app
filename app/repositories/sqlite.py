from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.domain.app_instance import AppInstance, AppStatus
from app.repositories.models import AccountApplicationRow, Base, JwtRow, SessionRow
from app.security.crypto import decrypt_sensitive, encrypt_sensitive, ensure_private_dir

SQLITE_POOL_SIZE = 5
SQLITE_CONNECTION_CHECKOUT_TIMEOUT_SECONDS = 5.0

# минимальный интервал удаления старых записей
PRUNE_INTERVAL_SECONDS = 60.0
# максимальное число удаляемых старых записей за один запуск
PRUNE_MAX_ROWS_PER_RUN = 1000


def create_sqlite_engine(filename: Path) -> Engine:
    ensure_private_dir(filename.parent)
    engine = create_engine(
        f"sqlite:///{filename}",
        connect_args={"check_same_thread": False},
        pool_size=SQLITE_POOL_SIZE,
        max_overflow=0,
        pool_timeout=SQLITE_CONNECTION_CHECKOUT_TIMEOUT_SECONDS,
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def configure_connection(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()

    Base.metadata.create_all(engine)
    return engine


def create_sqlite_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


class SqliteAppInstanceRepository:
    def __init__(
            self,
            filename: Path,
            encrypt_key: str,
            session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._session_factory = session_factory or create_sqlite_session_factory(create_sqlite_engine(filename))
        self._encrypt_key = encrypt_key

    def load(self, app_id: str, account_id: str) -> AppInstance | None:
        with self._session_factory() as session:
            row = session.get(
                AccountApplicationRow,
                {"account_id": account_id, "application_id": app_id},
            )

        if row is None:
            return None

        return AppInstance(
            app_id=row.application_id,
            account_id=row.account_id,
            info_message=row.info_message or "",
            store=row.store or "",
            access_token=decrypt_sensitive(row.access_token, self._encrypt_key) if row.access_token else "",
            status=_known_status(row.status),
            updated_at=_parse_timestamp_ms(row.updated_at),
        )

    def save(self, app: AppInstance) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        access_token = _nullable(app.access_token)
        values = {
            "account_id": app.account_id,
            "application_id": app.app_id,
            "status": int(app.status),
            "access_token": encrypt_sensitive(access_token, self._encrypt_key) if access_token else None,
            "info_message": _nullable(app.info_message),
            "store": _nullable(app.store),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        statement = insert(AccountApplicationRow).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[AccountApplicationRow.account_id, AccountApplicationRow.application_id],
            set_={
                "status": statement.excluded.status,
                "access_token": statement.excluded.access_token,
                "info_message": statement.excluded.info_message,
                "store": statement.excluded.store,
                "updated_at": statement.excluded.updated_at,
            },
        )

        with self._session_factory.begin() as session:
            session.execute(statement)

    def delete(self, app_id: str, account_id: str) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                delete(AccountApplicationRow).where(
                    AccountApplicationRow.application_id == app_id,
                    AccountApplicationRow.account_id == account_id,
                )
            )


class SqliteJwtReplayRepository:
    def __init__(self, filename: Path, session_factory: sessionmaker[Session] | None = None) -> None:
        self._session_factory = session_factory or create_sqlite_session_factory(create_sqlite_engine(filename))
        self._next_prune_at = 0.0

    def register(self, jti: str, exp_unix_seconds: int) -> bool:
        expires_at_ms = exp_unix_seconds * 1000
        with self._session_factory.begin() as session:
            self._maybe_prune_expired_jti(session)
            cursor = session.execute(
                insert(JwtRow).values(jti=jti, expires_at=expires_at_ms).on_conflict_do_nothing()
            )
            return cursor.rowcount == 1

    def _maybe_prune_expired_jti(self, session: Session) -> None:
        now = time.monotonic()
        if now < self._next_prune_at:
            return

        self._next_prune_at = now + PRUNE_INTERVAL_SECONDS
        expired_jti = select(JwtRow.jti).where(JwtRow.expires_at <= _current_epoch_ms()).limit(PRUNE_MAX_ROWS_PER_RUN)
        session.execute(delete(JwtRow).where(JwtRow.jti.in_(expired_jti)))


class SqliteSessionRepository:
    def __init__(
            self,
            filename: Path,
            encrypt_key: str,
            session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._session_factory = session_factory or create_sqlite_session_factory(create_sqlite_engine(filename))
        self._encrypt_key = encrypt_key
        self._next_prune_at = 0.0

    def load(self, sid: str) -> dict[str, Any] | None:
        with self._session_factory.begin() as session:
            row = session.get(SessionRow, sid)
            if row is None:
                return None

            now_ms = _current_epoch_ms()
            if row.expires_at <= now_ms:
                session.delete(row)
                return None

            return json.loads(decrypt_sensitive(row.session_json, self._encrypt_key))

    def save(self, sid: str, session_data: dict[str, Any], expires_at_ms: int) -> None:
        statement = insert(SessionRow).values(
            sid=sid,
            session_json=encrypt_sensitive(json.dumps(session_data), self._encrypt_key),
            expires_at=expires_at_ms,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[SessionRow.sid],
            set_={
                "session_json": statement.excluded.session_json,
                "expires_at": statement.excluded.expires_at,
            },
        )

        with self._session_factory.begin() as session:
            self._maybe_prune_expired_sessions(session)
            session.execute(statement)

    def delete(self, sid: str) -> None:
        with self._session_factory.begin() as session:
            session.execute(delete(SessionRow).where(SessionRow.sid == sid))

    def _maybe_prune_expired_sessions(self, session: Session) -> None:
        now = time.monotonic()
        if now < self._next_prune_at:
            return

        self._next_prune_at = now + PRUNE_INTERVAL_SECONDS
        expired_sid = (
            select(SessionRow.sid).where(SessionRow.expires_at <= _current_epoch_ms()).limit(PRUNE_MAX_ROWS_PER_RUN)
        )
        session.execute(delete(SessionRow).where(SessionRow.sid.in_(expired_sid)))


def _current_epoch_ms() -> int:
    return int(time.time() * 1000)


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
