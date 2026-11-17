from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import Engine, delete, func, insert, select
from sqlalchemy.exc import IntegrityError

from shop.domain.cart import OrderLine
from shop.domain.customer import CustomerType, EmailAddress
from shop.domain.errors import InvalidTransitionError, OrderNotFoundError
from shop.domain.money import Money
from shop.domain.order import Order, OrderStatus
from shop.infrastructure.sql.repository import SqlOrderRepository
from shop.infrastructure.sql.tables import order_lines, orders, outbox
from tests.factories import NOW


def place(repository: SqlOrderRepository, **overrides: object) -> Order:
    fields: dict[str, object] = {
        "id": repository.next_id(),
        "email": EmailAddress("buyer@example.com"),
        "lines": (
            OrderLine(Money.from_uah("100.50"), 2, "Mug"),
            OrderLine(Money.from_uah("30"), 1, None),
        ),
        "total": Money.from_uah("276"),
        "customer_type": CustomerType.VIP,
        "created_at": NOW,
    }
    fields.update(overrides)
    return Order.place(**fields)  # type: ignore[arg-type]  # keyword names are the Order fields


def count(engine: Engine, table: object) -> int:
    with engine.connect() as connection:
        return int(connection.execute(select(func.count()).select_from(table)).scalar_one())  # type: ignore[arg-type]


@pytest.fixture
def repository(engine: Engine) -> SqlOrderRepository:
    return SqlOrderRepository(engine)


class TestStoringOrders:
    def test_an_order_round_trips(self, repository: SqlOrderRepository) -> None:
        order = place(repository)

        repository.add(order)
        loaded = repository.get(order.id)

        assert loaded is not None
        assert loaded.id == order.id
        assert str(loaded.email) == "buyer@example.com"
        assert loaded.total == Money.from_uah("276")
        assert loaded.customer_type is CustomerType.VIP
        assert loaded.status is OrderStatus.NEW
        assert loaded.lines == order.lines
        assert loaded.created_at == NOW
        assert loaded.created_at.utcoffset() == timedelta(0)

    def test_lines_keep_their_order(self, repository: SqlOrderRepository) -> None:
        lines = tuple(OrderLine(Money.from_uah(str(n)), 1, f"item {n}") for n in (9, 3, 7, 1, 5))
        order = place(repository, lines=lines)

        repository.add(order)

        loaded = repository.get(order.id)
        assert loaded is not None
        assert [line.title for line in loaded.lines] == [f"item {n}" for n in (9, 3, 7, 1, 5)]

    def test_amounts_are_stored_as_whole_kopiyky(
        self, repository: SqlOrderRepository, engine: Engine
    ) -> None:
        order = place(repository, total=Money.from_uah("276.01"))
        repository.add(order)

        with engine.connect() as connection:
            stored = connection.execute(select(orders.c.total_kopiyky)).scalar_one()

        assert stored == 27601

    def test_unknown_order(self, repository: SqlOrderRepository) -> None:
        assert repository.get(404) is None

    def test_ids_increase(self, repository: SqlOrderRepository) -> None:
        assert [repository.next_id() for _ in range(3)] == [1, 2, 3]

    def test_a_timestamp_with_another_offset_is_the_same_instant(
        self, repository: SqlOrderRepository
    ) -> None:
        local = datetime(2025, 3, 14, 14, 0, tzinfo=timezone_plus_two())
        order = place(repository, created_at=local)

        repository.add(order)

        loaded = repository.get(order.id)
        assert loaded is not None
        assert loaded.created_at == local


def timezone_plus_two() -> timezone:
    return timezone(timedelta(hours=2))


class TestUpdatingOrders:
    def test_save_persists_the_new_status(self, repository: SqlOrderRepository) -> None:
        order = place(repository)
        repository.add(order)
        order.pay()
        order.ship()

        repository.save(order)

        loaded = repository.get(order.id)
        assert loaded is not None
        assert loaded.status is OrderStatus.SHIPPED

    def test_saving_an_order_that_was_never_added_fails(
        self, repository: SqlOrderRepository
    ) -> None:
        with pytest.raises(OrderNotFoundError):
            repository.save(place(repository))

    def test_a_loaded_order_still_enforces_the_state_machine(
        self, repository: SqlOrderRepository
    ) -> None:

        order = place(repository)
        repository.add(order)
        loaded = repository.get(order.id)
        assert loaded is not None

        with pytest.raises(InvalidTransitionError):
            loaded.deliver()


class TestDatabaseConstraints:
    """The schema refuses what the domain would refuse, even for a buggy writer."""

    @pytest.mark.parametrize(
        "values",
        [{"status": "banana"}, {"total_kopiyky": -1}],
    )
    def test_orders_reject_invalid_rows(self, engine: Engine, values: dict[str, object]) -> None:

        row = {
            "id": 1,
            "email": "a@b.c",
            "customer_type": "regular",
            "total_kopiyky": 1,
            "status": "new",
            "created_at": datetime(2025, 1, 1, tzinfo=UTC),
        } | values

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(insert(orders).values(**row))

    def test_lines_must_have_a_positive_quantity(
        self, repository: SqlOrderRepository, engine: Engine
    ) -> None:

        order = place(repository)
        repository.add(order)

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert(order_lines).values(
                    order_id=order.id, position=9, unit_price_kopiyky=1, quantity=0
                )
            )

    def test_deleting_an_order_removes_its_lines(
        self, repository: SqlOrderRepository, engine: Engine
    ) -> None:

        order = place(repository)
        repository.add(order)

        with engine.begin() as connection:
            connection.execute(delete(orders).where(orders.c.id == order.id))

        assert count(engine, order_lines) == 0


class TestUnitOfWork:
    def test_the_order_and_its_events_are_stored_together(
        self, repository: SqlOrderRepository, engine: Engine
    ) -> None:
        repository.add(place(repository))

        assert count(engine, orders) == 1
        assert count(engine, order_lines) == 2
        assert count(engine, outbox) == 1

    def test_if_storing_the_events_fails_nothing_is_stored(
        self, repository: SqlOrderRepository, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken(event: object) -> tuple[str, dict[str, object]]:
            raise RuntimeError("cannot serialise")

        monkeypatch.setattr("shop.infrastructure.sql.repository.encode", broken)

        with pytest.raises(RuntimeError):
            repository.add(place(repository))

        assert (count(engine, orders), count(engine, order_lines), count(engine, outbox)) == (
            0,
            0,
            0,
        )

    def test_a_duplicate_order_stores_no_second_event(
        self, repository: SqlOrderRepository, engine: Engine
    ) -> None:

        order = place(repository)
        repository.add(order)

        with pytest.raises(IntegrityError):
            repository.add(order)

        assert count(engine, orders) == 1
        assert count(engine, outbox) == 1

    def test_a_status_change_and_its_event_are_stored_together(
        self, repository: SqlOrderRepository, engine: Engine
    ) -> None:
        order = place(repository)
        repository.add(order)
        order.pull_events()
        order.pay()
        order.cancel(at=NOW)

        repository.save(order)

        assert count(engine, outbox) == 2  # OrderPlaced from add, RefundRequested from save

    def test_events_can_be_turned_off(self, engine: Engine) -> None:
        repository = SqlOrderRepository(engine, record_events=False)

        repository.add(place(repository))

        assert count(engine, orders) == 1
        assert count(engine, outbox) == 0
