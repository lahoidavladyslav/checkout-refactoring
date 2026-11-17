from __future__ import annotations

from decimal import Decimal

import pytest

from shop.domain.cart import Cart
from shop.domain.money import Money
from shop.domain.pricing.customer_discounts import PercentageDiscount
from shop.domain.pricing.promotions import (
    NO_EFFECT,
    FixedAmountOff,
    FreeShipping,
    PercentageOff,
    PromoEffect,
)
from shop.domain.pricing.registry import PROMOTIONS, SHIPPING_METHODS
from tests.factories import line


def uah(value: str) -> Money:
    return Money.from_uah(value)


class TestPromotions:
    @pytest.mark.parametrize(
        ("subtotal", "discount"),
        [("1000", "100"), ("99.99", "10.00"), ("0.05", "0.00")],
    )
    def test_percentage_off(self, subtotal: str, discount: str) -> None:
        effect = PercentageOff(Decimal(10)).evaluate(Cart.of([line(subtotal)]))

        assert effect == PromoEffect(discount=uah(discount))

    @pytest.mark.parametrize(
        ("subtotal", "discount"),
        [("500", "0"), ("500.01", "50"), ("501", "50"), ("100", "0")],
    )
    def test_fixed_amount_applies_strictly_above_the_threshold(
        self, subtotal: str, discount: str
    ) -> None:
        rule = FixedAmountOff(amount=uah("50"), subtotal_above=uah("500"))

        assert rule.evaluate(Cart.of([line(subtotal)])).discount == uah(discount)

    def test_fixed_amount_without_effect_is_the_neutral_effect(self) -> None:
        rule = FixedAmountOff(amount=uah("50"), subtotal_above=uah("500"))

        assert rule.evaluate(Cart.of([line("10")])) == NO_EFFECT

    def test_free_shipping_grants_no_discount(self) -> None:
        effect = FreeShipping().evaluate(Cart.of([line("10")]))

        assert effect == PromoEffect(free_shipping=True)

    def test_registered_codes(self) -> None:
        assert set(PROMOTIONS) == {"SALE10", "MINUS50", "FREESHIP"}


class TestCustomerDiscount:
    @pytest.mark.parametrize(
        ("total", "expected"),
        [("200", "190.00"), ("522.50", "496.38"), ("0.10", "0.10"), ("0.30", "0.29")],
    )
    def test_percentage_discount(self, total: str, expected: str) -> None:
        assert PercentageDiscount(Decimal(5)).apply(uah(total)) == uah(expected)


class TestShipping:
    @pytest.mark.parametrize(
        ("method", "total", "city", "cost"),
        [
            ("nova", "100", None, "70"),
            ("nova", "1000", None, "70"),
            ("nova", "1000.01", None, "0"),
            ("nova", "5000", "Lviv", "0"),
            ("ukr", "1", None, "45"),
            ("ukr", "99999", "Kyiv", "45"),
            ("courier", "100", "Kyiv", "120"),
            ("courier", "100", "Lviv", "170"),
            ("courier", "100", None, "170"),
            ("courier", "100", "kyiv", "170"),
        ],
    )
    def test_cost(self, method: str, total: str, city: str | None, cost: str) -> None:
        assert SHIPPING_METHODS[method].cost(uah(total), city) == uah(cost)

    def test_registered_methods(self) -> None:
        assert set(SHIPPING_METHODS) == {"nova", "ukr", "courier"}
