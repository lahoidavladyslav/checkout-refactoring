"""Serialisation of domain events for the outbox."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from shop.domain.customer import CustomerType
from shop.domain.events import DomainEvent, OrderPlaced, RefundRequested
from shop.domain.money import Money

ORDER_PLACED = "order_placed"
REFUND_REQUESTED = "refund_requested"


class UnknownEventError(Exception):
    """An outbox row refers to an event type this version of the code does not know."""


def encode(event: DomainEvent) -> tuple[str, dict[str, Any]]:
    """Return the event's type name and a JSON-safe payload.

    Money travels as integer kopiyky, timestamps as ISO 8601 with their offset.
    """
    if isinstance(event, OrderPlaced):
        return ORDER_PLACED, {
            "occurred_at": event.occurred_at.isoformat(),
            "order_id": event.order_id,
            "email": event.email,
            "total_kopiyky": event.total.kopiyky,
            "customer_type": event.customer_type.value,
        }
    if isinstance(event, RefundRequested):
        return REFUND_REQUESTED, {
            "occurred_at": event.occurred_at.isoformat(),
            "order_id": event.order_id,
            "amount_kopiyky": event.amount.kopiyky,
        }
    raise UnknownEventError(f"cannot encode {type(event).__name__}")


def decode(event_type: str, payload: dict[str, Any]) -> DomainEvent:
    occurred_at = datetime.fromisoformat(payload["occurred_at"])
    if event_type == ORDER_PLACED:
        return OrderPlaced(
            occurred_at=occurred_at,
            order_id=payload["order_id"],
            email=payload["email"],
            total=Money(payload["total_kopiyky"]),
            customer_type=CustomerType(payload["customer_type"]),
        )
    if event_type == REFUND_REQUESTED:
        return RefundRequested(
            occurred_at=occurred_at,
            order_id=payload["order_id"],
            amount=Money(payload["amount_kopiyky"]),
        )
    raise UnknownEventError(f"cannot decode event type {event_type!r}")
