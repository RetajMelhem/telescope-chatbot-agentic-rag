"""Application logs include only explicitly selected non-content fields."""

import json
import logging
from datetime import UTC, datetime

SAFE_EVENTS = frozenset(
    {"request_completed", "adapter_cleanup_timed_out", "adapter_cleanup_failed"}
)


class SafeJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.msg
            if isinstance(record.msg, str) and record.msg in SAFE_EVENTS
            else "application_event",
        }
        for name in ("request_id", "route", "status_code", "duration_ms"):
            if hasattr(record, name):
                payload[name] = getattr(record, name)
        # Deliberately omit message args, exc_info, HTTP headers, URLs, and bodies.
        return json.dumps(payload)


def configure_logging(level: str) -> logging.Logger:
    logger = logging.getLogger("telescope_rag")
    logger.setLevel(level)
    logger.propagate = False
    if not any(getattr(handler, "telescope_safe", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(SafeJsonFormatter())
        handler.telescope_safe = True
        logger.addHandler(handler)
    return logger
