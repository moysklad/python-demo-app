"""Интеграционный тест: PostgreSQL-хранилища установок и server-side сессий, миграции схемы."""

from __future__ import annotations

import time

from sqlalchemy import text

from app.domain.app_instance import AppInstance, AppStatus
from app.repositories.migrations import MIGRATIONS_DIR, apply_migrations
from app.repositories.models import SessionRow
from app.repositories.postgres import (
    PostgresAppInstanceRepository,
    PostgresJwtReplayRepository,
    PostgresSessionRepository,
    create_session_factory,
)


def test_migrations_create_schema_once_and_are_idempotent(app_config, db_engine):
    # Фикстура db_engine уже применила все SQL-файлы, повторный запуск ничего не применяет.
    assert apply_migrations(db_engine, app_config.db_schema) == []
    with db_engine.connect() as connection:
        versions = set(connection.scalars(text("select version from schema_migrations")))
        tables = set(connection.scalars(text(
            "select table_name from information_schema.tables where table_schema = :schema"
        ), {"schema": app_config.db_schema}))
    assert versions == {path.stem for path in MIGRATIONS_DIR.glob("*.sql")}
    assert {"schema_migrations", "account_application", "sessions", "jwt"} <= tables


def test_migrations_accept_reserved_word_as_schema_name(db_engine):
    # APP_NAME=order дает схему order: имя должно попадать в SQL как идентификатор в кавычках.
    try:
        apply_migrations(db_engine, "order")
    finally:
        with db_engine.begin() as connection:
            connection.execute(text('drop schema if exists "order" cascade'))


def test_postgres_app_instance_repository_saves_loads_and_deletes(app_config, db_engine):
    # Smoke-test: одна запись должна спокойно сохраняться, читаться и удаляться в PostgreSQL.
    repository = PostgresAppInstanceRepository(create_session_factory(db_engine), app_config.encrypt_key)
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


def test_postgres_session_repository_deletes_expired_session_on_load(app_config, db_engine):
    # Истекшая server-side session должна удаляться при чтении, а не возвращаться наружу.
    session_factory = create_session_factory(db_engine)
    repository = PostgresSessionRepository(session_factory, app_config.encrypt_key)
    repository.save("sid-1", {"value": "expired"}, int(time.time() * 1000) - 1)

    # load() не должен возвращать истекшую сессию
    assert repository.load("sid-1") is None
    with session_factory() as session:
        # и load() должен удалить устаревшую строку из хранилища
        assert session.get(SessionRow, "sid-1") is None


def test_postgres_repositories_treat_data_of_another_encrypt_key_as_missing(app_config, db_engine):
    # После смены APP_ENCRYPT_KEY старые токен и сессия не расшифровываются: решение должно дожить до переустановки, а не отвечать 500.
    session_factory = create_session_factory(db_engine)
    other_key = "0" * 64
    assert other_key != app_config.encrypt_key
    PostgresAppInstanceRepository(session_factory, other_key).save(
        AppInstance(app_id="app-1", account_id="account-1", access_token="token", status=AppStatus.ACTIVATED)
    )
    PostgresSessionRepository(session_factory, other_key).save("sid-1", {"value": "old"}, int(time.time() * 1000) + 60_000)

    loaded = PostgresAppInstanceRepository(session_factory, app_config.encrypt_key).load("app-1", "account-1")

    assert loaded is not None
    assert loaded.access_token == ""
    assert PostgresSessionRepository(session_factory, app_config.encrypt_key).load("sid-1") is None


def test_saving_with_another_encrypt_key_keeps_unreadable_access_token(app_config, db_engine):
    # Ключ подменили по ошибке: сохранение настроек не должно затереть токен, после возврата ключа он снова читается.
    session_factory = create_session_factory(db_engine)
    original = PostgresAppInstanceRepository(session_factory, "0" * 64)
    current = PostgresAppInstanceRepository(session_factory, app_config.encrypt_key)
    original.save(AppInstance(app_id="app-1", account_id="account-1", access_token="token", status=AppStatus.ACTIVATED))

    loaded = current.load("app-1", "account-1")
    assert loaded is not None
    loaded.info_message = "changed"
    current.save(loaded)

    restored = original.load("app-1", "account-1")
    assert restored is not None
    assert restored.access_token == "token"
    assert restored.info_message == "changed"

    loaded.access_token = "token-new"
    current.save(loaded)
    reinstalled = current.load("app-1", "account-1")
    assert reinstalled is not None
    assert reinstalled.access_token == "token-new"


def test_postgres_jwt_replay_repository_accepts_jti_once(db_engine):
    # Первый jti принимается, повтор того же jti отклоняется как replay.
    repository = PostgresJwtReplayRepository(create_session_factory(db_engine))
    expires_at = int(time.time()) + 300

    assert repository.register("jti-1", expires_at) is True
    assert repository.register("jti-1", expires_at) is False
    assert repository.register("jti-2", expires_at) is True
