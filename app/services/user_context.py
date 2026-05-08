from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, MutableMapping

from app.integrations.vendor_api import VendorApi
from app.logging import log_message


USER_CONTEXT_SESSION_KEY = "userContext"
USER_CONTEXT_STACK_LIMIT = 10
USER_CONTEXT_SESSION_TTL_SECONDS = 7200


@dataclass(frozen=True)
class UserContextSessionEntry:
    uid: str
    fio: str
    account_id: str
    is_admin: bool
    context_key: str
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

        cached_context = load_user_context_from_session(session_data, context_key)
        if cached_context:
            log_message("DEBUG", "Loaded user context from session")
            return cached_context

        log_message("DEBUG", "Loading user context from Vendor API")
        employee = self._vendor_api.get_context(context_key)
        if not employee or not employee.get("accountId") or not employee.get("uid"):
            return None

        save_user_context_to_session(
            session_data,
            context_key,
            uid=str(employee.get("uid", "")),
            fio=str(employee.get("shortFio", "") or ""),
            account_id=str(employee.get("accountId", "")),
            is_admin=check_is_admin(employee),
        )
        return load_user_context_from_session(session_data, context_key)

    def resolve_backend_context(self, session_data: MutableMapping[str, Any], context_key: str | None) -> ResolvedBackendAuthContext | None:
        if context_key is None:
            return None

        context = load_user_context_from_session(session_data, context_key)
        if not context:
            return None

        account_id = context.account_id.strip()
        uid = context.uid.strip()
        if account_id == "" or uid == "":
            return None

        return ResolvedBackendAuthContext(account_id=account_id, uid=uid, is_admin=context.is_admin)


def get_context_key(query_value: Any = None, body_value: Any = None) -> str | None:
    context_key = body_value if body_value is not None else query_value
    if not isinstance(context_key, str):
        return None
    trimmed = context_key.strip()
    return trimmed or None


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


def user_context_session_bucket(session_data: MutableMapping[str, Any]) -> dict[str, Any]:
    current = session_data.get(USER_CONTEXT_SESSION_KEY)
    if not isinstance(current, dict) or not isinstance(current.get("byContextKey"), dict) or not isinstance(current.get("contextKeyStack"), list):
        current = {"byContextKey": {}, "contextKeyStack": []}
        session_data[USER_CONTEXT_SESSION_KEY] = current

    trim_user_context_bucket(current)
    return current


def save_user_context_to_session(
    session_data: MutableMapping[str, Any],
    context_key: str,
    *,
    uid: str,
    fio: str,
    account_id: str,
    is_admin: bool,
) -> None:
    bucket = user_context_session_bucket(session_data)
    normalized_context_key = context_key.strip()
    now = int(time.time() * 1000)
    bucket["byContextKey"][normalized_context_key] = {
        "uid": uid,
        "fio": fio,
        "accountId": account_id,
        "isAdmin": is_admin,
        "contextKey": normalized_context_key,
        "createdAt": now,
        "expiresAt": now + USER_CONTEXT_SESSION_TTL_SECONDS * 1000,
    }

    stack = [item for item in bucket["contextKeyStack"] if item != normalized_context_key]
    stack.append(normalized_context_key)
    bucket["contextKeyStack"] = stack
    trim_user_context_bucket(bucket)


def load_user_context_from_session(session_data: MutableMapping[str, Any], context_key: str) -> UserContextSessionEntry | None:
    bucket = user_context_session_bucket(session_data)
    raw_context = bucket["byContextKey"].get(context_key)
    context = _normalize_user_context_session_entry(context_key, raw_context)
    if not context:
        bucket["byContextKey"].pop(context_key, None)
        bucket["contextKeyStack"] = [item for item in bucket["contextKeyStack"] if item != context_key]
        return None

    now = int(time.time() * 1000)
    refreshed = UserContextSessionEntry(
        uid=context.uid,
        fio=context.fio,
        account_id=context.account_id,
        is_admin=context.is_admin,
        context_key=context.context_key,
        created_at=context.created_at,
        expires_at=now + USER_CONTEXT_SESSION_TTL_SECONDS * 1000,
    )
    bucket["byContextKey"][context_key] = _to_session_dict(refreshed)
    return refreshed


def trim_user_context_bucket(bucket: dict[str, Any]) -> None:
    raw_contexts = bucket.get("byContextKey") if isinstance(bucket.get("byContextKey"), dict) else {}
    raw_stack = bucket.get("contextKeyStack") if isinstance(bucket.get("contextKeyStack"), list) else []
    contexts: dict[str, dict[str, Any]] = {}

    for context_key, value in raw_contexts.items():
        if not isinstance(context_key, str) or context_key == "":
            continue
        normalized = _normalize_user_context_session_entry(context_key, value)
        if normalized:
            contexts[context_key] = _to_session_dict(normalized)

    stack: list[str] = []
    seen: set[str] = set()
    for context_key in raw_stack:
        if not isinstance(context_key, str) or context_key == "" or context_key not in contexts or context_key in seen:
            continue
        seen.add(context_key)
        stack.append(context_key)

    for context_key in contexts:
        if context_key not in seen:
            seen.add(context_key)
            stack.append(context_key)

    limited_stack = stack[-USER_CONTEXT_STACK_LIMIT:]
    bucket["byContextKey"] = {context_key: contexts[context_key] for context_key in limited_stack}
    bucket["contextKeyStack"] = [context_key for context_key in limited_stack if context_key in bucket["byContextKey"]]


def _normalize_user_context_session_entry(context_key: str, value: Any) -> UserContextSessionEntry | None:
    if not isinstance(value, dict):
        return None

    account_id = str(value.get("accountId", "")).strip()
    uid = str(value.get("uid", "")).strip()
    if account_id == "" or uid == "":
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
        context_key=context_key,
        created_at=created_at,
        expires_at=expires_at,
    )


def _to_session_dict(context: UserContextSessionEntry) -> dict[str, Any]:
    data = asdict(context)
    return {
        "uid": data["uid"],
        "fio": data["fio"],
        "accountId": data["account_id"],
        "isAdmin": data["is_admin"],
        "contextKey": data["context_key"],
        "createdAt": data["created_at"],
        "expiresAt": data["expires_at"],
    }
