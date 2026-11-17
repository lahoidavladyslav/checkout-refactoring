"""The "buy N, the cheapest unit is free" promotion."""

from __future__ import annotations

from dataclasses import dataclass

from shop.domain.cart import Cart
from shop.domain.pricing.promotions import NO_EFFECT, PromoEffect


@dataclass(frozen=True, slots=True)
class CheapestUnitFree:
    """When at least ``min_units`` units are bought, the cheapest single unit costs nothing.

    Units are counted across all lines of the cart, so two lines of quantity 2 qualify.
    """

    min_units: int

    def evaluate(self, cart: Cart) -> PromoEffect:
        if cart.units < self.min_units:
            return NO_EFFECT
        return PromoEffect(discount=min(line.unit_price for line in cart.lines))
