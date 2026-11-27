"""Request-id logging and timing middleware (Slice C)."""

from __future__ import annotations

import logging
import time
import uuid

from flask import g, request

logger = logging.getLogger("careerai")


def configure_logging() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s request_id=%(request_id)s %(message)s"
        )
    )
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(g, "request_id", "-") if _has_app_ctx() else "-"
        return True


def _has_app_ctx() -> bool:
    try:
        from flask import has_request_context

        return has_request_context()
    except Exception:
        return False


def register_observability(app) -> None:
    configure_logging()
    for handler in logger.handlers:
        handler.addFilter(_RequestIdFilter())

    @app.before_request
    def _start_timer():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        g._req_start = time.perf_counter()

    @app.after_request
    def _log_request(response):
        started = getattr(g, "_req_start", None)
        latency_ms = int((time.perf_counter() - started) * 1000) if started else -1
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        logger.info(
            "method=%s path=%s status=%s latency_ms=%s",
            request.method,
            request.path,
            response.status_code,
            latency_ms,
        )
        return response
