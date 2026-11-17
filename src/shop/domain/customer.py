"""Customer-related value objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from shop.domain.errors import InvalidEmailError


class CustomerType(StrEnum):
    REGULAR = "regular"
    VIP = "vip"
    B2B = "b2b"

    @classmethod
    def parse(cls, value: str | None) -> CustomerType:
        """Lenient parsing: anything unknown is a regular customer.

        The legacy checkout treats an unrecognised ``user_type`` as no special treatment at
        all, and clients rely on it. Strictness here would be a behaviour change.
        """
        try:
            return cls(value) if value else cls.REGULAR
        except ValueError:
            return cls.REGULAR


@dataclass(frozen=True, slots=True)
class EmailAddress:
    """A customer email.

    The validation is intentionally as loose as the legacy rule (it must contain ``@``):
    the real proof of an address is the delivery of a message, not a regular expression.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or "@" not in self.value:
            raise InvalidEmailError

    def __str__(self) -> str:
        return self.value
