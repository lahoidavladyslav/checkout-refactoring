"""Order storage adapters."""

from __future__ import annotations

import itertools
import threading

from shop.domain.order import Order


class InMemoryOrderRepository:
    """Keeps orders in process memory.

    Good for tests and local runs. It is not shared between processes, so a deployment with
    several workers needs a persistent implementation of the same port.
    """

    def __init__(self) -> None:
        self._orders: dict[int, Order] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def next_id(self) -> int:
        with self._lock:
            return next(self._ids)

    def add(self, order: Order) -> None:
        with self._lock:
            self._orders[order.id] = order

    def save(self, order: Order) -> None:
        with self._lock:
            self._orders[order.id] = order

    def get(self, order_id: int) -> Order | None:
        with self._lock:
            return self._orders.get(order_id)
