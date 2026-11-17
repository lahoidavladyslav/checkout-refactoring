from __future__ import annotations

from datetime import datetime

import pytest

from shop.domain.customer import CustomerType, EmailAddress
from shop.domain.errors import InvalidTransitionError
from shop.domain.events import OrderPlaced, RefundRequested
from shop.domain.money import Money
from shop.domain.order import Order, OrderStatus
from tests.factories import NOW, an_order, line

NEW, PAID, SHIPPED, DELIVERED, CANCELLED = (
    OrderStatus.NEW,
    OrderStatus.PAID,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
    OrderStatus.CANCELLED,
)

ALLOWED = {
    (NEW, PAID),
    (NEW, CANCELLED),
    (PAID, SHIPPED),
    (PAID, CANCELLED),
    (SHIPPED, DELIVERED),
}


def _apply(order: Order, target: OrderStatus) -> None:
    actions = {
        PAID: order.pay,
        SHIPPED: order.ship,
        DELIVERED: order.deliver,
        CANCELLED: lambda: order.cancel(at=NOW),
    }
    if target is NEW:
        raise InvalidTransitionError("nothing leads back to new")
    actions[target]()


class TestTransitions:
    @pytest.mark.parametrize(("source", "target"), sorted(ALLOWED))
    def test_allowed_transition(self, source: OrderStatus, target: OrderStatus) -> None:
        order = an_order(status=source)

        _apply(order, target)

        assert order.status is target

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            (source, target)
            for source in OrderStatus
            for target in OrderStatus
            if (source, target) not in ALLOWED
        ],
    )
    def test_forbidden_transition(self, source: OrderStatus, target: OrderStatus) -> None:
        order = an_order(status=source)

        with pytest.raises(InvalidTransitionError):
            _apply(order, target)

        assert order.status is source

    def test_delivered_cannot_return_to_new(self) -> None:
        """What the legacy change_status allowed."""
        order = an_order(status=DELIVERED)

        assert not order.can_move_to(NEW)

    def test_happy_path(self) -> None:
        order = an_order()

        order.pay()
        order.ship()
        order.deliver()

        assert order.status is DELIVERED

    def test_status_is_read_only(self) -> None:
        order = an_order()

        with pytest.raises(AttributeError):
            order.status = PAID  # type: ignore[misc]  # the property has no setter by design

    def test_error_names_the_order_and_both_statuses(self) -> None:
        order = an_order(id=7, status=DELIVERED)

        with pytest.raises(InvalidTransitionError, match=r"order 7 .* delivered to shipped"):
            order.ship()


class TestPlacing:
    def test_a_placed_order_carries_what_it_was_given_and_starts_new(self) -> None:
        lines = (line("100", 2), line("30"))

        order = Order.place(
            id=3,
            email=EmailAddress("buyer@example.com"),
            lines=lines,
            total=Money.from_uah("245"),
            customer_type=CustomerType.VIP,
            created_at=NOW,
        )

        assert order.id == 3
        assert str(order.email) == "buyer@example.com"
        assert order.lines == lines
        assert order.total == Money.from_uah("245")
        assert order.customer_type is CustomerType.VIP
        assert order.created_at == NOW
        assert order.status is NEW

    def test_pending_events_can_be_read_without_consuming_them(self) -> None:
        order = Order.place(
            id=1,
            email=EmailAddress("buyer@example.com"),
            lines=(line(),),
            total=Money.from_uah("100"),
            customer_type=CustomerType.REGULAR,
            created_at=NOW,
        )

        assert order.pending_events == tuple(order.pull_events())
        assert order.pending_events == ()


class TestEvents:
    def test_placing_records_order_placed(self) -> None:
        order = Order.place(
            id=3,
            email=EmailAddress("buyer@example.com"),
            lines=(line("100", 2),),
            total=Money.from_uah("245"),
            customer_type=CustomerType.VIP,
            created_at=NOW,
        )

        assert order.pull_events() == [
            OrderPlaced(
                occurred_at=NOW,
                order_id=3,
                email="buyer@example.com",
                total=Money.from_uah("245"),
                customer_type=CustomerType.VIP,
            )
        ]

    def test_events_are_handed_over_once(self) -> None:
        order = Order.place(
            id=1,
            email=EmailAddress("buyer@example.com"),
            lines=(line(),),
            total=Money.from_uah("100"),
            customer_type=CustomerType.REGULAR,
            created_at=NOW,
        )

        order.pull_events()

        assert order.pull_events() == []

    def test_cancelling_a_paid_order_requests_a_refund(self) -> None:
        order = an_order(total="145.00", status=PAID)

        order.cancel(at=NOW)

        assert order.pull_events() == [
            RefundRequested(occurred_at=NOW, order_id=1, amount=Money.from_uah("145.00"))
        ]

    def test_cancelling_an_unpaid_order_requests_nothing(self) -> None:
        order = an_order(status=NEW)

        order.cancel(at=NOW)

        assert order.pull_events() == []

    def test_a_failed_cancellation_records_nothing(self) -> None:
        order = an_order(status=SHIPPED)

        with pytest.raises(InvalidTransitionError):
            order.cancel(at=NOW)

        assert order.pull_events() == []


def test_created_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match=r"^created_at must be timezone-aware$"):
        Order(
            id=1,
            email=EmailAddress("buyer@example.com"),
            lines=(line(),),
            total=Money.from_uah("1"),
            customer_type=CustomerType.REGULAR,
            created_at=datetime(2025, 1, 1),  # noqa: DTZ001  # naive on purpose
        )
