from __future__ import annotations

import logging

from app.config import AppConfig, load_config
from app.config import configure_logging
from app.logging_filters import SensitiveDataFilter


def test_load_config_uses_app_config_defaults_for_optional_values():
    env = {
        "APP_ID": "app-id",
        "APP_UID": "app-uid",
        "APP_SECRET_KEY": "secret-key-32-characters-value",
        "APP_ENCRYPT_KEY": "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
        "APP_BASE_URL": "http://localhost:8080",
        "SESSION_SECRET": "session-secret-32-characters",
    }
    defaults = AppConfig()

    config = load_config(env)

    assert config.port == defaults.port
    assert config.log_level == defaults.log_level
    assert config.moysklad_vendor_api_endpoint_url == defaults.moysklad_vendor_api_endpoint_url
    assert config.moysklad_json_api_endpoint_url == defaults.moysklad_json_api_endpoint_url
    assert config.session_cookie_secure == defaults.session_cookie_secure
    assert config.session_cookie_same_site == defaults.session_cookie_same_site
    assert config.session_name == defaults.session_name
    assert config.trust_proxy == defaults.trust_proxy


def test_configure_logging_sets_timestamp_and_logger_name():
    configure_logging("INFO")

    root_logger = logging.getLogger()
    handler = root_logger.handlers[0]

    assert root_logger.level == logging.INFO
    assert handler.formatter is not None
    assert handler.formatter._fmt == "%(asctime)s %(levelname)s %(name)s %(message)s"
    assert handler.formatter.datefmt == "%Y-%m-%d %H:%M:%S"
    assert any(isinstance(log_filter, SensitiveDataFilter) for log_filter in handler.filters)
