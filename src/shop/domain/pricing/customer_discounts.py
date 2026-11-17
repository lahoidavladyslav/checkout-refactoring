"""Discounts granted to a customer segment, independent of any promo code."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from shop.domain.money import Money


class CustomerDiscount(Protocol):
    def apply(self, total: Money) -> Money:
        """Return the total after the discount."""
        ...


@dataclass(frozen=True, slots=True)
class PercentageDiscount:
    """Pay ``100 - percent`` percent of the total."""

    percent: Decimal

    def apply(self, total: Money) -> Money:
        return total.scale(1 - self.percent / 100)
