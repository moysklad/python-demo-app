from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Integer, Text, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from app.loyalty.installation import LoyaltyInstallation
from app.repositories.models import Base
from app.security.crypto import decrypt_sensitive, encrypt_sensitive


class LoyaltyInstallationRow(Base):
    __tablename__ = "loyalty_installation"

    application_id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    # Токены зашифрованы APP_ENCRYPT_KEY
    provider_token: Mapped[str | None] = mapped_column(Text)
    external_search: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # NULL: МойСклад не знает о подключении
    connected_at: Mapped[str | None] = mapped_column(Text)
    pending_provider_token: Mapped[str | None] = mapped_column(Text)
    pending_external_search: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class SqliteLoyaltyInstallationRepository:
    def __init__(self, encrypt_key: str, session_factory: sessionmaker[Session]) -> None:
        self._encrypt_key = encrypt_key
        self._session_factory = session_factory

    def load(self, app_id: str, account_id: str) -> LoyaltyInstallation | None:
        with self._session_factory() as session:
            row = session.get(LoyaltyInstallationRow, {"application_id": app_id, "account_id": account_id})

        return None if row is None else self._from_row(row)

    def find_by_token(self, token: str) -> LoyaltyInstallation | None:
        """
        Токен хранится зашифрованным, поэтому искать по нему приходится перебором.
        Для демо это приемлемо; в продакшене храните рядом хеш токена и ищите по нему.
        """
        with self._session_factory() as session:
            rows = session.scalars(select(LoyaltyInstallationRow)).all()

        for row in rows:
            installation = self._from_row(row)
            if installation.accepts_token(token):
                return installation

        return None

    def save(self, installation: LoyaltyInstallation) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        statement = insert(LoyaltyInstallationRow).values(
            application_id=installation.app_id,
            account_id=installation.account_id,
            provider_token=self._encrypt(installation.provider_token),
            external_search=1 if installation.external_search else 0,
            connected_at=installation.connected_at,
            pending_provider_token=self._encrypt(installation.pending_provider_token),
            pending_external_search=1 if installation.pending_external_search else 0,
            created_at=timestamp,
            updated_at=timestamp,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[LoyaltyInstallationRow.application_id, LoyaltyInstallationRow.account_id],
            set_={
                "provider_token": statement.excluded.provider_token,
                "external_search": statement.excluded.external_search,
                "connected_at": statement.excluded.connected_at,
                "pending_provider_token": statement.excluded.pending_provider_token,
                "pending_external_search": statement.excluded.pending_external_search,
                "updated_at": statement.excluded.updated_at,
            },
        )

        with self._session_factory.begin() as session:
            session.execute(statement)

    def _from_row(self, row: LoyaltyInstallationRow) -> LoyaltyInstallation:
        return LoyaltyInstallation(
            app_id=row.application_id,
            account_id=row.account_id,
            provider_token=self._decrypt(row.provider_token),
            external_search=bool(row.external_search),
            connected_at=row.connected_at,
            pending_provider_token=self._decrypt(row.pending_provider_token),
            pending_external_search=bool(row.pending_external_search),
        )

    def _encrypt(self, value: str | None) -> str | None:
        return None if value is None else encrypt_sensitive(value, self._encrypt_key)

    def _decrypt(self, value: str | None) -> str | None:
        return None if value is None else decrypt_sensitive(value, self._encrypt_key)
