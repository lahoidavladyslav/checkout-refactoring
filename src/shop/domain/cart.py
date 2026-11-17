"""Cart: the priced content of an order."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from shop.domain.errors import InvalidQuantityError, NoItemsError
from shop.domain.money import Money


@dataclass(frozen=True, slots=True)
class OrderLine:
    """A product line: a unit price and how many units are bought."""

    unit_price: Money
    quantity: int
    title: str | None = None

    @property
    def total(self) -> Money:
        return self.unit_price * self.quantity


@dataclass(frozen=True, slots=True)
class Cart:
    lines: tuple[OrderLine, ...]

    @classmethod
    def of(cls, lines: Sequence[OrderLine]) -> Cart:
        """Build a cart, enforcing that it is not empty and every quantity is positive."""
        if not lines:
            raise NoItemsError
        if any(line.quantity <= 0 for line in lines):
            raise InvalidQuantityError
        return cls(tuple(lines))

    @property
    def subtotal(self) -> Money:
        return Money.sum(line.total for line in self.lines)

    @property
    def units(self) -> int:
        return sum(line.quantity for line in self.lines)
