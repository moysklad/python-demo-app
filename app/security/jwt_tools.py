from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from secrets import token_hex
from typing import Any, Protocol

import jwt

from app.config import AppConfig


logger = logging.getLogger(__name__)


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
        logger.warning("Authorization header not set")
        return False

    bearer = "Bearer "
    if not raw_auth.startswith(bearer):
        logger.warning("Invalid Authorization header format")
        return False

    jwt_token = raw_auth[len(bearer):]
    if not config.secret_key:
        logger.error("Secret key is not set in config")
        return False

    try:
        decoded = jwt.decode(jwt_token, config.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as error:
        logger.warning("%s", error)
        return False

    jti = decoded.get("jti")
    exp = decoded.get("exp")
    iat = decoded.get("iat")

    if not jti:
        logger.warning("JTI is not set")
        return False
    if exp is None:
        logger.warning("JWT exp is not set")
        return False
    if iat is None:
        logger.warning("JWT iat is not set")
        return False

    if not replay_repository.register(str(jti), int(exp)):
        logger.warning("JWT replay detected %s", {"jti": str(jti)})
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
