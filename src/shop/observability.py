"""Logging setup: JSON lines, a correlation id on every record, personal data masked."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# Set per request by the HTTP middleware. A ContextVar follows the request into the worker thread
# that runs a synchronous handler and into any task it spawns, so every log line of one request
# carries the same id without passing it around.
correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# Attributes every LogRecord has; anything else was passed through ``extra=``.
_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def mask_email(text: str) -> str:
    """Replace every email in ``text`` with ``j***@example.com`` (first letter and domain kept)."""
    return _EMAIL.sub(lambda match: f"{match.group()[0]}***@{match.group().split('@', 1)[1]}", text)


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Emails are masked in the message, the extras and tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": mask_email(record.getMessage()),
            "correlation_id": correlation_id.get(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS:
                entry[key] = mask_email(value) if isinstance(value, str) else value
        if record.exc_info:
            entry["exception"] = mask_email(self.formatException(record.exc_info))
        return json.dumps(entry, default=str, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
