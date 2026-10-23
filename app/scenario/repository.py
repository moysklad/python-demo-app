from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Integer, Text, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from app.repositories.models import Base
from app.scenario.events import SCENARIO_EVENTS_LIMIT, ScenarioEvent


class ScenarioEventRow(Base):
    __tablename__ = "scenario_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    action_name: Mapped[str] = mapped_column(Text, nullable=False)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_id: Mapped[str] = mapped_column(Text, nullable=False)
    object_name: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class SqliteScenarioEventRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, event: ScenarioEvent) -> None:
        """Пишет событие и оставляет на аккаунте только последние SCENARIO_EVENTS_LIMIT записей."""
        row = ScenarioEventRow(
            application_id=event.app_id,
            account_id=event.account_id,
            action_name=event.action_name,
            action_type=event.action_type,
            object_type=event.object_type,
            object_id=event.object_id,
            object_name=event.object_name or None,
            outcome=event.outcome,
            message=event.message or None,
            created_at=event.created_at or datetime.now(timezone.utc).isoformat(),
        )
        with self._session_factory.begin() as session:
            session.add(row)
            session.flush()
            event.id = row.id
            event.created_at = row.created_at

            keep_ids = select(ScenarioEventRow.id).where(
                ScenarioEventRow.application_id == event.app_id,
                ScenarioEventRow.account_id == event.account_id,
            ).order_by(ScenarioEventRow.id.desc()).limit(SCENARIO_EVENTS_LIMIT)
            session.execute(
                delete(ScenarioEventRow).where(
                    ScenarioEventRow.application_id == event.app_id,
                    ScenarioEventRow.account_id == event.account_id,
                    ScenarioEventRow.id.not_in(keep_ids),
                )
            )

    def list_recent(self, app_id: str, account_id: str, limit: int = SCENARIO_EVENTS_LIMIT) -> list[ScenarioEvent]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(ScenarioEventRow)
                .where(ScenarioEventRow.application_id == app_id, ScenarioEventRow.account_id == account_id)
                .order_by(ScenarioEventRow.id.desc())
                .limit(limit)
            ).all()

        return [
            ScenarioEvent(
                id=row.id,
                app_id=row.application_id,
                account_id=row.account_id,
                action_name=row.action_name,
                action_type=row.action_type,
                object_type=row.object_type,
                object_id=row.object_id,
                object_name=row.object_name or "",
                outcome=row.outcome,  # type: ignore[arg-type]
                message=row.message or "",
                created_at=row.created_at,
            )
            for row in rows
        ]
