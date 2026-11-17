from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any

import pytest

from shop.domain.errors import InvalidMoneyError
from shop.domain.money import Money


class TestConstruction:
    @pytest.mark.parametrize(
        ("amount", "kopiyky"),
        [
            ("0", 0),
            ("0.01", 1),
            ("1", 100),
            ("99.99", 9999),
            (Decimal("1000.50"), 100050),
            (25, 2500),
            ("5.0", 500),
        ],
    )
    def test_from_uah(self, amount: Any, kopiyky: int) -> None:
        assert Money.from_uah(amount) == Money(kopiyky)

    @pytest.mark.parametrize("amount", ["0.001", "99.999", Decimal("1.005")])
    def test_from_uah_rejects_fractions_of_a_kopiyk(self, amount: Any) -> None:
        with pytest.raises(InvalidMoneyError):
            Money.from_uah(amount)

    @pytest.mark.parametrize("amount", [1.5, None, True, [1], "abc", "NaN", "Infinity"])
    def test_from_uah_rejects_non_decimal_input(self, amount: Any) -> None:
        with pytest.raises(InvalidMoneyError):
            Money.from_uah(amount)

    @pytest.mark.parametrize("kopiyky", [-1, 1.5, "10", None, True])
    def test_constructor_rejects_invalid_kopiyky(self, kopiyky: Any) -> None:
        with pytest.raises(InvalidMoneyError):
            Money(kopiyky)

    def test_is_immutable(self) -> None:
        money = Money(100)

        with pytest.raises(FrozenInstanceError):
            money.kopiyky = 5  # type: ignore[misc]  # frozen dataclass, that is the point


class TestErrorMessages:
    """The messages are for humans, but they are what makes a rejected amount diagnosable."""

    def test_negative_amount(self) -> None:
        with pytest.raises(
            InvalidMoneyError, match=r"^amount must not be negative, got -5 kopiyky$"
        ):
            Money(-5)

    def test_non_integer_kopiyky(self) -> None:
        with pytest.raises(InvalidMoneyError, match=r"^amount in kopiyky must be an int, got 1.5$"):
            Money(1.5)  # type: ignore[arg-type]  # the invalid input is the point of the test

    def test_unsupported_type(self) -> None:
        with pytest.raises(InvalidMoneyError, match=r"^cannot build money from float$"):
            Money.from_uah(1.5)  # type: ignore[arg-type]  # floats are rejected on purpose

    def test_not_a_number(self) -> None:
        with pytest.raises(InvalidMoneyError, match=r"^not a number: 'abc'$"):
            Money.from_uah("abc")

    def test_not_finite(self) -> None:
        with pytest.raises(InvalidMoneyError, match=r"^not a finite number: 'Infinity'$"):
            Money.from_uah("Infinity")

    def test_fraction_of_a_kopiyk(self) -> None:
        with pytest.raises(InvalidMoneyError, match=r"^'99.999' has a fraction of a kopiyk$"):
            Money.from_uah("99.999")


class TestArithmetic:
    def test_addition_is_exact(self) -> None:
        """The classic float trap: 0.1 + 0.2."""
        assert Money.from_uah("0.10") + Money.from_uah("0.20") == Money.from_uah("0.30")

    def test_subtraction(self) -> None:
        assert Money.from_uah("10") - Money.from_uah("0.01") == Money.from_uah("9.99")

    def test_subtraction_cannot_go_negative(self) -> None:
        with pytest.raises(InvalidMoneyError):
            Money.from_uah("1") - Money.from_uah("1.01")

    def test_multiplication_by_quantity(self) -> None:
        assert Money.from_uah("33.33") * 3 == Money.from_uah("99.99")
        assert 3 * Money.from_uah("33.33") == Money.from_uah("99.99")

    def test_multiplication_by_zero(self) -> None:
        assert Money.from_uah("33.33") * 0 == Money.ZERO

    def test_multiplication_rejects_negative_quantity(self) -> None:
        with pytest.raises(InvalidMoneyError):
            Money.from_uah("1") * -1

    def test_multiplication_by_float_is_not_supported(self) -> None:
        with pytest.raises(TypeError):
            Money.from_uah("1") * 1.5  # type: ignore[operator]  # floats must not slip in

    def test_adding_a_bare_number_is_not_supported(self) -> None:
        with pytest.raises(TypeError):
            Money.from_uah("1") + 1  # type: ignore[operator]  # only Money adds to Money

    def test_sum(self) -> None:
        amounts = [Money.from_uah("0.10")] * 10

        assert Money.sum(amounts) == Money.from_uah("1.00")

    def test_sum_of_nothing_is_zero(self) -> None:
        assert Money.sum([]) == Money.ZERO


class TestRounding:
    """The rule is ROUND_HALF_UP, applied once to an exact decimal."""

    @pytest.mark.parametrize(
        ("amount", "factor", "expected"),
        [
            ("100.00", "0.95", "95.00"),
            ("99.99", "0.9", "89.99"),  # 89.991 -> 89.99
            ("0.05", "0.9", "0.05"),  # 4.5 kopiyky -> 5, half goes up
            ("0.01", "0.5", "0.01"),  # 0.5 kopiyk -> 1
            ("0.03", "0.5", "0.02"),  # 1.5 kopiyky -> 2
            ("0.02", "0.5", "0.01"),  # exact, no rounding
            ("10.10", "0.95", "9.60"),  # 959.5 kopiyky -> 960, float would give 9.59
            ("2.675", "1", None),  # not representable as Money in the first place
        ],
    )
    def test_scale(self, amount: str, factor: str, expected: str | None) -> None:
        if expected is None:
            with pytest.raises(InvalidMoneyError):
                Money.from_uah(amount)
            return

        assert Money.from_uah(amount).scale(Decimal(factor)) == Money.from_uah(expected)

    def test_half_up_differs_from_float_round(self) -> None:
        """``round(0.125, 2)`` is 0.12 (binary float plus banker's rounding), we want 0.13."""
        assert round(0.125, 2) == 0.12
        assert Money.from_uah("12.5").scale(Decimal("0.01")) == Money.from_uah("0.13")

    def test_percent(self) -> None:
        assert Money.from_uah("200").percent(Decimal(10)) == Money.from_uah("20")
        assert Money.from_uah("0.15").percent(Decimal(10)) == Money.from_uah("0.02")

    def test_chained_scaling_rounds_after_every_step(self) -> None:
        """Rounding is per operation: this is why the pricing order is part of the contract."""
        amount = Money.from_uah("0.55")

        stepwise = amount.scale(Decimal("0.9")).scale(Decimal("0.95"))
        at_once = amount.scale(Decimal("0.855"))

        assert stepwise == Money.from_uah("0.48")
        assert at_once == Money.from_uah("0.47")


class TestZero:
    def test_zero_is_zero(self) -> None:
        assert Money.ZERO.is_zero()
        assert Money(0).is_zero()

    def test_any_other_amount_is_not(self) -> None:
        assert not Money(1).is_zero()
        assert not Money.from_uah("100").is_zero()


class TestComparison:
    def test_ordering(self) -> None:
        assert Money.from_uah("1.00") < Money.from_uah("1.01")
        assert Money.from_uah("1000") > Money.from_uah("999.99")
        assert Money.from_uah("500") >= Money.from_uah("500.00")

    def test_equality_ignores_representation(self) -> None:
        assert Money.from_uah("5") == Money.from_uah("5.00") == Money(500)

    def test_is_hashable(self) -> None:
        assert len({Money(100), Money.from_uah("1.00")}) == 1


class TestPresentation:
    @pytest.mark.parametrize(
        ("kopiyky", "text"),
        [(0, "0.00"), (1, "0.01"), (10, "0.10"), (14500, "145.00"), (1000001, "10000.01")],
    )
    def test_str(self, kopiyky: int, text: str) -> None:
        assert str(Money(kopiyky)) == text

    def test_to_uah(self) -> None:
        assert Money(14550).to_uah() == Decimal("145.50")

    def test_repr(self) -> None:
        assert repr(Money(9999)) == "Money(99.99)"
