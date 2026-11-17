"""Domain events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from shop.domain.customer import CustomerType
from shop.domain.money import Money


@dataclass(frozen=True, slots=True)
class DomainEvent:
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class OrderPlaced(DomainEvent):
    """An order was created (and persisted by the time subscribers see this)."""

    order_id: int
    email: str
    total: Money
    customer_type: CustomerType


@dataclass(frozen=True, slots=True)
class RefundRequested(DomainEvent):
    """A paid order was cancelled, so the customer's money has to be returned."""

    order_id: int
    amount: Money
