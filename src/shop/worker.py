"""Outbox worker: delivers stored domain events with retries.

Run with ``python -m shop.worker``. Several workers may run at once; they never take the same
message. ``SHOP_DATABASE_URL`` must be set.
"""

from __future__ import annotations

import logging
import signal
import threading
from types import FrameType

import httpx

from shop.composition import Settings, build_container
from shop.observability import configure_logging

logger = logging.getLogger("shop.worker")


def run(settings: Settings, stop: threading.Event) -> None:
    if not settings.database_url:
        raise SystemExit("SHOP_DATABASE_URL is not set: there is no outbox to work on")
    with httpx.Client(timeout=settings.http_timeout) as client:
        container = build_container(settings, http_client=client)
        relay = container.relay
        if relay is None:
            raise SystemExit("the container has no outbox relay")
        logger.info("outbox worker started")
        while not stop.is_set():
            try:
                report = relay.run_once()
            except Exception:
                logger.exception("outbox poll failed")
                stop.wait(settings.outbox_poll_seconds)
                continue
            if report.delivered or report.retried or report.dead:
                logger.info(
                    "outbox batch: %s delivered, %s to retry, %s dead",
                    report.delivered,
                    report.retried,
                    report.dead,
                )
            else:
                stop.wait(settings.outbox_poll_seconds)
        logger.info("outbox worker stopped")


def main() -> None:
    configure_logging()
    stop = threading.Event()

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    run(Settings.from_env(), stop)


if __name__ == "__main__":
    main()
