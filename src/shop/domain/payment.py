"""Payment-related value objects."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CardToken:
    """An opaque card credential.

    It is passed to the payment gateway and nowhere else: it is never part of an order, an
    event or a log line. ``repr`` is masked so that an accidental ``%r`` or traceback does not
    leak it, and :meth:`reveal` makes every deliberate use easy to grep for.
    """

    _value: str = field(repr=False)

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "CardToken(***)"

    def __str__(self) -> str:
        return "***"
