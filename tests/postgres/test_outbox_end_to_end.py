"""The whole path: checkout, PostgreSQL, outbox, relay, notification, with failures and retries."""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import Engine, select

from shop.application.checkout import CheckoutCommand
from shop.composition import Container, Settings, build_container
from shop.domain.errors import UnsupportedDeliveryError
from shop.domain.order import OrderStatus
from shop.domain.payment import CardToken
from shop.infrastructure.sql.tables import outbox
from tests.factories import NOW, line
from tests.fakes import FakeClock


class ExternalServices:
    def __init__(self) -> None:
        self.mail_up = True
        self.slack_up = True
        self.calls: list[tuple[str, dict[str, object]]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        body = json.loads(request.content)
        if host.startswith("payments."):
            return httpx.Response(200, json={"status": "ok"})
        up = self.mail_up if host.startswith("mail.") else self.slack_up
        if not up:
            return httpx.Response(503)
        self.calls.append((host.split(".")[0], body))
        return httpx.Response(200)

    def sent(self, service: str) -> list[dict[str, object]]:
        return [body for name, body in self.calls if name == service]


@pytest.fixture
def services() -> ExternalServices:
    return ExternalServices()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def app(
    migrated_url: str, engine: Engine, services: ExternalServices, clock: FakeClock
) -> Container:
    settings = Settings(
        database_url=migrated_url, outbox_max_attempts=4, outbox_base_delay_seconds=10
    )
    http = httpx.Client(transport=httpx.MockTransport(services.handle))
    return build_container(settings, http_client=http, clock=clock)


def checkout(app: Container, price: str = "100", *, card: bool = False) -> int:
    order = app.checkout.place_order(
        CheckoutCommand(
            lines=(line(price),),
            email="buyer@example.com",
            delivery="ukr",
            payment="card" if card else "cod",
            card=CardToken("tok") if card else None,
        )
    )
    return order.id


def statuses(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return [r.status for r in connection.execute(select(outbox).order_by(outbox.c.id))]


def test_checkout_stores_the_order_and_an_owed_notification_but_sends_nothing_yet(
    app: Container, engine: Engine, services: ExternalServices
) -> None:
    order_id = checkout(app)

    assert app.orders.get(order_id).status is OrderStatus.NEW
    assert statuses(engine) == ["pending"]
    assert services.calls == []


def test_the_relay_delivers_the_notifications(
    app: Container, engine: Engine, services: ExternalServices
) -> None:
    checkout(app, "10000", card=True)
    assert app.relay is not None

    report = app.relay.run_once()

    assert report.delivered == 1
    assert statuses(engine) == ["delivered"]
    assert services.sent("mail") == [
        {"to": "buyer@example.com", "template": "order", "total": 10045.0}
    ]
    assert services.sent("slack") == [{"text": "Big order 1"}]


def test_a_mail_outage_delays_the_email_instead_of_losing_it(
    app: Container, engine: Engine, services: ExternalServices, clock: FakeClock
) -> None:
    services.mail_up = False
    checkout(app)
    assert app.relay is not None

    first = app.relay.run_once()
    assert first.retried == 1
    assert statuses(engine) == ["pending"]
    assert services.sent("mail") == []

    services.mail_up = True
    clock.moment = NOW + timedelta(seconds=9)
    assert app.relay.run_once().delivered == 0, "not due yet"

    clock.moment = NOW + timedelta(seconds=10)
    assert app.relay.run_once().delivered == 1
    assert len(services.sent("mail")) == 1
    assert statuses(engine) == ["delivered"]


def test_a_retry_does_not_repeat_what_already_succeeded(
    app: Container, services: ExternalServices, clock: FakeClock
) -> None:
    """Slack is down for a big order; the customer's email must go out exactly once."""
    services.slack_up = False
    checkout(app, "20000", card=True)
    assert app.relay is not None

    app.relay.run_once()
    services.slack_up = True
    clock.moment = NOW + timedelta(seconds=10)
    app.relay.run_once()

    assert len(services.sent("mail")) == 1
    assert len(services.sent("slack")) == 1


def test_a_permanent_outage_ends_in_a_dead_message_after_the_maximum_attempts(
    app: Container, engine: Engine, services: ExternalServices, clock: FakeClock
) -> None:
    services.mail_up = False
    checkout(app)
    assert app.relay is not None

    for _ in range(4):
        app.relay.run_once()
        clock.moment += timedelta(hours=1)

    assert statuses(engine) == ["dead"]
    with engine.connect() as connection:
        stored = connection.execute(select(outbox)).one()
    assert stored.attempts == 4
    assert stored.last_error == "email: HTTPStatusError"
    assert app.relay.run_once().dead == 0, "a dead message is left alone"


def test_the_order_survives_a_notification_outage(
    app: Container, services: ExternalServices
) -> None:
    services.mail_up = False
    order_id = checkout(app)
    assert app.relay is not None

    app.relay.run_once()

    assert app.orders.get(order_id).status is OrderStatus.NEW


def test_a_refund_request_travels_through_the_outbox_too(app: Container, engine: Engine) -> None:
    order_id = checkout(app, card=True)
    assert app.relay is not None
    app.relay.run_once()

    app.orders.change_status(order_id, OrderStatus.CANCELLED)

    assert statuses(engine) == ["delivered", "pending"]
    assert app.relay.run_once().delivered == 1
    assert statuses(engine) == ["delivered", "delivered"]


def test_a_rejected_checkout_leaves_no_trace_in_the_outbox(app: Container, engine: Engine) -> None:
    with pytest.raises(UnsupportedDeliveryError):
        app.checkout.place_order(
            CheckoutCommand(
                lines=(line(),), email="buyer@example.com", delivery="dhl", payment="cod"
            )
        )

    assert statuses(engine) == []
