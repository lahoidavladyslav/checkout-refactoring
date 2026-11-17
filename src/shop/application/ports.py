"""Ports: what the application needs from the outside world.

They are ``Protocol`` classes owned by the application layer. Adapters in
``shop.infrastructure`` satisfy them structurally and never need to import this module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from shop.domain.events import OrderPlaced
from shop.domain.money import Money
from shop.domain.order import Order
from shop.domain.payment import CardToken


class PaymentGateway(Protocol):
    def charge(self, amount: Money, card: CardToken) -> bool:
        """Charge a card. ``True`` if the charge was approved, ``False`` if it was declined.

        Raises :class:`~shop.domain.errors.PaymentGatewayUnavailableError` when the provider
        cannot be reached or does not give a usable answer: that is not a decline.
        """
        ...


class OrderRepository(Protocol):
    def next_id(self) -> int: ...

    def add(self, order: Order) -> None: ...

    def save(self, order: Order) -> None: ...

    def get(self, order_id: int) -> Order | None: ...


class Notifier(Protocol):
    def notify(self, event: OrderPlaced) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, timezone-aware."""
        ...
