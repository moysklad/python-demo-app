from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


LOG_LEVELS = {"DEBUG", "INFO", "WARN", "ERROR"}
SAME_SITE_VALUES = {"lax", "strict", "none"}


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=_log_level_value(level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


@dataclass(frozen=True)
class AppConfig:
    app_id: str = ""
    app_uid: str = ""
    secret_key: str = ""
    encrypt_key: str = ""
    app_base_url: str = ""
    session_secret: str = ""
    port: int = 8080
    log_level: str = "DEBUG"
    moysklad_vendor_api_endpoint_url: str = "https://apps-api.moysklad.ru/api/vendor/1.0"
    moysklad_json_api_endpoint_url: str = "https://api.moysklad.ru/api/remap/1.2"
    session_cookie_secure: bool = True
    session_cookie_same_site: str = "none"
    session_name: str = "connect.sid"
    trust_proxy: int = 1
    data_dir: Path = Path("./tmp/data")
    app_db_path: Path = Path("./tmp/data/app.sqlite")


def load_config(env: Mapping[str, str] | None = None, *, load_dotenv_file: bool = True) -> AppConfig:
    if env is None:
        if load_dotenv_file:
            load_dotenv()
        source: Mapping[str, str] = os.environ
    else:
        source = env

    defaults = AppConfig()
    cwd = Path.cwd()
    data_dir = _resolve_path(cwd, source.get("DATA_DIR", str(defaults.data_dir)))
    app_db_path = _resolve_path(cwd, source.get("APP_DB_PATH", str(defaults.app_db_path)))

    config = AppConfig(
        app_id=_required(source, "APP_ID"),
        app_uid=_required(source, "APP_UID"),
        secret_key=_required(source, "APP_SECRET_KEY"),
        encrypt_key=_required(source, "APP_ENCRYPT_KEY"),
        app_base_url=_required(source, "APP_BASE_URL"),
        session_secret=_required(source, "SESSION_SECRET"),
        port=_int_value(source, "PORT", defaults.port),
        log_level=source.get("LOG_LEVEL", defaults.log_level).upper(),
        moysklad_vendor_api_endpoint_url=source.get(
            "MOYSKLAD_VENDOR_API_ENDPOINT_URL",
            defaults.moysklad_vendor_api_endpoint_url,
        ),
        moysklad_json_api_endpoint_url=source.get(
            "MOYSKLAD_JSON_API_ENDPOINT_URL",
            defaults.moysklad_json_api_endpoint_url,
        ),
        session_cookie_secure=_bool_value(
            source,
            "SESSION_COOKIE_SECURE",
            defaults.session_cookie_secure,
        ),
        session_cookie_same_site=source.get(
            "SESSION_COOKIE_SAME_SITE",
            defaults.session_cookie_same_site,
        ).lower(),
        session_name=source.get("SESSION_NAME", defaults.session_name),
        trust_proxy=_int_value(source, "TRUST_PROXY", defaults.trust_proxy),
        data_dir=data_dir,
        app_db_path=app_db_path,
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    missing = [
        name
        for name, value in (
            ("APP_ID", config.app_id),
            ("APP_UID", config.app_uid),
            ("APP_SECRET_KEY", config.secret_key),
            ("APP_ENCRYPT_KEY", config.encrypt_key),
            ("APP_BASE_URL", config.app_base_url),
            ("SESSION_SECRET", config.session_secret),
        )
        if not value
    ]

    if missing:
        raise ValueError(f"Missing required runtime config: {', '.join(missing)}")

    if not re.fullmatch(r"[0-9a-fA-F]{64}", config.encrypt_key):
        raise ValueError("APP_ENCRYPT_KEY must be 64 hex characters")

    if config.log_level not in LOG_LEVELS:
        raise ValueError("LOG_LEVEL must be one of DEBUG, INFO, WARN, ERROR")

    if config.session_cookie_same_site not in SAME_SITE_VALUES:
        raise ValueError("SESSION_COOKIE_SAME_SITE must be one of lax, strict, none")


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if value == "":
        return ""
    return value


def _int_value(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _bool_value(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() == "true"


def _log_level_value(level: str) -> int:
    normalized = level.upper()
    if normalized == "INFO":
        return logging.INFO
    if normalized == "WARN":
        return logging.WARNING
    if normalized == "ERROR":
        return logging.ERROR
    return logging.DEBUG


def _resolve_path(cwd: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (cwd / path).resolve()
