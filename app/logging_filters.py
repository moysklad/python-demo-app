from __future__ import annotations

import re
import logging
from collections.abc import Mapping
from typing import Any


SENSITIVE_FIELD_NAMES = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "access_token",
}
SENSITIVE_FIELD_SUBSTRINGS = {
    "token",
    "secret",
    "password",
    "passwd",
    "pwd",
    "access_token",
}
CONTEXT_KEY_QUERY_PARAM_RE = re.compile(r"(?i)(contextKey=)([^&\s]+)")


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact_string(record.msg)
        if record.args:
            record.args = _redact_logging_value(record.args)
        return True


def _redact_logging_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, Mapping):
        return _redact_mapping(value)
    if isinstance(value, tuple):
        return tuple(_redact_logging_value(item) for item in value)
    if isinstance(value, list):
        return [_redact_logging_value(item) for item in value]
    if isinstance(value, set):
        return {_redact_logging_value(item) for item in value}
    return value


def _redact_mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        key_name = str(key)
        if _is_sensitive_name(key_name):
            redacted[key_name] = "<redacted>"
        else:
            redacted[key_name] = _redact_logging_value(item)
    return redacted


def _is_sensitive_name(name: str) -> bool:
    lowered = name.lower()
    return lowered in SENSITIVE_FIELD_NAMES or any(part in lowered for part in SENSITIVE_FIELD_SUBSTRINGS)


def _redact_string(value: str) -> str:
    return CONTEXT_KEY_QUERY_PARAM_RE.sub(r"\1<redacted>", value)
