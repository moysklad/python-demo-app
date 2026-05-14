from __future__ import annotations

from app.services.user_context import (
    UserContextService,
    check_is_admin,
    load_active_user_context_from_session,
    save_active_user_context_to_session,
)

from tests.conftest import FakeVendorApi


def test_check_is_admin_accepts_all_permission():
    assert check_is_admin({"permissions": {"admin": {"view": "ALL"}}}) is True
    assert check_is_admin({"permissions": {"admin": {"view": "OWN"}}}) is False


def test_active_context_does_not_store_raw_context_key(monkeypatch):
    monkeypatch.setattr("app.services.user_context.secrets.token_urlsafe", lambda _: "nonce-1")
    session = {}

    context = save_active_user_context_to_session(
        session,
        uid="user-1",
        fio="Иванов И.",
        account_id="account-1",
        is_admin=True,
    )

    active = session["userContext"]
    assert context.context_nonce == "nonce-1"
    assert active["contextNonce"] == "nonce-1"
    assert "contextKey" not in active


def test_load_for_entry_reuses_nonce_for_same_backend_identity(monkeypatch):
    tokens = iter(["nonce-1", "nonce-2"])
    monkeypatch.setattr("app.services.user_context.secrets.token_urlsafe", lambda _: next(tokens))
    service = UserContextService(FakeVendorApi())
    session = {}

    first = service.load_for_entry(session, "context-key-1")
    second = service.load_for_entry(session, "context-key-2")

    assert first is not None
    assert second is not None
    assert first.context_nonce == "nonce-1"
    assert second.context_nonce == "nonce-1"
    assert "context-key-1" not in str(session)
    assert "context-key-2" not in str(session)


def test_load_for_entry_rotates_nonce_when_backend_identity_changes(monkeypatch):
    tokens = iter(["nonce-1", "nonce-2"])
    monkeypatch.setattr("app.services.user_context.secrets.token_urlsafe", lambda _: next(tokens))
    vendor_api = FakeVendorApi()
    service = UserContextService(vendor_api)
    session = {}

    first = service.load_for_entry(session, "context-key-1")
    vendor_api.context_response = {
        "uid": "user-2",
        "shortFio": "Петров П.",
        "accountId": "account-1",
        "permissions": {"admin": {"view": "ALL"}},
    }
    second = service.load_for_entry(session, "context-key-2")

    assert first is not None
    assert second is not None
    assert first.context_nonce == "nonce-1"
    assert second.context_nonce == "nonce-2"


def test_resolve_backend_context_requires_active_nonce(monkeypatch):
    monkeypatch.setattr("app.services.user_context.secrets.token_urlsafe", lambda _: "nonce-1")
    service = UserContextService(FakeVendorApi())
    session = {}
    service.load_for_entry(session, "context-key")

    resolved = service.resolve_backend_context(session, "nonce-1")

    assert resolved is not None
    assert resolved.uid == "user-1"
    assert service.resolve_backend_context(session, "old-nonce") is None
    assert service.resolve_backend_context(session, None) is None


def test_expired_active_context_is_removed_from_session():
    session = {
        "userContext": {
            "uid": "user-1",
            "fio": "",
            "accountId": "account-1",
            "isAdmin": True,
            "contextNonce": "nonce-1",
            "createdAt": 1,
            "expiresAt": 1,
        }
    }

    assert load_active_user_context_from_session(session) is None
    assert "userContext" not in session
