from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from shop.application.outbox import (
    DeliveryStatus,
    DeliveryUpdate,
    OutboxMessage,
    OutboxRelay,
    RetryPolicy,
    Subscription,
)
from shop.domain.customer import CustomerType
from shop.domain.events import OrderPlaced, RefundRequested
from shop.domain.money import Money
from tests.factories import NOW
from tests.fakes import FakeClock


def placed() -> OrderPlaced:
    return OrderPlaced(
        occurred_at=NOW,
        order_id=1,
        email="a@b.c",
        total=Money.from_uah("1"),
        customer_type=CustomerType.REGULAR,
    )


class FakeStore:
    """An outbox in a list, with the same claim and update contract as the real one."""

    def __init__(self) -> None:
        self.rows: dict[int, dict[str, Any]] = {}

    def add(self, event: Any = None) -> int:
        row_id = len(self.rows) + 1
        self.rows[row_id] = {
            "event": event or placed(),
            "attempts": 0,
            "delivered_to": frozenset[str](),
            "status": DeliveryStatus.PENDING,
            "next_attempt_at": NOW,
            "error": None,
        }
        return row_id

    def claim(self, *, limit: int, now: Any, lease: timedelta) -> list[OutboxMessage]:
        due = [
            OutboxMessage(i, r["event"], r["attempts"], r["delivered_to"])
            for i, r in sorted(self.rows.items())
            if r["status"] is DeliveryStatus.PENDING and r["next_attempt_at"] <= now
        ]
        return due[:limit]

    def update(self, message_id: int, update: DeliveryUpdate) -> None:
        row = self.rows[message_id]
        row.update(
            status=update.status,
            attempts=update.attempts,
            delivered_to=update.delivered_to,
            error=update.error,
        )
        if update.next_attempt_at:
            row["next_attempt_at"] = update.next_attempt_at


class Flaky:
    """A subscriber that fails a given number of times and then works."""

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0

    def __call__(self, event: Any) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("down")


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def relay(
    store: FakeStore,
    clock: FakeClock,
    subscriptions: dict[Any, list[Subscription]],
    policy: RetryPolicy | None = None,
) -> OutboxRelay:
    return OutboxRelay(
        store=store,
        subscriptions=subscriptions,
        clock=clock,
        policy=policy or RetryPolicy(max_attempts=4, base_delay=timedelta(seconds=10)),
    )


class TestRetryPolicy:
    @pytest.mark.parametrize(
        ("attempt", "seconds"),
        [(1, 10), (2, 20), (3, 40), (4, 80), (10, 3600), (50, 3600), (5000, 3600)],
    )
    def test_exponential_backoff_with_a_cap(self, attempt: int, seconds: int) -> None:
        policy = RetryPolicy(base_delay=timedelta(seconds=10), max_delay=timedelta(hours=1))

        assert policy.delay_after(attempt) == timedelta(seconds=seconds)


class TestDelivery:
    def test_delivers_to_every_subscriber(self, store: FakeStore, clock: FakeClock) -> None:
        first, second = Flaky(), Flaky()
        store.add()
        subs = {OrderPlaced: [Subscription("a", first), Subscription("b", second)]}

        report = relay(store, clock, subs).run_once()

        assert (first.calls, second.calls) == (1, 1)
        assert report.delivered == 1
        assert store.rows[1]["status"] is DeliveryStatus.DELIVERED

    def test_a_delivered_message_is_not_delivered_again(
        self, store: FakeStore, clock: FakeClock
    ) -> None:
        handler = Flaky()
        store.add()
        r = relay(store, clock, {OrderPlaced: [Subscription("a", handler)]})

        r.run_once()
        r.run_once()

        assert handler.calls == 1

    def test_an_event_nobody_listens_to_is_marked_delivered(
        self, store: FakeStore, clock: FakeClock
    ) -> None:
        store.add()

        relay(store, clock, {}).run_once()

        assert store.rows[1]["status"] is DeliveryStatus.DELIVERED

    def test_subscribers_are_chosen_by_event_type(self, store: FakeStore, clock: FakeClock) -> None:
        refunds = Flaky()
        store.add()

        relay(store, clock, {RefundRequested: [Subscription("r", refunds)]}).run_once()

        assert refunds.calls == 0


class TestRetries:
    def test_a_failure_schedules_a_retry_with_backoff(
        self, store: FakeStore, clock: FakeClock
    ) -> None:
        store.add()
        r = relay(store, clock, {OrderPlaced: [Subscription("a", Flaky(failures=9))]})

        report = r.run_once()

        row = store.rows[1]
        assert report.retried == 1
        assert row["status"] is DeliveryStatus.PENDING
        assert row["attempts"] == 1
        assert row["next_attempt_at"] == NOW + timedelta(seconds=10)
        assert row["error"] == "a: ConnectionError"

    def test_nothing_happens_before_the_retry_is_due(
        self, store: FakeStore, clock: FakeClock
    ) -> None:
        handler = Flaky(failures=1)
        store.add()
        r = relay(store, clock, {OrderPlaced: [Subscription("a", handler)]})
        r.run_once()

        clock.moment = NOW + timedelta(seconds=9)
        idle = r.run_once()

        assert idle == type(idle)()
        assert handler.calls == 1

    def test_the_delay_doubles_on_every_failure(self, store: FakeStore, clock: FakeClock) -> None:
        store.add()
        r = relay(store, clock, {OrderPlaced: [Subscription("a", Flaky(failures=9))]})
        gaps = []

        for _ in range(3):
            before = clock.moment
            r.run_once()
            gaps.append(store.rows[1]["next_attempt_at"] - before)
            clock.moment = store.rows[1]["next_attempt_at"]

        assert gaps == [timedelta(seconds=s) for s in (10, 20, 40)]

    def test_it_recovers_when_the_subscriber_comes_back(
        self, store: FakeStore, clock: FakeClock
    ) -> None:
        handler = Flaky(failures=2)
        store.add()
        r = relay(store, clock, {OrderPlaced: [Subscription("a", handler)]})

        for _ in range(3):
            r.run_once()
            clock.moment = store.rows[1]["next_attempt_at"]

        assert store.rows[1]["status"] is DeliveryStatus.DELIVERED
        assert handler.calls == 3

    def test_it_gives_up_after_the_maximum_number_of_attempts(
        self, store: FakeStore, clock: FakeClock
    ) -> None:
        handler = Flaky(failures=99)
        store.add()
        r = relay(store, clock, {OrderPlaced: [Subscription("a", handler)]})
        reports = []

        for _ in range(6):
            reports.append(r.run_once())
            clock.moment = store.rows[1]["next_attempt_at"]

        assert store.rows[1]["status"] is DeliveryStatus.DEAD
        assert store.rows[1]["attempts"] == 4
        assert sum(report.dead for report in reports) == 1
        assert handler.calls == 4

    def test_only_the_failed_subscriber_is_retried(
        self, store: FakeStore, clock: FakeClock
    ) -> None:
        email, slack = Flaky(), Flaky(failures=1)
        store.add()
        r = relay(
            store,
            clock,
            {OrderPlaced: [Subscription("email", email), Subscription("slack", slack)]},
        )

        r.run_once()
        clock.moment = store.rows[1]["next_attempt_at"]
        r.run_once()

        assert email.calls == 1, "the customer must not get the email twice"
        assert slack.calls == 2
        assert store.rows[1]["status"] is DeliveryStatus.DELIVERED

    def test_one_failing_message_does_not_block_the_others(
        self, store: FakeStore, clock: FakeClock
    ) -> None:
        handler = Flaky(failures=1)
        store.add()
        store.add()

        report = relay(store, clock, {OrderPlaced: [Subscription("a", handler)]}).run_once()

        assert (report.delivered, report.retried) == (1, 1)

    def test_a_failing_subscriber_does_not_stop_the_next_one_in_the_same_attempt(
        self, store: FakeStore, clock: FakeClock
    ) -> None:
        after = Flaky()
        store.add()

        relay(
            store,
            clock,
            {OrderPlaced: [Subscription("a", Flaky(failures=9)), Subscription("b", after)]},
        ).run_once()

        assert after.calls == 1
        assert store.rows[1]["delivered_to"] == frozenset({"b"})
