from __future__ import annotations

from app.services.user_context import (
    UserContextService,
    load_active_user_context_from_session,
    role_to_is_admin,
    save_active_user_context_to_session,
)
from app.web.session import ServerSideSession

from tests.conftest import FakeVendorApi


def active_context(expires_at: int, created_at: int = 0) -> dict:
    return {
        "userContext": {
            "uid": "user-1",
            "fio": "Иванов И.",
            "accountId": "account-1",
            "isAdmin": True,
            "contextNonce": "nonce-1",
            "createdAt": created_at,
            "expiresAt": expires_at,
        }
    }


def test_active_context_keeps_nonce_for_same_identity_and_rotates_it_on_change(monkeypatch):
    tokens = iter(["nonce-1", "nonce-2"])
    monkeypatch.setattr("app.services.user_context.secrets.token_urlsafe", lambda _: next(tokens))
    session = {}

    first = save_active_user_context_to_session(session, uid="user-1", fio="", account_id="account-1", is_admin=True)
    same = save_active_user_context_to_session(session, uid="user-1", fio="", account_id="account-1", is_admin=True)
    changed = save_active_user_context_to_session(session, uid="user-1", fio="", account_id="account-1", is_admin=False)

    assert first.context_nonce == same.context_nonce == "nonce-1"
    assert changed.context_nonce == "nonce-2"
    assert session["userContext"]["contextNonce"] == "nonce-2"
    assert "contextKey" not in session["userContext"]


def test_resolve_backend_context_requires_matching_nonce(monkeypatch):
    monkeypatch.setattr("app.services.user_context.time.time", lambda: 1000.0)
    service = UserContextService(FakeVendorApi())
    session = active_context(expires_at=2_000_000)

    resolved = service.resolve_backend_context(session, "nonce-1")

    assert resolved is not None
    assert resolved.uid == "user-1"
    assert resolved.account_id == "account-1"
    assert service.resolve_backend_context(session, "old-nonce") is None
    assert service.resolve_backend_context(session, None) is None
    assert service.resolve_backend_context({}, "nonce-1") is None


def test_resolve_backend_context_refreshes_ttl_at_most_once_per_interval(monkeypatch):
    # Чужой nonce TTL не продлевает, свой продлевает не чаще раза в пять минут, и только тогда сессия помечается modified.
    service = UserContextService(FakeVendorApi())
    session = ServerSideSession(active_context(expires_at=7_200_000))

    monkeypatch.setattr("app.services.user_context.time.time", lambda: 100.0)
    assert service.resolve_backend_context(session, "wrong-nonce") is None
    assert service.resolve_backend_context(session, "nonce-1") is not None
    assert session["userContext"]["expiresAt"] == 7_200_000
    assert session.modified is False

    monkeypatch.setattr("app.services.user_context.time.time", lambda: 300.0)
    assert service.resolve_backend_context(session, "nonce-1") is not None
    assert session["userContext"]["expiresAt"] == 7_500_000
    assert session.modified is True


def test_expired_active_context_is_removed_from_session():
    session = active_context(expires_at=1, created_at=1)

    assert load_active_user_context_from_session(session) is None
    assert "userContext" not in session


def test_load_for_entry_exchanges_context_key_without_storing_it(monkeypatch):
    # Мобильный iframe получает контекст по contextKey: в сессию попадает только производный контекст.
    monkeypatch.setattr("app.services.user_context.secrets.token_urlsafe", lambda _: "nonce-1")
    vendor_api = FakeVendorApi()
    session = {}

    context = UserContextService(vendor_api).load_for_entry(session, "context-key-1")

    assert context is not None
    assert context.uid == "user-1"
    assert context.is_admin is True
    assert context.context_nonce == "nonce-1"
    assert "context-key-1" not in str(session)

    vendor_api.context_response = None
    assert UserContextService(vendor_api).load_for_entry({}, "context-key-2") is None


def test_role_to_is_admin_grants_admin_only_to_admin_role():
    assert role_to_is_admin("admin") is True
    assert role_to_is_admin("cashier") is False
    assert role_to_is_admin("worker") is False
    assert role_to_is_admin("individual") is False
