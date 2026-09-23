from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, session

from app.domain.entities import is_supported_entity
from app.security.jwt_tools import auth_token_is_valid
from app.services.common import ServiceResponse


@dataclass(frozen=True)
class WebError(Exception):
    message: str
    status_code: int


def register_routes(app: Flask, services: Any) -> None:
    @app.errorhandler(WebError)
    def handle_web_error(error: WebError) -> Response:
        return _text_response(error.message, error.status_code)

    @app.get("/health")
    def health():
        return jsonify(
            {
                "ok": True,
                "status": "healthy",
                "uptimeSeconds": round(time.monotonic() - app.config["STARTED_AT"]),
            }
        )

    @app.get("/entry/iframe-main")
    def iframe_main():
        return render_template("entry/iframe.html")

    @app.post("/entry/user-context")
    def user_context():
        body = request.get_json(silent=True) if request.is_json else None
        if not isinstance(body, dict):
            raise WebError("token обязателен и передается только в JSON body", 400)

        token = _trimmed_string(body.get("token"))
        if token is None:
            raise WebError("token обязателен", 400)

        outcome = services.user_context_service.exchange_for_entry(session, token)
        if outcome.context is None or outcome.user is None:
            payload: dict[str, Any] = {"message": "Не удалось получить контекст пользователя"}
            if outcome.error_code:
                payload["code"] = outcome.error_code
            return _json_response(payload, outcome.status_code)

        response: dict[str, Any] = {
            "user": {
                "accountId": outcome.user.account_id,
                "userId": outcome.user.user_id,
                "userUid": outcome.user.user_uid,
                "role": outcome.user.role,
                "isAdmin": outcome.context.is_admin,
            },
            "contextNonce": outcome.context.context_nonce,
        }
        if body.get("page") == "iframe":
            response["pageData"] = services.entry_service.iframe_page_data(outcome.context)
        return _json_response(response, 200)

    @app.get("/entry/iframe-mobile")
    def iframe_mobile():
        # Мобильный хост не поддерживает протокол user-context, сессия поднимается по contextKey из URL.
        context = _load_entry_context(services)
        return render_template("entry/iframe_mobile.html", **services.entry_service.mobile_iframe_view_model(context))

    @app.get("/entry/widget-customerorder")
    def widget_customerorder():
        return _render_widget(services, "customerorder")

    @app.get("/entry/widget-invoiceout")
    def widget_invoiceout():
        return _render_widget(services, "invoiceout")

    @app.get("/entry/popup")
    def popup():
        return render_template("entry/popup.html")

    @app.post("/utils/update-settings")
    def update_settings():
        body = _request_body()
        context_nonce = _trimmed_string(body.get("contextNonce"))
        response = services.utils_service.update_settings(
            session,
            context_nonce,
            str(body.get("infoMessage", "") or ""),
            str(body.get("store", "") or ""),
        )
        return _service_response(response)

    @app.post("/utils/get-object")
    def get_object():
        body = _request_body()
        context_nonce = _trimmed_string(body.get("contextNonce"))
        response = services.utils_service.get_object(
            session,
            context_nonce,
            str(request.args.get("entity", "") or ""),
            str(body.get("objectId", request.args.get("objectId", "")) or ""),
        )
        return _service_response(response)

    @app.post("/utils/stores")
    def request_stores():
        body = _request_body()
        context_nonce = _trimmed_string(body.get("contextNonce"))
        response = services.utils_service.request_stores(session, context_nonce)
        return _service_response(response)

    @app.put("/api/moysklad/vendor/1.0/apps/<app_id>/<account_id>")
    def vendor_put_app(app_id: str, account_id: str):
        _require_vendor_auth(services)
        return _service_response(services.vendor_endpoint_service.put_app(app_id, account_id, _request_body()))

    @app.delete("/api/moysklad/vendor/1.0/apps/<app_id>/<account_id>")
    def vendor_delete_app(app_id: str, account_id: str):
        _require_vendor_auth(services)
        return _service_response(services.vendor_endpoint_service.delete_app(app_id, account_id, _request_body()))

    @app.put("/api/moysklad/vendor/1.0/apps/<app_id>/<account_id>/event")
    def vendor_event(app_id: str, account_id: str):
        _require_vendor_auth(services)
        return _service_response(services.vendor_endpoint_service.app_event(app_id, account_id, _request_body()))

    @app.post("/api/moysklad/vendor/1.0/apps/<app_id>/<account_id>/button")
    def vendor_button(app_id: str, account_id: str):
        _require_vendor_auth(services)
        return _service_response(services.vendor_endpoint_service.button(app_id, account_id, _request_body()))


def _render_widget(services: Any, entity: str) -> str:
    if not is_supported_entity(entity):
        raise WebError("Unsupported entity", 400)

    return render_template("entry/widget.html", **services.entry_service.widget_view_model(entity))


def _load_entry_context(services: Any) -> Any:
    context_key = _trimmed_string(request.args.get("contextKey"))
    if context_key is None:
        raise WebError("Authorization error: contextKey parameter is required", 401)

    context = services.user_context_service.load_for_entry(session, context_key)
    if not context:
        raise WebError("Authorization error: failed to load user context", 401)

    return context


def _require_vendor_auth(services: Any) -> None:
    if not auth_token_is_valid(request.headers, services.config, services.jwt_replay_repository):
        raise WebError("Invalid Authorization token", 401)


def _service_response(response: ServiceResponse) -> Response:
    if response.json_body is not None:
        return _json_response(response.json_body, response.status_code)
    if response.text_body is not None:
        return _text_response(response.text_body, response.status_code)
    return _empty_response(response.status_code)


def _json_response(body: dict[str, Any], status_code: int) -> Response:
    flask_response = jsonify(body)
    flask_response.status_code = status_code
    return flask_response


def _text_response(text: str, status_code: int) -> Response:
    return Response(text, status=status_code, mimetype="text/plain")


def _empty_response(status_code: int) -> Response:
    return Response(status=status_code)


def _request_body() -> dict[str, Any]:
    if request.is_json:
        body = request.get_json(silent=True)
        return body if isinstance(body, dict) else {}
    return dict(request.form.items())


def _trimmed_string(value: Any = None) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None
