"""PostgreSQL implementation of the order repository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC
from typing import Any

from sqlalchemy import Connection, Engine, insert, select, update

from shop.domain.cart import OrderLine
from shop.domain.customer import CustomerType, EmailAddress
from shop.domain.errors import OrderNotFoundError
from shop.domain.events import DomainEvent
from shop.domain.money import Money
from shop.domain.order import Order, OrderStatus
from shop.infrastructure.event_codec import encode
from shop.infrastructure.sql.tables import order_ids, order_lines, orders, outbox


class SqlOrderRepository:
    """Stores orders in PostgreSQL.

    Every write is one database transaction, which is the unit of work of this adapter: the order
    row, its lines and (when ``record_events`` is on) the outbox rows for the events the aggregate
    has recorded either all become visible or none do. With events recorded in the same transaction
    an order can never exist without its notifications being owed, nor the other way round.
    """

    def __init__(self, engine: Engine, *, record_events: bool = True) -> None:
        self._engine = engine
        self._record_events = record_events

    def next_id(self) -> int:
        with self._engine.connect() as connection:
            value = connection.execute(select(order_ids.next_value())).scalar_one()
        return int(value)

    def add(self, order: Order) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                insert(orders).values(
                    id=order.id,
                    email=str(order.email),
                    customer_type=order.customer_type.value,
                    total_kopiyky=order.total.kopiyky,
                    status=order.status.value,
                    created_at=order.created_at,
                )
            )
            connection.execute(
                insert(order_lines),
                [
                    {
                        "order_id": order.id,
                        "position": position,
                        "unit_price_kopiyky": line.unit_price.kopiyky,
                        "quantity": line.quantity,
                        "title": line.title,
                    }
                    for position, line in enumerate(order.lines)
                ],
            )
            self._write_events(connection, order.pending_events)

    def save(self, order: Order) -> None:
        with self._engine.begin() as connection:
            result = connection.execute(
                update(orders).where(orders.c.id == order.id).values(status=order.status.value)
            )
            if result.rowcount == 0:
                raise OrderNotFoundError(f"order {order.id} does not exist")
            self._write_events(connection, order.pending_events)

    def get(self, order_id: int) -> Order | None:
        with self._engine.connect() as connection:
            row = connection.execute(select(orders).where(orders.c.id == order_id)).one_or_none()
            if row is None:
                return None
            lines = connection.execute(
                select(order_lines)
                .where(order_lines.c.order_id == order_id)
                .order_by(order_lines.c.position)
            ).all()
        return Order(
            id=row.id,
            email=EmailAddress(row.email),
            lines=tuple(
                OrderLine(Money(line.unit_price_kopiyky), line.quantity, line.title)
                for line in lines
            ),
            total=Money(row.total_kopiyky),
            customer_type=CustomerType(row.customer_type),
            # timestamptz comes back in the session's time zone; the domain works in UTC.
            created_at=row.created_at.astimezone(UTC),
            status=OrderStatus(row.status),
        )

    def _write_events(self, connection: Connection, events: Sequence[DomainEvent]) -> None:
        if not self._record_events or not events:
            return
        rows: list[dict[str, Any]] = []
        for event in events:
            event_type, payload = encode(event)
            rows.append(
                {
                    "event_type": event_type,
                    "payload": payload,
                    "occurred_at": event.occurred_at,
                    "next_attempt_at": event.occurred_at,
                }
            )
        connection.execute(insert(outbox), rows)
