from __future__ import annotations

from shop.application.event_bus import EventBus
from shop.domain.customer import CustomerType
from shop.domain.events import OrderPlaced, RefundRequested
from shop.domain.money import Money
from tests.factories import NOW


def placed() -> OrderPlaced:
    return OrderPlaced(
        occurred_at=NOW,
        order_id=1,
        email="a@b.c",
        total=Money.from_uah("1"),
        customer_type=CustomerType.REGULAR,
    )


def test_handlers_receive_only_their_event_type() -> None:
    bus = EventBus()
    received: list[object] = []
    bus.subscribe(OrderPlaced, received.append)
    event = placed()

    bus.publish([event, RefundRequested(occurred_at=NOW, order_id=1, amount=Money.ZERO)])

    assert received == [event]


def test_handlers_run_in_subscription_order() -> None:
    bus = EventBus()
    calls: list[str] = []
    bus.subscribe(OrderPlaced, lambda _: calls.append("first"))
    bus.subscribe(OrderPlaced, lambda _: calls.append("second"))

    bus.publish([placed()])

    assert calls == ["first", "second"]


def test_publishing_without_subscribers_is_fine() -> None:
    EventBus().publish([placed()])
