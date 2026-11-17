from __future__ import annotations

from decimal import Decimal

import pytest

from shop.domain.cart import Cart
from shop.domain.customer import CustomerType
from shop.domain.errors import UnsupportedDeliveryError
from shop.domain.money import Money
from shop.domain.pricing.calculator import PricingCalculator, Quote
from shop.domain.pricing.customer_discounts import PercentageDiscount
from shop.domain.pricing.promotions import PercentageOff, PromoEffect
from shop.domain.pricing.registry import CUSTOMER_DISCOUNTS, PROMOTIONS, SHIPPING_METHODS
from shop.domain.pricing.shipping import FlatRate
from tests.factories import line


@pytest.fixture
def calculator() -> PricingCalculator:
    return PricingCalculator(PROMOTIONS, CUSTOMER_DISCOUNTS, SHIPPING_METHODS)


def quote(
    calculator: PricingCalculator,
    *prices: str,
    promo: str | None = None,
    customer: CustomerType = CustomerType.REGULAR,
    delivery: str | None = "ukr",
    city: str | None = None,
) -> Quote:
    cart = Cart.of([line(price) for price in prices])
    return calculator.quote(
        cart, promo_code=promo, customer_type=customer, delivery=delivery, city=city
    )


def uah(value: str) -> Money:
    return Money.from_uah(value)


class TestPricingOrder:
    def test_breakdown_without_discounts(self, calculator: PricingCalculator) -> None:
        result = quote(calculator, "100")

        assert result == Quote(
            subtotal=uah("100"),
            promo_discount=Money.ZERO,
            customer_discount=Money.ZERO,
            shipping=uah("45"),
        )
        assert result.total == uah("145")

    def test_customer_discount_is_applied_after_the_promo(
        self, calculator: PricingCalculator
    ) -> None:
        result = quote(calculator, "1000", promo="SALE10", customer=CustomerType.VIP)

        assert result.promo_discount == uah("100")
        assert result.customer_discount == uah("45")  # 5% of 900, not of 1000
        assert result.total == uah("900")

    def test_shipping_threshold_looks_at_the_discounted_total(
        self, calculator: PricingCalculator
    ) -> None:
        result = quote(calculator, "1100", promo="SALE10", delivery="nova")

        assert result.shipping == uah("70")
        assert result.total == uah("1060")

    def test_free_shipping_promo_skips_the_delivery_lookup(
        self, calculator: PricingCalculator
    ) -> None:
        result = quote(calculator, "100", promo="FREESHIP", delivery="teleport")

        assert result.shipping == Money.ZERO
        assert result.total == uah("100")

    def test_free_shipping_promo_does_not_need_a_delivery_at_all(
        self, calculator: PricingCalculator
    ) -> None:
        assert quote(calculator, "100", promo="FREESHIP", delivery=None).total == uah("100")

    @pytest.mark.parametrize("promo", [None, "", "WAT", "sale10"])
    def test_unknown_promo_is_ignored(
        self, calculator: PricingCalculator, promo: str | None
    ) -> None:
        assert quote(calculator, "100", promo=promo).total == uah("145")

    @pytest.mark.parametrize("delivery", [None, "", "dhl", "NOVA"])
    def test_unknown_delivery_is_rejected(
        self, calculator: PricingCalculator, delivery: str | None
    ) -> None:
        with pytest.raises(UnsupportedDeliveryError):
            quote(calculator, "100", delivery=delivery)

    def test_a_float_tail_is_rounded_to_a_whole_kopiyk(self, calculator: PricingCalculator) -> None:
        """Legacy: 99.99 with SALE10 is 89.991 (+ 45 shipping). Here: 89.99, exact."""
        result = quote(calculator, "99.99", promo="SALE10")

        assert result.total == uah("134.99")


class TestOpenForExtension:
    """New rules plug in through the registries; the calculator is not touched."""

    def test_a_new_promotion_is_just_a_registry_entry(self) -> None:
        calculator = PricingCalculator(
            promotions={**PROMOTIONS, "HALF": PercentageOff(Decimal(50))},
            customer_discounts=CUSTOMER_DISCOUNTS,
            shipping_methods=SHIPPING_METHODS,
        )

        assert quote(calculator, "100", promo="HALF").total == uah("95")

    def test_a_new_promotion_may_be_any_object_with_evaluate(self) -> None:
        class Everything:
            def evaluate(self, cart: Cart) -> PromoEffect:
                return PromoEffect(discount=cart.subtotal, free_shipping=True)

        calculator = PricingCalculator({"FREE": Everything()}, {}, {})

        assert quote(calculator, "100", promo="FREE", delivery=None).total == Money.ZERO

    def test_a_new_shipping_method_is_just_a_registry_entry(self) -> None:
        calculator = PricingCalculator(
            promotions={},
            customer_discounts={},
            shipping_methods={"drone": FlatRate(uah("300"))},
        )

        assert quote(calculator, "100", delivery="drone").total == uah("400")

    def test_a_new_customer_segment_is_just_a_registry_entry(self) -> None:
        calculator = PricingCalculator(
            promotions={},
            customer_discounts={CustomerType.B2B: PercentageDiscount(Decimal(20))},
            shipping_methods=SHIPPING_METHODS,
        )

        assert quote(calculator, "100", customer=CustomerType.B2B).total == uah("125")
