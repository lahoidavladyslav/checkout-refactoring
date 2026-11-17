from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

import pytest

from shop.application.checkout import CheckoutCommand
from shop.domain.customer import CustomerType
from shop.domain.errors import (
    CardRequiredError,
    CashOnDeliveryLimitError,
    InvalidEmailError,
    InvalidQuantityError,
    InvoiceNotAllowedError,
    NoItemsError,
    PaymentDeclinedError,
    PaymentGatewayUnavailableError,
    UnsupportedDeliveryError,
    UnsupportedPaymentMethodError,
)
from shop.domain.events import OrderPlaced
from shop.domain.money import Money
from shop.domain.order import OrderStatus
from shop.domain.payment import CardToken
from tests.factories import NOW, line
from tests.fakes import World


def command(**overrides: Any) -> CheckoutCommand:
    base = CheckoutCommand(
        lines=(line("100"),),
        email="buyer@example.com",
        delivery="ukr",
        payment="cod",
    )
    return replace(base, **overrides)


@pytest.fixture
def world() -> World:
    return World()


class TestPlacingAnOrder:
    def test_cash_on_delivery_order_is_created_unpaid(self, world: World) -> None:
        order = world.checkout.place_order(command())

        assert order.id == 1
        assert order.status is OrderStatus.NEW
        assert order.total == Money.from_uah("145")
        assert order.created_at == NOW
        assert world.repository.get(1) is order

    def test_card_order_is_charged_and_marked_paid(self, world: World) -> None:
        card = CardToken("tok_visa")

        order = world.checkout.place_order(command(payment="card", card=card))

        assert order.status is OrderStatus.PAID
        assert world.gateway.charges == [(Money.from_uah("145"), card)]

    def test_invoice_order_for_a_business_customer(self, world: World) -> None:
        order = world.checkout.place_order(command(payment="invoice", customer_type="b2b"))

        assert order.status is OrderStatus.NEW
        assert order.customer_type is CustomerType.B2B

    def test_the_order_keeps_what_was_bought(self, world: World) -> None:
        lines = (line("100", 2, "Mug"), line("50", 1, "Pen"))

        order = world.checkout.place_order(command(lines=lines))

        assert order.lines == lines

    def test_the_total_follows_the_pricing_rules(self, world: World) -> None:
        order = world.checkout.place_order(
            command(lines=(line("1000"),), promo_code="SALE10", customer_type="vip")
        )

        assert order.total == Money.from_uah("900")


class TestRejections:
    """A rejected checkout has no side effects: no order, no id, no event."""

    @pytest.mark.parametrize(
        ("overrides", "error"),
        [
            ({"lines": ()}, NoItemsError),
            ({"email": "nope"}, InvalidEmailError),
            ({"lines": (line(quantity=0),)}, InvalidQuantityError),
            ({"delivery": "dhl"}, UnsupportedDeliveryError),
            ({"delivery": None}, UnsupportedDeliveryError),
            ({"lines": (line("5000"),)}, CashOnDeliveryLimitError),
            ({"payment": "invoice"}, InvoiceNotAllowedError),
            ({"payment": "card", "card": None}, CardRequiredError),
            ({"payment": "crypto"}, UnsupportedPaymentMethodError),
            ({"payment": ""}, UnsupportedPaymentMethodError),
            ({"payment": None}, UnsupportedPaymentMethodError),
        ],
    )
    def test_rejected(
        self, world: World, overrides: dict[str, object], error: type[Exception]
    ) -> None:
        with pytest.raises(error):
            world.checkout.place_order(command(**overrides))

        assert world.repository.get(1) is None
        assert world.notifier.received == []
        assert world.repository.next_id() == 1

    def test_the_first_problem_is_the_one_reported(self, world: World) -> None:
        with pytest.raises(NoItemsError):
            world.checkout.place_order(command(lines=(), email="nope"))
        with pytest.raises(InvalidEmailError):
            world.checkout.place_order(command(lines=(line(quantity=0),), email="nope"))

    def test_declined_card_creates_nothing(self, world: World) -> None:
        world.gateway.approve = False

        with pytest.raises(PaymentDeclinedError):
            world.checkout.place_order(command(payment="card", card=CardToken("tok")))

        assert world.repository.get(1) is None
        assert world.notifier.received == []

    def test_unreachable_gateway_creates_nothing(self, world: World) -> None:
        world.gateway.unavailable = True

        with pytest.raises(PaymentGatewayUnavailableError):
            world.checkout.place_order(command(payment="card", card=CardToken("tok")))

        assert world.repository.get(1) is None

    def test_the_card_is_not_charged_when_the_order_is_invalid(self, world: World) -> None:
        with pytest.raises(UnsupportedDeliveryError):
            world.checkout.place_order(
                command(payment="card", card=CardToken("tok"), delivery="dhl")
            )

        assert world.gateway.charges == []


class TestEvents:
    def test_order_placed_is_published(self, world: World) -> None:
        order = world.checkout.place_order(command(customer_type="vip"))

        assert world.notifier.received == [
            OrderPlaced(
                occurred_at=NOW,
                order_id=order.id,
                email="buyer@example.com",
                total=order.total,
                customer_type=CustomerType.VIP,
            )
        ]

    def test_subscribers_see_an_order_that_is_already_stored(self, world: World) -> None:
        seen: list[bool] = []
        world.events.subscribe(
            OrderPlaced, lambda event: seen.append(world.repository.get(event.order_id) is not None)
        )

        world.checkout.place_order(command())

        assert seen == [True]

    def test_a_failing_subscriber_does_not_fail_the_checkout(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        def broken(event: OrderPlaced) -> None:
            raise RuntimeError("mail server is down")

        world.events.subscribe(OrderPlaced, broken)

        with caplog.at_level(logging.ERROR):
            order = world.checkout.place_order(command())

        assert world.repository.get(order.id) is order
        assert "broken" in caplog.text
        assert "mail server is down" in caplog.text

    def test_a_failing_subscriber_does_not_starve_the_next_one(self, world: World) -> None:
        def broken(event: OrderPlaced) -> None:
            raise RuntimeError

        late: list[OrderPlaced] = []
        world.events.subscribe(OrderPlaced, broken)
        world.events.subscribe(OrderPlaced, late.append)

        world.checkout.place_order(command())

        assert len(late) == 1


class TestCardSecrecy:
    def test_the_card_is_not_part_of_the_order_or_its_event(self, world: World) -> None:
        card = CardToken("4111111111111111")

        order = world.checkout.place_order(command(payment="card", card=card))

        assert "4111" not in repr(vars(order))
        assert "4111" not in repr(world.notifier.received)

    def test_the_card_does_not_show_up_in_repr_or_str(self) -> None:
        card = CardToken("4111111111111111")

        assert "4111" not in repr(card)
        assert "4111" not in str(card)
        assert "4111" not in repr(command(card=card))
