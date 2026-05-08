from __future__ import annotations

from app.config import AppConfig, load_config


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
