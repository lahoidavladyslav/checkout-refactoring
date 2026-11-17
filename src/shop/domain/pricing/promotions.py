"""Promo code strategies.

A promotion looks at the cart and answers with a :class:`PromoEffect`. It knows nothing about
the other promotions, customer discounts or shipping: how the effects are combined and in
which order is decided by :class:`~shop.domain.pricing.calculator.PricingCalculator`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from shop.domain.cart import Cart
from shop.domain.money import Money


@dataclass(frozen=True, slots=True)
class PromoEffect:
    """What a promo code does to an order."""

    discount: Money = Money.ZERO
    free_shipping: bool = False


NO_EFFECT = PromoEffect()


class Promotion(Protocol):
    """A promo code rule.

    ``Protocol`` rather than an abstract base class: strategies are tiny, stateless-ish value
    objects and do not need a shared implementation, so structural typing gives the same static
    safety without forcing an inheritance hierarchy on every new rule.
    """

    def evaluate(self, cart: Cart) -> PromoEffect: ...


@dataclass(frozen=True, slots=True)
class PercentageOff:
    """Take a percentage off the cart subtotal."""

    percent: Decimal

    def evaluate(self, cart: Cart) -> PromoEffect:
        subtotal = cart.subtotal
        remaining = subtotal.scale(1 - self.percent / 100)
        return PromoEffect(discount=subtotal - remaining)


@dataclass(frozen=True, slots=True)
class FixedAmountOff:
    """Take a fixed amount off, but only when the subtotal is strictly above a threshold."""

    amount: Money
    subtotal_above: Money

    def evaluate(self, cart: Cart) -> PromoEffect:
        if cart.subtotal > self.subtotal_above:
            return PromoEffect(discount=self.amount)
        return NO_EFFECT


@dataclass(frozen=True, slots=True)
class FreeShipping:
    """Waive the shipping cost."""

    def evaluate(self, cart: Cart) -> PromoEffect:  # part of the interface
        return PromoEffect(free_shipping=True)
