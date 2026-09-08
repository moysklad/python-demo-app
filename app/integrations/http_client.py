from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

import requests
from requests import Session
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.exceptions import MaxRetryError
from urllib3.util import Retry

DEFAULT_HTTP_TIMEOUT_SECONDS = 30
DEFAULT_HTTP_MAX_RETRIES = 2
DEFAULT_HTTP_RETRY_BASE_SECONDS = 0.25
LOGNEX_RETRY_AFTER_HEADER = "X-Lognex-Retry-After"
LOGNEX_RETRY_INTERVAL_HEADER = "X-Lognex-Retry-TimeInterval"
RATE_LIMIT_HEADER = "X-RateLimit-Limit"
MAX_LOGGED_RESPONSE_BODY_CHARS = 2000


logger = logging.getLogger(__name__)


class LognexRetry(Retry):
    """urllib3.Retry that understands MoySklad's millisecond X-Lognex-Retry-After header."""

    def get_retry_after(self, response: Any) -> float | None:
        retry_after_seconds = _lognex_retry_after_seconds(response.headers)
        if retry_after_seconds is not None:
            return min(retry_after_seconds, float(self.retry_after_max))
        return super().get_retry_after(response)

    def is_retry(self, method: str, status_code: int, has_retry_after: bool = False) -> bool:
        if not self._is_method_retryable(method):
            return False
        if self.status_forcelist and status_code in self.status_forcelist:
            return True
        return bool(
            self.total
            and self.respect_retry_after_header
            and has_retry_after
            and status_code == HTTPStatus.TOO_MANY_REQUESTS
        )


@dataclass(frozen=True)
class _HttpResult:
    body: str
    attempt: int
    duration_ms: int
    lognex_retries: int
    successful: bool


class _LognexRateLimitGate:
    """Shared rate-limit wait for parallel requests within one limit scope.

    Holds a not-before deadline from X-Lognex-Retry-After and from the
    advertised rate (X-RateLimit-Limit / X-Lognex-Retry-TimeInterval), and
    lets one thread send at a time so the deadline is not raced. MoySklad
    counts limits per account and per API, so each scope needs its own gate.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._not_before = 0.0

    def wait(self) -> None:
        while True:
            with self._lock:
                delay = self._not_before - time.monotonic()
            if delay <= 0:
                return
            time.sleep(delay)

    def block_for(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        with self._lock:
            if deadline > self._not_before:
                self._not_before = deadline

    def slot(self) -> threading.Lock:
        return self._send_lock

    def observe(self, response: requests.Response) -> None:
        spacing = _rate_limit_spacing_seconds(response.headers) or 0.0
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            retry_after = _lognex_retry_after_seconds(response.headers) or 0.0
            self.block_for(max(retry_after, spacing))
        elif spacing > 0:
            self.block_for(spacing)


class HttpClient:
    def __init__(self, session: Session | None = None) -> None:
        self._injected_session = _configure_session(session) if session is not None else None
        self._thread_local = threading.local()
        self._gates_lock = threading.Lock()
        self._gates: dict[tuple[str, str], _LognexRateLimitGate] = {}

    def _gate_for(self, service_name: str, bearer_token: str) -> _LognexRateLimitGate:
        """Rate limits are counted per API and per account, so gate on both."""
        key = (service_name, bearer_token)
        with self._gates_lock:
            gate = self._gates.get(key)
            if gate is None:
                gate = _LognexRateLimitGate()
                self._gates[key] = gate
            return gate

    def _session_for_current_thread(self) -> Session:
        if self._injected_session is not None:
            return self._injected_session

        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = _configure_session(requests.Session())
            self._thread_local.session = session
        return session

    def request_json(
        self,
        method: str,
        url: str,
        bearer_token: str,
        data: Any = None,
        *,
        service_name: str = "external-api",
        retryable: bool | None = None,
    ) -> Any | None:
        """Send an HTTP request and decode a JSON response body.

        Returns parsed JSON for successful responses with a non-empty body.
        Returns `None` for transport errors, non-2xx responses, empty bodies,
        or invalid JSON payloads.
        """
        result = self._request(
            method,
            url,
            bearer_token,
            data,
            service_name=service_name,
            retryable=retryable,
        )
        return _decode_json_result(method, url, service_name, result)

    def request_json_with_retries(
        self,
        method: str,
        url: str,
        bearer_token: str,
        data: Any = None,
        *,
        service_name: str = "external-api",
        retryable: bool | None = None,
    ) -> tuple[Any | None, int]:
        """Send an HTTP request and return its JSON body and Lognex retry count."""
        result = self._request(
            method,
            url,
            bearer_token,
            data,
            service_name=service_name,
            retryable=retryable,
        )
        decoded = _decode_json_result(method, url, service_name, result)
        return decoded, result.lognex_retries if result is not None else 0

    def execute(
        self,
        method: str,
        url: str,
        bearer_token: str,
        data: Any = None,
        *,
        service_name: str = "external-api",
        retryable: bool | None = None,
    ) -> bool:
        """Send an HTTP request and return whether it completed successfully.

        This method is intended for command-style endpoints where response body
        content is irrelevant. It returns `True` for any successful 2xx
        response and `False` for transport errors or non-2xx responses.
        """
        result = self._request(
            method,
            url,
            bearer_token,
            data,
            service_name=service_name,
            retryable=retryable,
        )
        return result is not None and result.successful

    def _request(
        self,
        method: str,
        url: str,
        bearer_token: str,
        data: Any = None,
        *,
        service_name: str,
        retryable: bool | None,
    ) -> _HttpResult | None:
        normalized_method = method.upper()
        request_line = f"{normalized_method} {url}"
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Accept-Encoding": "gzip",
        }

        _log_debug_request(request_line, service_name, headers, data)
        started_at = time.time()

        try:
            response = self._send_request(
                normalized_method,
                url,
                headers=headers,
                data=data,
                retryable=retryable,
                gate=self._gate_for(service_name, bearer_token),
            )
        except RequestException as error:
            duration_ms = int((time.time() - started_at) * 1000)
            logger.error(
                "Transport error %s service=%s error=%s attempt=%s durationMs=%s",
                request_line,
                service_name,
                error,
                1,
                duration_ms,
            )
            return None

        duration_ms = int((time.time() - started_at) * 1000)
        attempt = _response_attempt_count(response)
        body = response.text or ""
        lognex_retries = int(getattr(response, "_lognex_retry_count", 0))
        successful = HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES
        _log_debug_response(request_line, service_name, response, attempt, duration_ms, body)

        if not successful:
            logger.warning(
                "HTTP error %s service=%s status=%s attempt=%s durationMs=%s",
                request_line,
                service_name,
                response.status_code,
                attempt,
                duration_ms,
            )

        return _HttpResult(
            body=body,
            attempt=attempt,
            duration_ms=duration_ms,
            lognex_retries=lognex_retries,
            successful=successful,
        )

    def _send_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        data: Any,
        retryable: bool | None,
        gate: _LognexRateLimitGate,
    ) -> requests.Response:
        session = self._session_for_current_thread()
        if retryable is False:
            return self._send_once(session, method, url, headers=headers, data=data, retryable=False, gate=gate)

        retries = _build_retries()
        while True:
            response = self._send_once(session, method, url, headers=headers, data=data, retryable=True, gate=gate)
            retry_view = _RetryAfterView(response)
            retry_after = retries.get_retry_after(retry_view)
            if not retries.is_retry(method, response.status_code, retry_after is not None):
                setattr(response, "_lognex_retry_count", _lognex_retry_count(retries))
                return response

            try:
                retries = retries.increment(method, url, response=retry_view)
            except MaxRetryError:
                setattr(response, "_lognex_retry_count", _lognex_retry_count(retries))
                return response

            logger.info(
                "Retrying %s %s after %s header delayMs=%s retry=%s/%s",
                method,
                url,
                LOGNEX_RETRY_AFTER_HEADER,
                response.headers.get(LOGNEX_RETRY_AFTER_HEADER),
                len(retries.history),
                DEFAULT_HTTP_MAX_RETRIES,
            )

    def _send_once(
        self,
        session: Session,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        data: Any,
        retryable: bool,
        gate: _LognexRateLimitGate,
    ) -> requests.Response:
        with gate.slot():
            gate.wait()
            if not retryable:
                request = requests.Request(method, url, headers=headers, json=data)
                prepared = session.prepare_request(request)
                adapter = HTTPAdapter(max_retries=False)
                response = adapter.send(prepared, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
            else:
                response = session.request(
                    method,
                    url,
                    headers=headers,
                    json=data,
                    timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
                )
            gate.observe(response)
            return response


def _configure_session(session: Session) -> Session:
    retry_adapter = HTTPAdapter(max_retries=_build_retries())
    session.mount("http://", retry_adapter)
    session.mount("https://", retry_adapter)
    return session


def _decode_json_result(
    method: str,
    url: str,
    service_name: str,
    result: _HttpResult | None,
) -> Any | None:
    if result is None or not result.successful or result.body == "":
        return None

    try:
        return json.loads(result.body)
    except ValueError as error:
        request_line = f"{method.upper()} {url}"
        logger.warning(
            "Failed to decode JSON for %s service=%s error=%s attempt=%s durationMs=%s",
            request_line,
            service_name,
            error,
            result.attempt,
            result.duration_ms,
        )
        return None


def _build_retries() -> LognexRetry:
    return LognexRetry(
        total=DEFAULT_HTTP_MAX_RETRIES,
        backoff_factor=DEFAULT_HTTP_RETRY_BASE_SECONDS,
        raise_on_status=False,
        respect_retry_after_header=True,
    )


class _RetryAfterView:
    def __init__(self, response: requests.Response) -> None:
        self.headers = response.headers
        self.status = response.status_code

    def get_redirect_location(self) -> None:
        return None


def _log_debug_request(request_line: str, service_name: str, headers: dict[str, str], data: Any) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return

    log_message = "Request %s service=%s\nheaders=%s"
    log_args: list[Any] = [request_line, service_name, headers]
    if data is not None:
        log_message += "\n\n%s"
        log_args.append(data)

    logger.debug(log_message, *log_args)


def _log_debug_response(
    request_line: str,
    service_name: str,
    response: requests.Response,
    attempt: int,
    duration_ms: int,
    body: str,
) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return

    log_message = "Response %s service=%s status=%s attempt=%s durationMs=%s\nheaders=%s"
    log_args: list[Any] = [request_line, service_name, response.status_code, attempt, duration_ms, dict(response.headers)]
    if body != "":
        log_message += "\n\n%s"
        log_args.append(_sanitize_response_body_for_log(body))

    logger.debug(log_message, *log_args)


def _header_int(headers: Any, name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _lognex_retry_after_seconds(headers: Any) -> float | None:
    retry_after_ms = _header_int(headers, LOGNEX_RETRY_AFTER_HEADER)
    if retry_after_ms is None or retry_after_ms < 0:
        return None
    return retry_after_ms / 1000


def _rate_limit_spacing_seconds(headers: Any) -> float | None:
    """Sustainable delay between requests from the advertised rate limit."""
    limit = _header_int(headers, RATE_LIMIT_HEADER)
    interval_ms = _header_int(headers, LOGNEX_RETRY_INTERVAL_HEADER)
    if not limit or not interval_ms or limit <= 0 or interval_ms <= 0:
        return None
    return interval_ms / 1000 / limit


def _lognex_retry_count(retries: Retry) -> int:
    return sum(1 for item in retries.history if item.status == HTTPStatus.TOO_MANY_REQUESTS)


def _response_attempt_count(response: requests.Response) -> int:
    lognex_retry_count = getattr(response, "_lognex_retry_count", 0)
    retries = getattr(response.raw, "retries", None)
    history = getattr(retries, "history", None)
    if history is None:
        return lognex_retry_count + 1
    return lognex_retry_count + len(history) + 1


def _sanitize_response_body_for_log(body: str) -> str:
    if body == "":
        return ""
    try:
        serialized = json.dumps(json.loads(body), ensure_ascii=False)
    except ValueError:
        serialized = body
    if len(serialized) <= MAX_LOGGED_RESPONSE_BODY_CHARS:
        return serialized
    return f"{serialized[:MAX_LOGGED_RESPONSE_BODY_CHARS]}... [truncated {len(serialized) - MAX_LOGGED_RESPONSE_BODY_CHARS} chars]"
