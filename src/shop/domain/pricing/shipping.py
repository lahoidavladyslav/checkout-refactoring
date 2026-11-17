"""Delivery method strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from shop.domain.money import Money


class ShippingMethod(Protocol):
    def cost(self, order_total: Money, city: str | None) -> Money:
        """Shipping cost for an order whose goods cost ``order_total`` after all discounts."""
        ...


@dataclass(frozen=True, slots=True)
class FlatRate:
    price: Money

    def cost(self, order_total: Money, city: str | None) -> Money:
        return self.price


@dataclass(frozen=True, slots=True)
class FreeAboveThreshold:
    """Free for orders strictly above a threshold, a flat price otherwise."""

    threshold: Money
    price: Money

    def cost(self, order_total: Money, city: str | None) -> Money:
        return Money.ZERO if order_total > self.threshold else self.price


@dataclass(frozen=True, slots=True)
class LocalOrRemoteRate:
    """One price inside a home city, a higher one anywhere else (or with no city given)."""

    home_city: str
    local_price: Money
    remote_price: Money

    def cost(self, order_total: Money, city: str | None) -> Money:
        return self.local_price if city == self.home_city else self.remote_price
