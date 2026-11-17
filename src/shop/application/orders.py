"""Use cases on existing orders."""

from __future__ import annotations

from shop.application.event_bus import EventBus
from shop.application.ports import Clock, OrderRepository
from shop.domain.errors import InvalidTransitionError, OrderNotFoundError
from shop.domain.order import Order, OrderStatus


class OrderService:
    def __init__(self, *, orders: OrderRepository, events: EventBus, clock: Clock) -> None:
        self._orders = orders
        self._events = events
        self._clock = clock

    def get(self, order_id: int) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"order {order_id} does not exist")
        return order

    def change_status(self, order_id: int, target: OrderStatus) -> Order:
        order = self.get(order_id)

        match target:
            case OrderStatus.PAID:
                order.pay()
            case OrderStatus.SHIPPED:
                order.ship()
            case OrderStatus.DELIVERED:
                order.deliver()
            case OrderStatus.CANCELLED:
                order.cancel(at=self._clock.now())
            case OrderStatus.NEW:
                raise InvalidTransitionError(f"order {order_id} cannot go back to new")

        self._orders.save(order)
        self._events.publish(order.pull_events())
        return order
