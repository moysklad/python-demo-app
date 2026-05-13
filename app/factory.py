from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from flask import Flask, g, request
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import AppConfig, configure_logging, load_config
from app.domain.app_instance import AppInstanceRepository
from app.integrations.http_client import HttpClient
from app.integrations.json_api import JsonApiFactory
from app.integrations.vendor_api import VendorApi
from app.repositories.sqlite import (
    SqliteAppInstanceRepository,
    SqliteConnectionPool,
    SqliteJwtReplayRepository,
    SqliteSessionRepository,
)
from app.security.crypto import ensure_private_dir
from app.security.jwt_tools import JwtReplayRepository
from app.services.entry import EntryService
from app.services.user_context import UserContextService
from app.services.utils import UtilsService
from app.services.vendor_endpoint import VendorEndpointService
from app.web.routes import register_routes
from app.web.session import SqliteSessionInterface


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppServices:
    config: AppConfig
    app_repository: AppInstanceRepository
    jwt_replay_repository: JwtReplayRepository
    vendor_api: VendorApi
    json_api_factory: JsonApiFactory
    user_context_service: UserContextService
    entry_service: EntryService
    utils_service: UtilsService
    vendor_endpoint_service: VendorEndpointService


def create_app(
    config: AppConfig | None = None,
    *,
    app_repository: AppInstanceRepository | None = None,
    jwt_replay_repository: JwtReplayRepository | None = None,
    vendor_api: VendorApi | None = None,
    json_api_factory: JsonApiFactory | None = None,
) -> Flask:
    runtime_config = config or load_config()
    configure_logging(runtime_config.log_level)
    ensure_private_dir(runtime_config.data_dir)

    root = Path(__file__).resolve().parent.parent
    flask_app = Flask(
        __name__,
        template_folder=str(root / "templates"),
        static_folder=str(root / "static" / "assets"),
        static_url_path="/assets",
    )
    flask_app.config["APP_CONFIG"] = runtime_config
    flask_app.config["STARTED_AT"] = time.monotonic()

    if runtime_config.trust_proxy > 0:
        flask_app.wsgi_app = ProxyFix(
            flask_app.wsgi_app,
            x_for=runtime_config.trust_proxy,
            x_proto=runtime_config.trust_proxy,
            x_host=runtime_config.trust_proxy,
            x_port=runtime_config.trust_proxy,
            x_prefix=runtime_config.trust_proxy,
        )

    sqlite_pool = SqliteConnectionPool(runtime_config.app_db_path)
    real_app_repository = app_repository or SqliteAppInstanceRepository(
        runtime_config.app_db_path,
        runtime_config.encrypt_key,
        sqlite_pool,
    )
    real_jwt_replay_repository = jwt_replay_repository or SqliteJwtReplayRepository(
        runtime_config.app_db_path,
        sqlite_pool,
    )
    session_repository = SqliteSessionRepository(
        runtime_config.app_db_path,
        runtime_config.encrypt_key,
        sqlite_pool,
    )
    flask_app.session_interface = SqliteSessionInterface(runtime_config, session_repository)

    http_client = HttpClient()
    real_vendor_api = vendor_api or VendorApi(runtime_config, http_client)
    real_json_api_factory = json_api_factory or JsonApiFactory(runtime_config, http_client)
    user_context_service = UserContextService(real_vendor_api)
    services = AppServices(
        config=runtime_config,
        app_repository=real_app_repository,
        jwt_replay_repository=real_jwt_replay_repository,
        vendor_api=real_vendor_api,
        json_api_factory=real_json_api_factory,
        user_context_service=user_context_service,
        entry_service=EntryService(runtime_config, real_app_repository, real_json_api_factory),
        utils_service=UtilsService(runtime_config, real_app_repository, user_context_service, real_vendor_api, real_json_api_factory),
        vendor_endpoint_service=VendorEndpointService(real_app_repository),
    )
    flask_app.config["APP_SERVICES"] = services

    register_routes(flask_app, services)
    if runtime_config.log_level == "DEBUG":
        _register_request_logging(flask_app)

    @flask_app.errorhandler(Exception)
    def handle_error(error: Exception):
        if isinstance(error, HTTPException):
            return error
        logger.error("%s", error)
        return "Internal Server Error", 500

    return flask_app


def _register_request_logging(app: Flask) -> None:
    @app.before_request
    def log_request_started() -> None:
        g.started_at = time.time()
        should_log_body = request.path.startswith("/vendor-endpoint")
        body = request.get_json(silent=True) if should_log_body else None
        request_line = f"{request.method} {request.path}"
        log_message = "HTTP request started %s queryKeys=%s"
        log_args = [request_line, list(request.args.keys())]
        if should_log_body and body is not None:
            log_message += "\n\n%s"
            log_args.append(body)

        logger.debug(log_message, *log_args)

    @app.after_request
    def log_request_completed(response):
        started_at = getattr(g, "started_at", time.time())
        request_line = f"{request.method} {request.path}"
        logger.debug(
            "HTTP request completed %s status=%s durationMs=%s",
            request_line,
            response.status_code,
            int((time.time() - started_at) * 1000),
        )
        return response
