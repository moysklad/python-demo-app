from __future__ import annotations

import time
from collections.abc import Mapping
from secrets import token_hex
from typing import Any, Protocol

import jwt

from app.config import AppConfig
from app.logging import log_message


class JwtReplayRepository(Protocol):
    def register(self, jti: str, exp_unix_seconds: int) -> bool:
        ...


def build_vendor_api_jwt(config: AppConfig) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": config.app_uid,
            "iat": now,
            "exp": now + 300,
            "jti": token_hex(32),
        },
        config.secret_key,
        algorithm="HS256",
    )


def auth_token_is_valid(headers: Mapping[str, Any], config: AppConfig, replay_repository: JwtReplayRepository) -> bool:
    raw_auth = _get_header(headers, "Authorization")
    if not raw_auth:
        log_message("WARN", "Authorization header not set")
        return False

    bearer = "Bearer "
    if not raw_auth.startswith(bearer):
        log_message("WARN", "Invalid Authorization header format")
        return False

    jwt_token = raw_auth[len(bearer):]
    if not config.secret_key:
        log_message("ERROR", "Secret key is not set in config")
        return False

    try:
        decoded = jwt.decode(jwt_token, config.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as error:
        log_message("WARN", str(error))
        return False

    jti = decoded.get("jti")
    exp = decoded.get("exp")
    iat = decoded.get("iat")

    if not jti:
        log_message("WARN", "JTI is not set")
        return False
    if exp is None:
        log_message("WARN", "JWT exp is not set")
        return False
    if iat is None:
        log_message("WARN", "JWT iat is not set")
        return False

    if not replay_repository.register(str(jti), int(exp)):
        log_message("WARN", "JWT replay detected", {"jti": str(jti)})
        return False

    return True


def _get_header(headers: Mapping[str, Any], name: str) -> str:
    if hasattr(headers, "get"):
        value = headers.get(name)
        if value is None:
            value = headers.get(name.lower())
    else:
        value = None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value) if value else ""
