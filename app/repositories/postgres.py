from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidTag
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.domain.app_instance import AppInstance, AppStatus
from app.repositories.models import AccountApplicationRow, JwtRow, SessionRow
from app.security.crypto import decrypt_sensitive, encrypt_sensitive

logger = logging.getLogger(__name__)

# минимальный интервал удаления старых записей
PRUNE_INTERVAL_SECONDS = 60.0
# максимальное число удаляемых старых записей за один запуск
PRUNE_MAX_ROWS_PER_RUN = 1000


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


class PostgresAppInstanceRepository:
    def __init__(self, session_factory: sessionmaker[Session], encrypt_key: str) -> None:
        self._session_factory = session_factory
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
            access_token=self._decrypt_access_token(row),
            status=_known_status(row.status),
            updated_at=_parse_timestamp_ms(row.updated_at),
        )

    def _decrypt_access_token(self, row: AccountApplicationRow) -> str:
        if not row.access_token:
            return ""
        try:
            return decrypt_sensitive(row.access_token, self._encrypt_key)
        except InvalidTag:
            logger.warning(
                "Access token of app %s on account %s is encrypted with another APP_ENCRYPT_KEY, treating it as missing",
                row.application_id,
                row.account_id,
            )
            return ""

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
                "access_token": AccountApplicationRow.access_token
                if access_token is None and self._has_unreadable_access_token(app)
                else statement.excluded.access_token,
                "info_message": statement.excluded.info_message,
                "store": statement.excluded.store,
                "updated_at": statement.excluded.updated_at,
            },
        )

        with self._session_factory.begin() as session:
            session.execute(statement)

    def _has_unreadable_access_token(self, app: AppInstance) -> bool:
        # Токен, зашифрованный другим APP_ENCRYPT_KEY, читается как отсутствующий. Сохранение без нового токена
        # не должно затирать его шифротекст: ключ могли подменить по ошибке, после возврата токен снова прочитается.
        with self._session_factory() as session:
            row = session.get(AccountApplicationRow, {"account_id": app.account_id, "application_id": app.app_id})

        return row is not None and bool(row.access_token) and self._decrypt_access_token(row) == ""

    def uninstall(self, app_id: str, account_id: str) -> None:
        """
        Помечает установку удаленной, сохраняя пользовательские настройки.
        Токен доступа стирается: при повторной установке МойСклад пришлет новый.
        """
        with self._session_factory.begin() as session:
            session.execute(
                update(AccountApplicationRow)
                .where(
                    AccountApplicationRow.application_id == app_id,
                    AccountApplicationRow.account_id == account_id,
                )
                .values(
                    status=int(AppStatus.UNINSTALLED),
                    access_token=None,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
            )

    def delete(self, app_id: str, account_id: str) -> None:
        """
        Полностью удаляет установку вместе с настройками.
        Используйте вместо uninstall(), если политика хранения данных требует удалять
        пользовательские настройки при отключении решения от аккаунта.
        """
        with self._session_factory.begin() as session:
            session.execute(
                delete(AccountApplicationRow).where(
                    AccountApplicationRow.application_id == app_id,
                    AccountApplicationRow.account_id == account_id,
                )
            )


class PostgresJwtReplayRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._next_prune_at = 0.0

    def register(self, jti: str, exp_unix_seconds: int) -> bool:
        expires_at_ms = exp_unix_seconds * 1000
        with self._session_factory.begin() as session:
            self._maybe_prune_expired_jti(session)
            inserted = session.execute(
                insert(JwtRow).values(jti=jti, expires_at=expires_at_ms).on_conflict_do_nothing().returning(JwtRow.jti)
            ).first()
            return inserted is not None

    def _maybe_prune_expired_jti(self, session: Session) -> None:
        now = time.monotonic()
        if now < self._next_prune_at:
            return

        self._next_prune_at = now + PRUNE_INTERVAL_SECONDS
        expired_jti = select(JwtRow.jti).where(JwtRow.expires_at <= _current_epoch_ms()).limit(PRUNE_MAX_ROWS_PER_RUN)
        session.execute(delete(JwtRow).where(JwtRow.jti.in_(expired_jti)))


class PostgresSessionRepository:
    def __init__(self, session_factory: sessionmaker[Session], encrypt_key: str) -> None:
        self._session_factory = session_factory
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

            try:
                return json.loads(decrypt_sensitive(row.session_json, self._encrypt_key))
            except InvalidTag:
                logger.warning("Session is encrypted with another APP_ENCRYPT_KEY, treating it as missing")
                return None

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
