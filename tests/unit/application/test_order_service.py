from __future__ import annotations

import pytest

from shop.application.checkout import CheckoutCommand
from shop.domain.errors import InvalidTransitionError, OrderNotFoundError
from shop.domain.events import RefundRequested
from shop.domain.money import Money
from shop.domain.order import OrderStatus
from shop.domain.payment import CardToken
from tests.factories import NOW, line
from tests.fakes import World


@pytest.fixture
def world() -> World:
    return World()


def place(world: World, *, card: bool = False) -> int:
    order = world.checkout.place_order(
        CheckoutCommand(
            lines=(line("100"),),
            email="buyer@example.com",
            delivery="ukr",
            payment="card" if card else "cod",
            card=CardToken("tok") if card else None,
        )
    )
    return order.id


def test_unknown_order(world: World) -> None:
    with pytest.raises(OrderNotFoundError):
        world.orders.change_status(42, OrderStatus.PAID)


def test_full_lifecycle(world: World) -> None:
    order_id = place(world)

    for target in (OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DELIVERED):
        order = world.orders.change_status(order_id, target)
        assert order.status is target


def test_the_change_is_stored(world: World) -> None:
    order_id = place(world)

    world.orders.change_status(order_id, OrderStatus.PAID)

    stored = world.repository.get(order_id)
    assert stored is not None
    assert stored.status is OrderStatus.PAID


@pytest.mark.parametrize("target", list(OrderStatus))
def test_an_unpaid_order_cannot_skip_ahead(world: World, target: OrderStatus) -> None:
    order_id = place(world)

    if target in {OrderStatus.PAID, OrderStatus.CANCELLED}:
        world.orders.change_status(order_id, target)
        return
    with pytest.raises(InvalidTransitionError):
        world.orders.change_status(order_id, target)


def test_nothing_returns_to_new(world: World) -> None:
    order_id = place(world, card=True)

    with pytest.raises(InvalidTransitionError):
        world.orders.change_status(order_id, OrderStatus.NEW)


def test_a_delivered_order_is_final(world: World) -> None:
    order_id = place(world, card=True)
    for target in (OrderStatus.SHIPPED, OrderStatus.DELIVERED):
        world.orders.change_status(order_id, target)

    with pytest.raises(InvalidTransitionError):
        world.orders.change_status(order_id, OrderStatus.CANCELLED)


def test_cancelling_a_paid_order_publishes_a_refund_request(world: World) -> None:
    order_id = place(world, card=True)
    refunds: list[RefundRequested] = []
    world.events.subscribe(RefundRequested, refunds.append)

    world.orders.change_status(order_id, OrderStatus.CANCELLED)

    assert refunds == [
        RefundRequested(occurred_at=NOW, order_id=order_id, amount=Money.from_uah("145"))
    ]
