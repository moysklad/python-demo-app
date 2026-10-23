from __future__ import annotations

from typing import Any

from flask import Blueprint, Flask, Response, jsonify, request, session

from app.config import AppConfig
from app.scenario.service import ScenarioService
from app.security.jwt_tools import JwtReplayRepository, auth_token_is_valid
from app.services.user_context import UserContextService


def register_scenario(
    app: Flask,
    scenario_service: ScenarioService,
    user_context_service: UserContextService,
    config: AppConfig,
    jwt_replay_repository: JwtReplayRepository,
) -> None:
    blueprint = Blueprint("scenario", __name__)

    @blueprint.post("/api/moysklad/vendor/1.0/apps/<app_id>/<account_id>/scenario")
    def vendor_scenario(app_id: str, account_id: str):
        """Обработчик действия из сценария: вызывает МойСклад под service JWT, как и остальные методы vendorApi."""
        if not auth_token_is_valid(request.headers, config, jwt_replay_repository):
            return Response("Invalid Authorization token", status=401, mimetype="text/plain")

        body = request.get_json(silent=True) if request.is_json else None
        response = scenario_service.handle(app_id, account_id, body if isinstance(body, dict) else {})
        if response.json_body is None:
            return Response(status=response.status_code)
        return _json(response.json_body, response.status_code)

    @blueprint.post("/utils/scenario-events")
    def scenario_events():
        """Журнал для окна чатов: запрос из браузера авторизуется contextNonce, как и остальные /utils."""
        body = request.get_json(silent=True) if request.is_json else None
        body = body if isinstance(body, dict) else {}
        context_nonce = body.get("contextNonce") if isinstance(body.get("contextNonce"), str) else None

        auth_context = user_context_service.resolve_backend_context(session, context_nonce)
        if not auth_context:
            return _json({"message": "Ошибка авторизации: откройте окно заново."}, 401)

        return _json(scenario_service.journal(auth_context.account_id), 200)

    app.register_blueprint(blueprint)


def _json(payload: dict[str, Any], status: int) -> Response:
    response = jsonify(payload)
    response.status_code = status
    return response
