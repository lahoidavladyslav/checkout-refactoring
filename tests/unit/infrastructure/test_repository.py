from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from shop.infrastructure.repositories import InMemoryOrderRepository
from tests.factories import an_order


def test_ids_start_at_one_and_increase() -> None:
    repository = InMemoryOrderRepository()

    assert [repository.next_id() for _ in range(3)] == [1, 2, 3]


def test_ids_are_unique_under_concurrency() -> None:
    repository = InMemoryOrderRepository()

    with ThreadPoolExecutor(max_workers=16) as pool:
        ids = list(pool.map(lambda _: repository.next_id(), range(2000)))

    assert len(set(ids)) == 2000


def test_add_get_and_save() -> None:
    repository = InMemoryOrderRepository()
    order = an_order(id=5)

    repository.add(order)
    order.pay()
    repository.save(order)

    assert repository.get(5) is order


def test_get_unknown_returns_none() -> None:
    assert InMemoryOrderRepository().get(1) is None
