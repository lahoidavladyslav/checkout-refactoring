"""PostgreSQL implementation of the outbox store."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Engine, or_, select
from sqlalchemy import update as sql_update

from shop.application.outbox import DeliveryStatus, DeliveryUpdate, OutboxMessage
from shop.infrastructure.event_codec import decode
from shop.infrastructure.sql.tables import outbox


class SqlOutboxStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def claim(self, *, limit: int, now: datetime, lease: timedelta) -> list[OutboxMessage]:
        """Atomically lease due messages.

        ``FOR UPDATE SKIP LOCKED`` lets several relays poll the same table without blocking each
        other or taking the same row, and the lease keeps a message claimed after this transaction
        has ended, so no database lock is held while subscribers run.
        """
        due = (
            select(outbox.c.id)
            .where(
                outbox.c.status == DeliveryStatus.PENDING.value,
                outbox.c.next_attempt_at <= now,
                or_(outbox.c.locked_until.is_(None), outbox.c.locked_until <= now),
            )
            .order_by(outbox.c.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        statement = (
            sql_update(outbox)
            .where(outbox.c.id.in_(due))
            .values(locked_until=now + lease)
            .returning(
                outbox.c.id,
                outbox.c.event_type,
                outbox.c.payload,
                outbox.c.attempts,
                outbox.c.delivered_to,
            )
        )
        with self._engine.begin() as connection:
            rows = connection.execute(statement).all()
        return [
            OutboxMessage(
                id=row.id,
                event=decode(row.event_type, row.payload),
                attempts=row.attempts,
                delivered_to=frozenset(row.delivered_to),
            )
            for row in sorted(rows, key=lambda row: row.id)
        ]

    def update(self, message_id: int, update_: DeliveryUpdate) -> None:
        values: dict[str, object] = {
            "status": update_.status.value,
            "attempts": update_.attempts,
            "delivered_to": sorted(update_.delivered_to),
            "last_error": update_.error,
            "locked_until": None,
        }
        if update_.next_attempt_at is not None:
            values["next_attempt_at"] = update_.next_attempt_at
        with self._engine.begin() as connection:
            connection.execute(sql_update(outbox).where(outbox.c.id == message_id).values(**values))
