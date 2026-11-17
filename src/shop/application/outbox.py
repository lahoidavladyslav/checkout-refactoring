"""Reliable delivery of domain events through a transactional outbox.

The aggregate's events are stored in the same transaction as the aggregate. This relay then reads
the stored events and calls the subscribers, retrying failures with exponential backoff, so that
a down mail service delays a notification instead of losing it.

Delivery is **at least once**: if the process dies after a subscriber succeeded and before that
fact is recorded, the subscriber runs again on the next attempt. Subscribers should tolerate that.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from shop.application.ports import Clock
from shop.domain.events import DomainEvent

logger = logging.getLogger(__name__)


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    DEAD = "dead"


@dataclass(frozen=True, slots=True)
class Subscription:
    """A named subscriber. The name is what is remembered as "already delivered"."""

    name: str
    handler: Callable[[Any], None]


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    id: int
    event: DomainEvent
    attempts: int
    delivered_to: frozenset[str]


@dataclass(frozen=True, slots=True)
class DeliveryUpdate:
    status: DeliveryStatus
    attempts: int
    delivered_to: frozenset[str]
    next_attempt_at: datetime | None = None
    error: str | None = None


class OutboxStore(Protocol):
    def claim(self, *, limit: int, now: datetime, lease: timedelta) -> list[OutboxMessage]:
        """Take up to ``limit`` due messages and lease them so that no other relay takes them.

        A lease that expires (the relay crashed) makes the message claimable again.
        """
        ...

    def update(self, message_id: int, update: DeliveryUpdate) -> None: ...


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff: ``base_delay * factor ** (attempt - 1)``, capped at ``max_delay``."""

    max_attempts: int = 6
    base_delay: timedelta = timedelta(seconds=10)
    factor: float = 2.0
    max_delay: timedelta = timedelta(hours=1)

    def delay_after(self, attempt: int) -> timedelta:
        """How long to wait after the ``attempt``-th failed attempt (1-based)."""
        try:
            seconds = self.base_delay.total_seconds() * self.factor ** (attempt - 1)
        except OverflowError:
            return self.max_delay
        return min(timedelta(seconds=min(seconds, self.max_delay.total_seconds())), self.max_delay)


@dataclass(frozen=True, slots=True)
class RelayReport:
    delivered: int = 0
    retried: int = 0
    dead: int = 0


class OutboxRelay:
    def __init__(
        self,
        *,
        store: OutboxStore,
        subscriptions: Mapping[type[DomainEvent], Sequence[Subscription]],
        clock: Clock,
        policy: RetryPolicy | None = None,
        batch_size: int = 50,
        lease: timedelta = timedelta(minutes=2),
    ) -> None:
        self._store = store
        self._subscriptions = subscriptions
        self._clock = clock
        self._policy = policy or RetryPolicy()
        self._batch_size = batch_size
        self._lease = lease

    def run_once(self) -> RelayReport:
        """Process one batch of due messages."""
        now = self._clock.now()
        messages = self._store.claim(limit=self._batch_size, now=now, lease=self._lease)
        delivered = retried = dead = 0
        for message in messages:
            update = self._deliver(message, now)
            self._store.update(message.id, update)
            match update.status:
                case DeliveryStatus.DELIVERED:
                    delivered += 1
                case DeliveryStatus.DEAD:
                    dead += 1
                case DeliveryStatus.PENDING:
                    retried += 1
        return RelayReport(delivered=delivered, retried=retried, dead=dead)

    def _deliver(self, message: OutboxMessage, now: datetime) -> DeliveryUpdate:
        delivered_to = set(message.delivered_to)
        errors: list[str] = []
        for subscription in self._subscriptions.get(type(message.event), ()):
            if subscription.name in delivered_to:
                continue
            try:
                subscription.handler(message.event)
            except Exception as exc:
                logger.exception(
                    "outbox message %s: subscriber %r failed",
                    message.id,
                    subscription.name,
                )
                errors.append(f"{subscription.name}: {type(exc).__name__}")
            else:
                delivered_to.add(subscription.name)

        if not errors:
            return DeliveryUpdate(
                DeliveryStatus.DELIVERED, message.attempts, frozenset(delivered_to)
            )

        attempts = message.attempts + 1
        error = "; ".join(errors)
        if attempts >= self._policy.max_attempts:
            logger.error("outbox message %s gave up after %s attempts", message.id, attempts)
            return DeliveryUpdate(
                DeliveryStatus.DEAD, attempts, frozenset(delivered_to), error=error
            )
        return DeliveryUpdate(
            DeliveryStatus.PENDING,
            attempts,
            frozenset(delivered_to),
            next_attempt_at=now + self._policy.delay_after(attempts),
            error=error,
        )
