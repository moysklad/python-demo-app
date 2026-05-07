from __future__ import annotations

import json
import logging
from typing import Any


LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
}


def configure_logging(level: str) -> None:
    logging.basicConfig(level=LEVEL_MAP.get(level, logging.DEBUG), format="%(message)s")


def log_message(level: str, message: str, extra: dict[str, Any] | None = None) -> None:
    logger = logging.getLogger("python-demo-app")
    numeric_level = LEVEL_MAP.get(level, logging.INFO)

    if extra:
        logger.log(numeric_level, "%s %s", message, json.dumps(extra, ensure_ascii=False, default=str))
        return

    logger.log(numeric_level, "%s", message)
