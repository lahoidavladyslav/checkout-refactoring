"""Money value object."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import ClassVar

from shop.domain.errors import InvalidMoneyError

KOPIYKY_PER_UAH = 100
_ONE = Decimal(1)
_CENT = Decimal("0.01")

# The single rounding rule of the whole system: halves go away from zero, so 0.5 kopiyky
# becomes 1. It is the rule a customer expects from a receipt and, unlike ``round()`` on a
# float, it is applied to an exact decimal value.
ROUNDING = ROUND_HALF_UP


@dataclass(frozen=True, order=True, slots=True)
class Money:
    """A non-negative amount of hryvnias, stored as a whole number of kopiyky.

    Integers make addition and comparison exact. Fractions of a kopiyk can only appear when
    multiplying by a rate (:meth:`scale`), where the result is rounded once, explicitly, with
    :data:`ROUNDING`.

    The class is deliberately single-currency: introducing a second currency would add a
    currency field and cross-currency checks, which nothing needs yet.
    """

    kopiyky: int

    ZERO: ClassVar[Money]

    def __post_init__(self) -> None:
        if isinstance(self.kopiyky, bool) or not isinstance(self.kopiyky, int):
            raise InvalidMoneyError(f"amount in kopiyky must be an int, got {self.kopiyky!r}")
        if self.kopiyky < 0:
            raise InvalidMoneyError(f"amount must not be negative, got {self.kopiyky} kopiyky")

    @classmethod
    def from_uah(cls, amount: Decimal | int | str) -> Money:
        """Build from hryvnias. Floats are rejected on purpose, pass a ``str`` or ``Decimal``."""
        if isinstance(amount, bool) or not isinstance(amount, Decimal | int | str):
            raise InvalidMoneyError(f"cannot build money from {type(amount).__name__}")
        try:
            value = Decimal(amount)
        except InvalidOperation as exc:
            raise InvalidMoneyError(f"not a number: {amount!r}") from exc
        if not value.is_finite():
            raise InvalidMoneyError(f"not a finite number: {amount!r}")
        if value != value.quantize(_CENT):
            raise InvalidMoneyError(f"{amount!r} has a fraction of a kopiyk")
        return cls(int(value * KOPIYKY_PER_UAH))

    @classmethod
    def sum(cls, amounts: Iterable[Money]) -> Money:
        total = cls.ZERO
        for amount in amounts:
            total += amount
        return total

    def to_uah(self) -> Decimal:
        return Decimal(self.kopiyky).scaleb(-2)

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self.kopiyky + other.kopiyky)

    def __sub__(self, other: Money) -> Money:
        """Subtract; the result must stay non-negative."""
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self.kopiyky - other.kopiyky)

    def __mul__(self, quantity: int) -> Money:
        """Multiply by a whole quantity. Exact, no rounding involved."""
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            return NotImplemented
        return Money(self.kopiyky * quantity)

    __rmul__ = __mul__

    def scale(self, factor: Decimal) -> Money:
        """Multiply by a rate, rounding once with :data:`ROUNDING`.

        ``Money.from_uah("100").scale(Decimal("0.95"))`` is the amount after a 5% discount.
        """
        scaled = (Decimal(self.kopiyky) * factor).quantize(_ONE, rounding=ROUNDING)
        return Money(int(scaled))

    def percent(self, rate: Decimal) -> Money:
        """The given percentage of this amount, e.g. ``percent(Decimal(10))`` is 10%."""
        return self.scale(rate / 100)

    def is_zero(self) -> bool:
        return self.kopiyky == 0

    def __str__(self) -> str:
        return f"{self.to_uah():.2f}"

    def __repr__(self) -> str:
        return f"Money({self})"


Money.ZERO = Money(0)
