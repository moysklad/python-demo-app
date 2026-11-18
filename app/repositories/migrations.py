from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import OperationalError

from app.config import AppConfig

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DB_SCHEMA_RE = re.compile(r"[a-z_][a-z0-9_]*")

POOL_SIZE = 5
CONNECTION_CHECKOUT_TIMEOUT_SECONDS = 5.0
CONNECT_TIMEOUT_SECONDS = 5
# сколько ждать базу на старте: в docker compose PostgreSQL стартует одновременно с приложением
STARTUP_CONNECT_ATTEMPTS = 30
STARTUP_CONNECT_RETRY_SECONDS = 1.0


def create_postgres_engine(config: AppConfig) -> Engine:
    """CLI-утилиты (дескриптор, JWT) базу не трогают, поэтому параметры подключения проверяются здесь, а не в load_config()."""
    missing = [
        name
        for name, value in (("APP_DB_HOST", config.db_host), ("APP_DB_NAME", config.db_name), ("APP_DB_USER", config.db_user))
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required database config: {', '.join(missing)}")
    if not DB_SCHEMA_RE.fullmatch(config.db_schema):
        raise ValueError("APP_DB_SCHEMA must be a lowercase identifier: letters, digits and underscores")

    url = URL.create(
        "postgresql+psycopg",
        username=config.db_user,
        password=config.db_password,
        host=config.db_host,
        port=config.db_port,
        database=config.db_name,
    )
    return create_engine(
        url,
        connect_args={
            "options": f"-c search_path={config.db_schema},public",
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
        },
        pool_size=POOL_SIZE,
        max_overflow=0,
        pool_timeout=CONNECTION_CHECKOUT_TIMEOUT_SECONDS,
        pool_pre_ping=True,
    )


def apply_migrations(engine: Engine, schema: str) -> list[str]:
    """
    Создает схему решения и применяет SQL-файлы из migrations/ по порядку имен.
    Под advisory lock, чтобы параллельно стартующие экземпляры не мешали друг другу.
    """
    applied: list[str] = []
    with engine.begin() as connection:
        connection.execute(text("select pg_advisory_xact_lock(hashtext(:schema))"), {"schema": schema})
        connection.execute(text(f'create schema if not exists "{schema}"'))
        connection.execute(
            text(
                "create table if not exists schema_migrations ("
                "version text primary key, applied_at timestamptz not null default now())"
            )
        )
        known = set(connection.scalars(text("select version from schema_migrations")).all())
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.stem
            if version in known:
                continue
            connection.exec_driver_sql(path.read_text(encoding="utf-8"))
            connection.execute(text("insert into schema_migrations (version) values (:version)"), {"version": version})
            applied.append(version)

    if applied:
        logger.info("Applied database migrations in schema %s: %s", schema, ", ".join(applied))
    return applied


def wait_for_database(engine: Engine) -> None:
    for attempt in range(1, STARTUP_CONNECT_ATTEMPTS):
        try:
            with engine.connect():
                return
        except OperationalError as error:
            logger.warning("Database is not ready (attempt %s/%s): %s", attempt, STARTUP_CONNECT_ATTEMPTS, error)
            time.sleep(STARTUP_CONNECT_RETRY_SECONDS)
    with engine.connect():
        return
