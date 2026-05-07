from __future__ import annotations

import secrets
import time
from typing import Any

from flask import Flask, Request, Response
from flask.sessions import SessionInterface, SessionMixin
from itsdangerous import BadSignature, URLSafeSerializer
from werkzeug.datastructures import CallbackDict

from app.config import AppConfig
from app.repositories.sqlite import SqliteSessionRepository
from app.services.user_context import USER_CONTEXT_SESSION_TTL_SECONDS


class ServerSideSession(CallbackDict[str, Any], SessionMixin):
    def __init__(self, initial: dict[str, Any] | None = None, *, sid: str | None = None, new: bool = False) -> None:
        def on_update(_: ServerSideSession) -> None:
            self.modified = True

        super().__init__(initial or {}, on_update)
        self.sid = sid or secrets.token_urlsafe(32)
        self.new = new
        self.modified = False


class SqliteSessionInterface(SessionInterface):
    pickle_based = False

    def __init__(self, config: AppConfig, repository: SqliteSessionRepository) -> None:
        self._config = config
        self._repository = repository
        self._serializer = URLSafeSerializer(config.session_secret, salt="python-demo-app-session")

    def open_session(self, app: Flask, request: Request) -> ServerSideSession:
        signed_sid = request.cookies.get(self._config.session_name)
        if signed_sid:
            try:
                sid = str(self._serializer.loads(signed_sid))
            except BadSignature:
                sid = ""

            if sid:
                stored = self._repository.load(sid)
                if stored is not None:
                    return ServerSideSession(stored, sid=sid)

        return ServerSideSession(new=True)

    def save_session(self, app: Flask, session: ServerSideSession, response: Response) -> None:
        cookie_path = self.get_cookie_path(app)
        if not session:
            if session.sid:
                self._repository.delete(session.sid)
                response.delete_cookie(self._config.session_name, path=cookie_path)
            return

        expires_at_ms = int(time.time() * 1000) + USER_CONTEXT_SESSION_TTL_SECONDS * 1000
        self._repository.save(session.sid, dict(session), expires_at_ms)
        response.set_cookie(
            self._config.session_name,
            self._serializer.dumps(session.sid),
            max_age=USER_CONTEXT_SESSION_TTL_SECONDS,
            httponly=True,
            secure=self._config.session_cookie_secure,
            samesite=_same_site_cookie_value(self._config.session_cookie_same_site),
            path=cookie_path,
        )


def _same_site_cookie_value(value: str) -> str:
    if value == "none":
        return "None"
    return value.capitalize()
