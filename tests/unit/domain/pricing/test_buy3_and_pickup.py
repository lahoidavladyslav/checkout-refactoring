"""The BUY3 promo code and the pickup delivery method.

They were added after the refactoring to check that the design is open for extension: the
production change is one new module (``cheapest_free``) and two registry lines.
"""

from __future__ import annotations

import pytest

from shop.domain.cart import Cart, OrderLine
from shop.domain.customer import CustomerType
from shop.domain.money import Money
from shop.domain.pricing.calculator import PricingCalculator
from shop.domain.pricing.cheapest_free import CheapestUnitFree
from shop.domain.pricing.registry import CUSTOMER_DISCOUNTS, PROMOTIONS, SHIPPING_METHODS
from tests.factories import line


def uah(value: str) -> Money:
    return Money.from_uah(value)


@pytest.fixture
def calculator() -> PricingCalculator:
    return PricingCalculator(PROMOTIONS, CUSTOMER_DISCOUNTS, SHIPPING_METHODS)


def price(
    calculator: PricingCalculator,
    lines: list[OrderLine],
    *,
    promo: str | None = "BUY3",
    delivery: str = "pickup",
    customer: CustomerType = CustomerType.REGULAR,
) -> Money:
    return calculator.quote(
        Cart.of(lines), promo_code=promo, customer_type=customer, delivery=delivery, city=None
    ).total


class TestBuy3:
    @pytest.mark.parametrize(
        ("lines", "expected"),
        [
            # one line, three units: one of them is free
            ([line("100", 3)], "200"),
            # the cheapest unit across different lines
            ([line("100"), line("50"), line("80")], "180"),
            # two lines, quantities add up to three
            ([line("100", 2), line("30", 1)], "200"),
            # more than three units still give exactly one free unit
            ([line("10", 5)], "40"),
            # the cheapest unit may sit on a line with a quantity above one
            ([line("100"), line("20", 2)], "120"),
        ],
    )
    def test_cheapest_unit_is_free(
        self, calculator: PricingCalculator, lines: list[OrderLine], expected: str
    ) -> None:
        assert price(calculator, lines) == uah(expected)

    @pytest.mark.parametrize("lines", [[line("100", 2)], [line("100"), line("50")], [line("100")]])
    def test_fewer_than_three_units_get_nothing(
        self, calculator: PricingCalculator, lines: list[OrderLine]
    ) -> None:
        total = Money.sum(entry.total for entry in lines)

        assert price(calculator, lines) == total

    def test_it_works_with_the_customer_discount_and_shipping(
        self, calculator: PricingCalculator
    ) -> None:
        lines = [line("100", 3)]

        total = price(calculator, lines, customer=CustomerType.VIP, delivery="ukr")

        assert total == uah("190") + uah("45")  # 200 * 0.95 = 190

    def test_threshold_is_a_parameter(self) -> None:
        rule = CheapestUnitFree(min_units=2)

        assert rule.evaluate(Cart.of([line("100", 2)])).discount == uah("100")


class TestPickup:
    def test_pickup_is_free(self, calculator: PricingCalculator) -> None:
        assert price(calculator, [line("100")], promo=None) == uah("100")

    def test_pickup_is_free_regardless_of_the_total(self, calculator: PricingCalculator) -> None:
        assert price(calculator, [line("5")], promo=None) == uah("5")
