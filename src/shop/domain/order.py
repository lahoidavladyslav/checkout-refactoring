"""The Order aggregate and its status state machine."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum

from shop.domain.cart import OrderLine
from shop.domain.customer import CustomerType, EmailAddress
from shop.domain.errors import InvalidTransitionError
from shop.domain.events import DomainEvent, OrderPlaced, RefundRequested
from shop.domain.money import Money


class OrderStatus(StrEnum):
    NEW = "new"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


_TRANSITIONS: Mapping[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.NEW: frozenset({OrderStatus.PAID, OrderStatus.CANCELLED}),
    OrderStatus.PAID: frozenset({OrderStatus.SHIPPED, OrderStatus.CANCELLED}),
    OrderStatus.SHIPPED: frozenset({OrderStatus.DELIVERED}),
    OrderStatus.DELIVERED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}


class Order:
    """A placed order.

    The status can only change through :meth:`pay`, :meth:`ship`, :meth:`deliver` and
    :meth:`cancel`, which enforce the transition table. Events that the order wants to publish
    are collected and handed over with :meth:`pull_events`, so that nothing is announced before
    the order has actually been persisted.
    """

    def __init__(
        self,
        *,
        id: int,  # "id" is the natural name of an aggregate identifier
        email: EmailAddress,
        lines: tuple[OrderLine, ...],
        total: Money,
        customer_type: CustomerType,
        created_at: datetime,
        status: OrderStatus = OrderStatus.NEW,
    ) -> None:
        if created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        self.id = id
        self.email = email
        self.lines = lines
        self.total = total
        self.customer_type = customer_type
        self.created_at = created_at
        self._status = status
        self._events: list[DomainEvent] = []

    @classmethod
    def place(
        cls,
        *,
        id: int,
        email: EmailAddress,
        lines: tuple[OrderLine, ...],
        total: Money,
        customer_type: CustomerType,
        created_at: datetime,
    ) -> Order:
        order = cls(
            id=id,
            email=email,
            lines=lines,
            total=total,
            customer_type=customer_type,
            created_at=created_at,
        )
        order._events.append(
            OrderPlaced(
                occurred_at=created_at,
                order_id=id,
                email=str(email),
                total=total,
                customer_type=customer_type,
            )
        )
        return order

    @property
    def status(self) -> OrderStatus:
        return self._status

    def pay(self) -> None:
        self._move_to(OrderStatus.PAID)

    def ship(self) -> None:
        self._move_to(OrderStatus.SHIPPED)

    def deliver(self) -> None:
        self._move_to(OrderStatus.DELIVERED)

    def cancel(self, *, at: datetime) -> None:
        """Cancel the order. A paid order also asks for its money back."""
        was_paid = self._status is OrderStatus.PAID
        self._move_to(OrderStatus.CANCELLED)
        if was_paid:
            self._events.append(
                RefundRequested(occurred_at=at, order_id=self.id, amount=self.total)
            )

    def can_move_to(self, target: OrderStatus) -> bool:
        return target in _TRANSITIONS[self._status]

    def pull_events(self) -> list[DomainEvent]:
        """Return the recorded events and forget them."""
        events, self._events = self._events, []
        return events

    def _move_to(self, target: OrderStatus) -> None:
        if not self.can_move_to(target):
            raise InvalidTransitionError(
                f"order {self.id} cannot go from {self._status} to {target}"
            )
        self._status = target
