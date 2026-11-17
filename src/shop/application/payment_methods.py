"""Payment method strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from shop.application.ports import PaymentGateway
from shop.domain.customer import CustomerType
from shop.domain.errors import (
    CardRequiredError,
    CashOnDeliveryLimitError,
    InvoiceNotAllowedError,
    PaymentDeclinedError,
)
from shop.domain.money import Money
from shop.domain.payment import CardToken


@dataclass(frozen=True, slots=True)
class PaymentContext:
    total: Money
    customer_type: CustomerType
    card: CardToken | None


class PaymentMethod(Protocol):
    def settle(self, context: PaymentContext) -> bool:
        """Perform whatever the method requires at checkout.

        Returns ``True`` when the money has been collected, ``False`` when payment is deferred
        (cash on delivery, invoice). Raises a ``CheckoutError`` when the order must be refused.
        """
        ...


@dataclass(frozen=True, slots=True)
class CardPayment:
    gateway: PaymentGateway

    def settle(self, context: PaymentContext) -> bool:
        if context.card is None:
            raise CardRequiredError
        if not self.gateway.charge(context.total, context.card):
            raise PaymentDeclinedError
        return True


@dataclass(frozen=True, slots=True)
class CashOnDelivery:
    limit: Money

    def settle(self, context: PaymentContext) -> bool:
        if context.total > self.limit:
            raise CashOnDeliveryLimitError
        return False


@dataclass(frozen=True, slots=True)
class Invoice:
    def settle(self, context: PaymentContext) -> bool:
        if context.customer_type is not CustomerType.B2B:
            raise InvoiceNotAllowedError
        return False


@dataclass(frozen=True, slots=True)
class Deferred:
    """No checks, nothing collected.

    This is what the legacy checkout effectively did for an unrecognised payment method. It is
    kept only until the dedicated fix commit replaces it with a rejection.
    """

    def settle(self, context: PaymentContext) -> bool:
        return False
