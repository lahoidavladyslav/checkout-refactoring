"""The default registries: which promo codes, customer segments and delivery methods exist.

This is the one place that has to change when a new rule is introduced.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from shop.domain.customer import CustomerType
from shop.domain.money import Money
from shop.domain.pricing.cheapest_free import CheapestUnitFree
from shop.domain.pricing.customer_discounts import CustomerDiscount, PercentageDiscount
from shop.domain.pricing.promotions import FixedAmountOff, FreeShipping, PercentageOff, Promotion
from shop.domain.pricing.shipping import (
    FlatRate,
    FreeAboveThreshold,
    LocalOrRemoteRate,
    ShippingMethod,
)

PROMOTIONS: Mapping[str, Promotion] = {
    "SALE10": PercentageOff(Decimal(10)),
    "MINUS50": FixedAmountOff(amount=Money.from_uah(50), subtotal_above=Money.from_uah(500)),
    "FREESHIP": FreeShipping(),
    "BUY3": CheapestUnitFree(min_units=3),
}

CUSTOMER_DISCOUNTS: Mapping[CustomerType, CustomerDiscount] = {
    CustomerType.VIP: PercentageDiscount(Decimal(5)),
}

SHIPPING_METHODS: Mapping[str, ShippingMethod] = {
    "nova": FreeAboveThreshold(threshold=Money.from_uah(1000), price=Money.from_uah(70)),
    "ukr": FlatRate(Money.from_uah(45)),
    "courier": LocalOrRemoteRate(
        home_city="Kyiv",
        local_price=Money.from_uah(120),
        remote_price=Money.from_uah(170),
    ),
    "pickup": FlatRate(Money.ZERO),
}
