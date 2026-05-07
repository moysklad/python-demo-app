from __future__ import annotations

import json
import time
from typing import Any

import requests

from app.logging import log_message


DEFAULT_HTTP_TIMEOUT_SECONDS = 30
DEFAULT_HTTP_MAX_RETRIES = 2
DEFAULT_HTTP_RETRY_BASE_SECONDS = 0.25
RETRY_STATUSES = {429, 502, 503, 504}


class HttpClient:
    def request_json(
        self,
        method: str,
        url: str,
        bearer_token: str,
        data: Any = None,
        *,
        service_name: str = "external-api",
        retryable: bool | None = None,
        allow_empty_success_response: bool = False,
    ) -> Any | None:
        normalized_method = method.upper()
        retries = DEFAULT_HTTP_MAX_RETRIES if (retryable if retryable is not None else normalized_method in {"GET", "PUT", "DELETE"}) else 0
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Accept-Encoding": "gzip",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"

        log_message("DEBUG", f"Request: {normalized_method} {url}", {"service": service_name, "headers": headers, "body": data})
        started_at = time.time()

        for attempt in range(1, retries + 2):
            try:
                response = requests.request(
                    normalized_method,
                    url,
                    headers=headers,
                    json=data if data is not None else None,
                    timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
                    allow_redirects=True,
                )
            except requests.RequestException as error:
                if attempt <= retries:
                    log_message("WARN", f"Retry attempt {attempt + 1} for {normalized_method} {url}", {"service": service_name})
                    time.sleep(DEFAULT_HTTP_RETRY_BASE_SECONDS * attempt)
                    continue

                duration_ms = int((time.time() - started_at) * 1000)
                log_message(
                    "ERROR",
                    f"Transport error for {normalized_method} {url}: {error}",
                    {"service": service_name, "kind": "transport", "attempt": attempt, "durationMs": duration_ms},
                )
                return None

            duration_ms = int((time.time() - started_at) * 1000)
            log_message(
                "DEBUG",
                f"Response: {normalized_method} {url}",
                {
                    "service": service_name,
                    "status": response.status_code,
                    "attempt": attempt,
                    "durationMs": duration_ms,
                    "headers": dict(response.headers),
                    "body": _sanitize_response_body_for_log(response.text),
                },
            )

            if response.status_code in RETRY_STATUSES and attempt <= retries:
                log_message(
                    "WARN",
                    f"Retry attempt {attempt + 1} for {normalized_method} {url}",
                    {"service": service_name, "status": response.status_code},
                )
                time.sleep(DEFAULT_HTTP_RETRY_BASE_SECONDS * attempt)
                continue

            if response.status_code < 200 or response.status_code >= 300:
                log_message(
                    "WARN",
                    f"HTTP {response.status_code} for {normalized_method} {url}",
                    {"service": service_name, "kind": "http", "status": response.status_code, "attempt": attempt, "durationMs": duration_ms},
                )
                return None

            if response.text == "":
                return {} if allow_empty_success_response else None

            try:
                return response.json()
            except ValueError as error:
                log_message(
                    "WARN",
                    f"Failed to decode JSON for {normalized_method} {url}: {error}",
                    {"service": service_name, "kind": "decode", "attempt": attempt, "durationMs": duration_ms},
                )
                return None

        return None


def _sanitize_response_body_for_log(body: str) -> str:
    if body == "":
        return ""
    try:
        serialized = json.dumps(json.loads(body), ensure_ascii=False)
    except ValueError:
        serialized = body
    if len(serialized) <= 2000:
        return serialized
    return f"{serialized[:2000]}... [truncated {len(serialized) - 2000} chars]"
