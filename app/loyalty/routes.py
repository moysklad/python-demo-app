from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Flask, Response, g, jsonify, request, session

from app.loyalty.demo_customers import find_loyalty_demo_customers
from app.loyalty.installation import LoyaltyInstallation
from app.loyalty.service import LoyaltyService
from app.services.user_context import UserContextService

logger = logging.getLogger(__name__)

AUTH_TOKEN_HEADER = "Lognex-Discount-API-Auth-Token"
TRUE_VALUES = (True, "true", "on", "1", 1)


def register_loyalty(app: Flask, loyalty_service: LoyaltyService, user_context_service: UserContextService) -> None:
    app.register_blueprint(_provider_blueprint(loyalty_service))
    app.register_blueprint(_connect_blueprint(loyalty_service, user_context_service))


def _connect_blueprint(loyalty_service: LoyaltyService, user_context_service: UserContextService) -> Blueprint:
    """Backend вкладки: форма подключения шлет настройки сюда, рядом с /utils/update-settings."""
    blueprint = Blueprint("loyalty_connect", __name__)

    @blueprint.post("/utils/connect-loyalty")
    def connect_loyalty():
        body = request.get_json(silent=True) if request.is_json else None
        body = body if isinstance(body, dict) else {}
        context_nonce = body.get("contextNonce") if isinstance(body.get("contextNonce"), str) else None

        auth_context = user_context_service.resolve_backend_context(session, context_nonce)
        if not auth_context:
            return _json({"message": "Ошибка авторизации: откройте iframe заново."}, 401)
        if not auth_context.is_admin:
            return _json({"message": "Недостаточно прав"}, 403)

        response = loyalty_service.connect(
            auth_context.account_id,
            body.get("providerUrl"),
            body.get("providerToken"),
            body.get("externalSearch", False) in TRUE_VALUES,
        )
        return _json(response.json_body or {}, response.status_code)

    return blueprint


def _provider_blueprint(loyalty_service: LoyaltyService) -> Blueprint:
    """
    Заглушка провайдера Loyalty API. МойСклад вызывает методы относительно URL, переданного
    в PUT .../loyalty: {url}/counterparty, {url}/retaildemand/recalc и т.д.
    Ошибки отдаются в формате Loyalty API: {"errors": [{"error", "code", "error_message"}]}.
    """
    blueprint = Blueprint("loyalty_provider", __name__, url_prefix="/loyalty")

    @blueprint.before_request
    def authorize() -> Response | None:
        logger.debug("Loyalty API request: %s %s", request.method, request.path)
        installation = loyalty_service.find_by_token(request.headers.get(AUTH_TOKEN_HEADER, ""))
        if installation is None:
            return _loyalty_error(401, "Недействительный токен авторизации")
        g.loyalty_installation = installation
        return None

    @blueprint.post("/counterparty")
    @blueprint.post("/retaildemand")
    @blueprint.post("/retailsalesreturn")
    def created():
        return Response(status=201)

    @blueprint.get("/counterparty")
    def search_counterparty():
        # Внешний поиск обязателен только при externalSearch: true, иначе отвечаем как на нереализованный метод.
        if not _installation().allows_external_search():
            return _loyalty_error(404, "Внешний поиск покупателей не используется: externalSearch выключен")
        return jsonify({"rows": find_loyalty_demo_customers(request.args.get("search", ""))})

    @blueprint.post("/counterparty/detail")
    def counterparty_detail():
        return jsonify({"bonusProgram": {"agentBonusBalance": 0}})

    @blueprint.post("/retaildemand/recalc")
    def recalc():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _loyalty_error(400, "Некорректное тело запроса")

        positions = [
            {**position, "discountPercent": 0, "discountedPrice": position.get("price", 0)}
            for position in payload.get("positions") or []
            if isinstance(position, dict)
        ]
        bonus_program = payload.get("bonusProgram") if isinstance(payload.get("bonusProgram"), dict) else {}
        return jsonify(
            {
                "agent": payload.get("agent") or {},
                "positions": positions,
                "bonusProgram": {
                    "transactionType": "SPENDING" if bonus_program.get("transactionType") == "SPENDING" else "EARNING",
                    "agentBonusBalance": 0,
                    "bonusValueToSpend": 0,
                    "bonusValueToEarn": 0,
                    "agentBonusBalanceAfter": 0,
                    "paidByBonusPoints": 0,
                    "receiptExtraInfo": "",
                },
                "needVerification": False,
            }
        )

    @blueprint.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
    def not_implemented(path: str):
        return _loyalty_error(404, f"Метод {request.method} /{path} не реализован")

    @blueprint.errorhandler(Exception)
    def handle_error(error: Exception):
        logger.error("Loyalty API request failed: %s", error)
        return _loyalty_error(500, "Внутренняя ошибка провайдера")

    return blueprint


def _installation() -> LoyaltyInstallation:
    return g.loyalty_installation


def _loyalty_error(status: int, message: str) -> Response:
    return _json({"errors": [{"error": message, "code": 999, "error_message": message}]}, status)


def _json(payload: dict[str, Any], status: int) -> Response:
    response = jsonify(payload)
    response.status_code = status
    return response
