"""Builders for domain objects used across test modules."""

from __future__ import annotations

from datetime import UTC, datetime

from shop.domain.cart import OrderLine
from shop.domain.customer import CustomerType, EmailAddress
from shop.domain.money import Money
from shop.domain.order import Order, OrderStatus

NOW = datetime(2025, 3, 14, 12, 0, tzinfo=UTC)


def line(price: str = "100", quantity: int = 1, title: str | None = None) -> OrderLine:
    return OrderLine(unit_price=Money.from_uah(price), quantity=quantity, title=title)


def an_order(
    *,
    id: int = 1,
    total: str = "145.00",
    customer_type: CustomerType = CustomerType.REGULAR,
    status: OrderStatus = OrderStatus.NEW,
) -> Order:
    return Order(
        id=id,
        email=EmailAddress("buyer@example.com"),
        lines=(line(),),
        total=Money.from_uah(total),
        customer_type=customer_type,
        created_at=NOW,
        status=status,
    )
