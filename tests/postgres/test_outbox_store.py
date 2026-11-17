from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import Engine, select

from shop.application.outbox import DeliveryStatus, DeliveryUpdate
from shop.domain.cart import OrderLine
from shop.domain.customer import CustomerType, EmailAddress
from shop.domain.events import OrderPlaced
from shop.domain.money import Money
from shop.domain.order import Order
from shop.infrastructure.sql.outbox import SqlOutboxStore
from shop.infrastructure.sql.repository import SqlOrderRepository
from shop.infrastructure.sql.tables import outbox
from tests.factories import NOW

LEASE = timedelta(minutes=2)


@pytest.fixture
def store(engine: Engine) -> SqlOutboxStore:
    return SqlOutboxStore(engine)


@pytest.fixture
def place_orders(engine: Engine) -> Callable[[int], None]:
    repository = SqlOrderRepository(engine)

    def place(count: int) -> None:
        for _ in range(count):
            repository.add(
                Order.place(
                    id=repository.next_id(),
                    email=EmailAddress("buyer@example.com"),
                    lines=(OrderLine(Money.from_uah("10"), 1),),
                    total=Money.from_uah("10"),
                    customer_type=CustomerType.REGULAR,
                    created_at=NOW,
                )
            )

    return place


def row(engine: Engine, message_id: int):  # type: ignore[no-untyped-def]  # a SQLAlchemy Row
    with engine.connect() as connection:
        return connection.execute(select(outbox).where(outbox.c.id == message_id)).one()


class TestClaiming:
    def test_a_stored_event_is_claimed_and_decoded(
        self, store: SqlOutboxStore, place_orders: Callable[[int], None]
    ) -> None:
        place_orders(1)

        (message,) = store.claim(limit=10, now=NOW, lease=LEASE)

        assert message.attempts == 0
        assert message.delivered_to == frozenset()
        assert message.event == OrderPlaced(
            occurred_at=NOW,
            order_id=1,
            email="buyer@example.com",
            total=Money.from_uah("10"),
            customer_type=CustomerType.REGULAR,
        )

    def test_a_claimed_message_is_leased_to_one_relay(
        self, store: SqlOutboxStore, place_orders: Callable[[int], None]
    ) -> None:
        place_orders(1)
        store.claim(limit=10, now=NOW, lease=LEASE)

        assert store.claim(limit=10, now=NOW + timedelta(seconds=30), lease=LEASE) == []

    def test_an_expired_lease_makes_the_message_claimable_again(
        self, store: SqlOutboxStore, place_orders: Callable[[int], None]
    ) -> None:
        """A relay that crashed mid-batch must not strand its messages."""
        place_orders(1)
        store.claim(limit=10, now=NOW, lease=LEASE)

        again = store.claim(limit=10, now=NOW + LEASE + timedelta(seconds=1), lease=LEASE)

        assert len(again) == 1

    def test_the_limit_and_the_order_are_respected(
        self, store: SqlOutboxStore, place_orders: Callable[[int], None]
    ) -> None:
        place_orders(5)

        claimed = store.claim(limit=3, now=NOW, lease=LEASE)

        assert [message.id for message in claimed] == [1, 2, 3]

    def test_a_message_scheduled_for_later_is_not_claimed(
        self, store: SqlOutboxStore, engine: Engine, place_orders: Callable[[int], None]
    ) -> None:
        place_orders(1)
        (message,) = store.claim(limit=1, now=NOW, lease=LEASE)
        store.update(
            message.id,
            DeliveryUpdate(
                DeliveryStatus.PENDING,
                1,
                frozenset(),
                next_attempt_at=NOW + timedelta(minutes=5),
                error="down",
            ),
        )

        assert store.claim(limit=1, now=NOW + timedelta(minutes=4), lease=LEASE) == []
        assert len(store.claim(limit=1, now=NOW + timedelta(minutes=5), lease=LEASE)) == 1

    def test_concurrent_relays_never_take_the_same_message(
        self, store: SqlOutboxStore, place_orders: Callable[[int], None]
    ) -> None:
        place_orders(40)

        def take(_: int) -> list[int]:
            return [m.id for m in store.claim(limit=5, now=NOW, lease=LEASE)]

        with ThreadPoolExecutor(max_workers=8) as pool:
            batches = list(pool.map(take, range(8)))

        claimed = [message_id for batch in batches for message_id in batch]
        assert len(claimed) == 40
        assert len(set(claimed)) == 40


class TestUpdating:
    def test_delivery_is_recorded_and_releases_the_lease(
        self, store: SqlOutboxStore, engine: Engine, place_orders: Callable[[int], None]
    ) -> None:
        place_orders(1)
        (message,) = store.claim(limit=1, now=NOW, lease=LEASE)

        store.update(
            message.id, DeliveryUpdate(DeliveryStatus.DELIVERED, 0, frozenset({"email", "slack"}))
        )

        stored = row(engine, message.id)
        assert stored.status == "delivered"
        assert stored.delivered_to == ["email", "slack"]
        assert stored.locked_until is None
        assert store.claim(limit=1, now=NOW + timedelta(days=1), lease=LEASE) == []

    def test_a_failure_keeps_what_was_already_delivered(
        self, store: SqlOutboxStore, place_orders: Callable[[int], None]
    ) -> None:
        place_orders(1)
        (message,) = store.claim(limit=1, now=NOW, lease=LEASE)
        store.update(
            message.id,
            DeliveryUpdate(
                DeliveryStatus.PENDING,
                1,
                frozenset({"email"}),
                next_attempt_at=NOW,
                error="slack: ConnectionError",
            ),
        )

        (again,) = store.claim(limit=1, now=NOW, lease=LEASE)

        assert again.attempts == 1
        assert again.delivered_to == frozenset({"email"})

    def test_a_dead_message_is_never_claimed_again(
        self, store: SqlOutboxStore, engine: Engine, place_orders: Callable[[int], None]
    ) -> None:
        place_orders(1)
        (message,) = store.claim(limit=1, now=NOW, lease=LEASE)

        store.update(
            message.id,
            DeliveryUpdate(DeliveryStatus.DEAD, 6, frozenset(), error="email: ConnectionError"),
        )

        assert row(engine, message.id).status == "dead"
        assert row(engine, message.id).last_error == "email: ConnectionError"
        assert store.claim(limit=1, now=NOW + timedelta(days=30), lease=LEASE) == []
