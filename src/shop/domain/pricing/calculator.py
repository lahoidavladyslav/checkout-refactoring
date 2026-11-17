"""Order pricing.

The calculation order is a business contract inherited from the legacy checkout:

1. subtotal of the cart,
2. promo code,
3. customer segment discount,
4. shipping (which may depend on the total *after* 2 and 3, and may be waived by the promo).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from shop.domain.cart import Cart
from shop.domain.customer import CustomerType
from shop.domain.errors import UnsupportedDeliveryError
from shop.domain.money import Money
from shop.domain.pricing.customer_discounts import CustomerDiscount
from shop.domain.pricing.promotions import NO_EFFECT, Promotion
from shop.domain.pricing.shipping import ShippingMethod


@dataclass(frozen=True, slots=True)
class Quote:
    """The price of an order broken down by step."""

    subtotal: Money
    promo_discount: Money
    customer_discount: Money
    shipping: Money

    @property
    def goods_total(self) -> Money:
        return self.subtotal - self.promo_discount - self.customer_discount

    @property
    def total(self) -> Money:
        return self.goods_total + self.shipping


class PricingCalculator:
    """Combines the registered strategies into a :class:`Quote`.

    The three registries are plain mappings. Supporting a new promo code, customer segment or
    delivery method is a matter of adding an entry; this class does not change.
    """

    def __init__(
        self,
        promotions: Mapping[str, Promotion],
        customer_discounts: Mapping[CustomerType, CustomerDiscount],
        shipping_methods: Mapping[str, ShippingMethod],
    ) -> None:
        self._promotions = promotions
        self._customer_discounts = customer_discounts
        self._shipping_methods = shipping_methods

    def quote(
        self,
        cart: Cart,
        *,
        promo_code: str | None,
        customer_type: CustomerType,
        delivery: str | None,
        city: str | None,
    ) -> Quote:
        subtotal = cart.subtotal

        # An unknown or missing promo code is ignored, as it always was.
        promotion = self._promotions.get(promo_code) if promo_code else None
        effect = promotion.evaluate(cart) if promotion else NO_EFFECT
        after_promo = subtotal - effect.discount

        rule = self._customer_discounts.get(customer_type)
        after_customer = rule.apply(after_promo) if rule else after_promo

        shipping = (
            Money.ZERO if effect.free_shipping else self._shipping(delivery, after_customer, city)
        )

        return Quote(
            subtotal=subtotal,
            promo_discount=effect.discount,
            customer_discount=after_promo - after_customer,
            shipping=shipping,
        )

    def _shipping(self, delivery: str | None, goods_total: Money, city: str | None) -> Money:
        method = self._shipping_methods.get(delivery) if delivery else None
        if method is None:
            raise UnsupportedDeliveryError
        return method.cost(goods_total, city)
