from __future__ import annotations

import pytest

from shop.domain.errors import (
    CashOnDeliveryLimitError,
    DomainError,
    InvalidTransitionError,
    NoItemsError,
    PaymentDeclinedError,
)


class TestMessages:
    def test_an_error_without_a_message_describes_itself(self) -> None:
        assert NoItemsError().message == "The order has no items."

    def test_an_explicit_message_wins(self) -> None:
        assert InvalidTransitionError("order 7 is final").message == "order 7 is final"

    def test_the_code_is_the_fallback_when_there_is_no_docstring(self) -> None:
        class BareError(DomainError):
            code = "bare"

        BareError.__doc__ = None

        assert BareError().message == "bare"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (NoItemsError, "no_items"),
        (PaymentDeclinedError, "payment_failed"),
        (CashOnDeliveryLimitError, "cod_limit"),
        (InvalidTransitionError, "invalid_transition"),
    ],
)
def test_codes_are_stable(error: type[DomainError], code: str) -> None:
    assert error.code == code
