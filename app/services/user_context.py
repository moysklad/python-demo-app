from __future__ import annotations

import secrets
import time
from dataclasses import asdict, dataclass
from typing import Any, MutableMapping

from app.integrations.vendor_api import VendorApi


# В демо используется модель "один активный пользовательский контекст на browser session".
# contextKey нужен только для начальной загрузки entry-страницы из МоегоСклада, а дальше
# backend-подзапросы авторизуются через contextNonce, привязанный к server-side session.
USER_CONTEXT_SESSION_KEY = "userContext"
USER_CONTEXT_SESSION_TTL_SECONDS = 7200


@dataclass(frozen=True)
class UserContextSessionEntry:
    uid: str
    fio: str
    account_id: str
    is_admin: bool
    context_nonce: str
    created_at: int
    expires_at: int


@dataclass(frozen=True)
class ResolvedBackendAuthContext:
    account_id: str
    uid: str
    is_admin: bool


class UserContextService:
    def __init__(self, vendor_api: VendorApi) -> None:
        self._vendor_api = vendor_api

    def load_for_entry(self, session_data: MutableMapping[str, Any], context_key: str | None) -> UserContextSessionEntry | None:
        if context_key is None:
            return None

        # contextKey - opaque-token от хост-окна. Его не сохраняем в сессии и не
        # прокидываем дальше в шаблоны: он используется только для запроса контекста
        # пользователя во внешнем Vendor API.
        employee = self._vendor_api.get_context(context_key)
        if not employee or not employee.get("accountId") or not employee.get("uid"):
            return None

        uid = str(employee.get("uid", "")).strip()
        account_id = str(employee.get("accountId", "")).strip()
        if uid == "" or account_id == "":
            return None

        return save_active_user_context_to_session(
            session_data,
            uid=uid,
            fio=str(employee.get("shortFio", "") or ""),
            account_id=account_id,
            is_admin=check_is_admin(employee),
        )

    def resolve_backend_context(self, session_data: MutableMapping[str, Any], context_nonce: str | None) -> ResolvedBackendAuthContext | None:
        if context_nonce is None:
            return None

        normalized_nonce = context_nonce.strip()
        if normalized_nonce == "":
            return None

        context = load_active_user_context_from_session(session_data)
        if not context or context.context_nonce != normalized_nonce:
            return None

        account_id = context.account_id.strip()
        uid = context.uid.strip()
        if account_id == "" or uid == "":
            return None

        return ResolvedBackendAuthContext(account_id=account_id, uid=uid, is_admin=context.is_admin)


def normalize_is_admin(raw_is_admin: Any) -> bool:
    if isinstance(raw_is_admin, bool):
        return raw_is_admin
    if isinstance(raw_is_admin, str):
        return raw_is_admin.strip().upper() == "ALL"
    return False


def check_is_admin(employee: dict[str, Any] | None) -> bool:
    if not employee:
        return False
    permissions = employee.get("permissions")
    admin = permissions.get("admin") if isinstance(permissions, dict) else None
    view = admin.get("view") if isinstance(admin, dict) else None
    return normalize_is_admin(view)


def save_active_user_context_to_session(
    session_data: MutableMapping[str, Any],
    *,
    uid: str,
    fio: str,
    account_id: str,
    is_admin: bool,
) -> UserContextSessionEntry:
    previous = _normalize_user_context_session_entry(session_data.get(USER_CONTEXT_SESSION_KEY))
    normalized_uid = uid.strip()
    normalized_account_id = account_id.strip()
    now = int(time.time() * 1000)

    # contextNonce стабилен для того же uid/accountId/isAdmin, чтобы повторное
    # открытие iframe не ломало уже отрисованную страницу. При смене пользователя,
    # аккаунта или уровня прав nonce ротируется, а старые формы получают 401.
    if previous and _same_backend_identity(previous, normalized_uid, normalized_account_id, is_admin):
        context_nonce = previous.context_nonce
        created_at = previous.created_at
    else:
        context_nonce = secrets.token_urlsafe(16)
        created_at = now

    context = UserContextSessionEntry(
        uid=normalized_uid,
        fio=fio,
        account_id=normalized_account_id,
        is_admin=is_admin,
        context_nonce=context_nonce,
        created_at=created_at,
        expires_at=now + USER_CONTEXT_SESSION_TTL_SECONDS * 1000,
    )
    session_data[USER_CONTEXT_SESSION_KEY] = _to_session_dict(context)
    return context


def load_active_user_context_from_session(session_data: MutableMapping[str, Any]) -> UserContextSessionEntry | None:
    context = _normalize_user_context_session_entry(session_data.get(USER_CONTEXT_SESSION_KEY))
    if not context:
        session_data.pop(USER_CONTEXT_SESSION_KEY, None)
        return None

    now = int(time.time() * 1000)
    # TTL скользящий: пока iframe/виджет делает backend-запросы, активный контекст
    # продлевается. Истекший контекст удаляется и требует повторного открытия страницы.
    refreshed = UserContextSessionEntry(
        uid=context.uid,
        fio=context.fio,
        account_id=context.account_id,
        is_admin=context.is_admin,
        context_nonce=context.context_nonce,
        created_at=context.created_at,
        expires_at=now + USER_CONTEXT_SESSION_TTL_SECONDS * 1000,
    )
    session_data[USER_CONTEXT_SESSION_KEY] = _to_session_dict(refreshed)
    return refreshed


def _normalize_user_context_session_entry(value: Any) -> UserContextSessionEntry | None:
    if not isinstance(value, dict):
        return None

    account_id = str(value.get("accountId", "")).strip()
    uid = str(value.get("uid", "")).strip()
    context_nonce = str(value.get("contextNonce", "")).strip()
    if account_id == "" or uid == "" or context_nonce == "":
        return None

    now = int(time.time() * 1000)
    created_at = value.get("createdAt") if isinstance(value.get("createdAt"), int) else now
    expires_at = value.get("expiresAt") if isinstance(value.get("expiresAt"), int) else created_at + USER_CONTEXT_SESSION_TTL_SECONDS * 1000
    if expires_at <= now:
        return None

    return UserContextSessionEntry(
        account_id=account_id,
        uid=uid,
        fio=str(value.get("fio", "") or ""),
        is_admin=bool(value.get("isAdmin")),
        context_nonce=context_nonce,
        created_at=created_at,
        expires_at=expires_at,
    )


def _same_backend_identity(context: UserContextSessionEntry, uid: str, account_id: str, is_admin: bool) -> bool:
    return context.uid == uid and context.account_id == account_id and context.is_admin == is_admin


def _to_session_dict(context: UserContextSessionEntry) -> dict[str, Any]:
    data = asdict(context)
    return {
        "uid": data["uid"],
        "fio": data["fio"],
        "accountId": data["account_id"],
        "isAdmin": data["is_admin"],
        "contextNonce": data["context_nonce"],
        "createdAt": data["created_at"],
        "expiresAt": data["expires_at"],
    }

