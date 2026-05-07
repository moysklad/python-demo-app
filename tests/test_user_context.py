from __future__ import annotations

from app.services.user_context import (
    USER_CONTEXT_STACK_LIMIT,
    check_is_admin,
    load_user_context_from_session,
    save_user_context_to_session,
)


def test_check_is_admin_accepts_all_permission():
    assert check_is_admin({"permissions": {"admin": {"view": "ALL"}}}) is True
    assert check_is_admin({"permissions": {"admin": {"view": "OWN"}}}) is False


def test_context_bucket_keeps_latest_contexts_only():
    session = {}

    for index in range(USER_CONTEXT_STACK_LIMIT + 2):
        save_user_context_to_session(
            session,
            f"context-{index}",
            uid=f"user-{index}",
            fio="",
            account_id="account-1",
            is_admin=True,
        )

    bucket = session["userContext"]
    assert len(bucket["contextKeyStack"]) == USER_CONTEXT_STACK_LIMIT
    assert "context-0" not in bucket["byContextKey"]
    assert load_user_context_from_session(session, f"context-{USER_CONTEXT_STACK_LIMIT + 1}").uid == f"user-{USER_CONTEXT_STACK_LIMIT + 1}"
