from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ServiceResponse:
    status_code: int = 200
    json_body: dict[str, Any] | None = None
    text_body: str | None = None
