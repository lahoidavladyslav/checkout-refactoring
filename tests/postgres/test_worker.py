from __future__ import annotations

import threading
import time

import httpx
import pytest
from sqlalchemy import Engine, select

from shop.application.checkout import CheckoutCommand
from shop.composition import Settings, build_container
from shop.infrastructure.sql.tables import outbox
from shop.worker import run
from tests.factories import line

# Nothing listens here, so every delivery fails fast with a connection error.
DEAD_END = "http://127.0.0.1:9/"


def test_the_worker_polls_retries_and_stops_on_request(migrated_url: str, engine: Engine) -> None:
    settings = Settings(
        database_url=migrated_url,
        mail_url=DEAD_END,
        slack_url=DEAD_END,
        outbox_poll_seconds=0.05,
        outbox_base_delay_seconds=0.01,
        outbox_max_attempts=3,
    )
    with httpx.Client() as client:
        build_container(settings, http_client=client).checkout.place_order(
            CheckoutCommand(
                lines=(line(),), email="buyer@example.com", delivery="ukr", payment="cod"
            )
        )

    stop = threading.Event()
    worker = threading.Thread(target=run, args=(settings, stop))
    worker.start()
    try:
        deadline = time.monotonic() + 15
        status = "pending"
        while status != "dead" and time.monotonic() < deadline:
            time.sleep(0.1)
            with engine.connect() as connection:
                status = connection.execute(select(outbox.c.status)).scalar_one()
        assert status == "dead", "the worker should have retried and then given up"
    finally:
        stop.set()
        worker.join(timeout=10)

    assert not worker.is_alive()
    with engine.connect() as connection:
        assert connection.execute(select(outbox.c.attempts)).scalar_one() == 3


def test_the_worker_refuses_to_start_without_a_database() -> None:
    with pytest.raises(SystemExit):
        run(Settings(database_url=None), threading.Event())
