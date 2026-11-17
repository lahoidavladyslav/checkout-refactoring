"""Domain error hierarchy.

Every error carries a stable machine-readable ``code``. Callers branch on the type (or the code),
never on the message, which is meant for humans and may change.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all errors raised by business rules."""

    code: str = "domain_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.__class__.__doc__ or self.code)

    @property
    def message(self) -> str:
        return str(self)


class InvalidMoneyError(DomainError):
    """The amount is not a valid sum of money."""

    code = "invalid_money"


class CheckoutError(DomainError):
    """A checkout request was rejected."""

    code = "checkout_error"


class NoItemsError(CheckoutError):
    """The order has no items."""

    code = "no_items"


class InvalidEmailError(CheckoutError):
    """The customer email is missing or malformed."""

    code = "bad_email"


class InvalidQuantityError(CheckoutError):
    """An item quantity must be a positive integer."""

    code = "bad_qty"


class UnsupportedDeliveryError(CheckoutError):
    """The delivery method is not supported."""

    code = "bad_delivery"


class PaymentDeclinedError(CheckoutError):
    """The payment provider declined the charge."""

    code = "payment_failed"


class CashOnDeliveryLimitError(CheckoutError):
    """The order total exceeds the cash on delivery limit."""

    code = "cod_limit"


class InvoiceNotAllowedError(CheckoutError):
    """Payment by invoice is available to business customers only."""

    code = "invoice_b2b_only"


class CardRequiredError(CheckoutError):
    """Paying by card requires card details."""

    code = "card_required"


class PaymentGatewayUnavailableError(CheckoutError):
    """The payment provider could not be reached or answered with garbage."""

    code = "payment_unavailable"


class OrderError(DomainError):
    """An operation on an existing order was rejected."""

    code = "order_error"


class InvalidTransitionError(OrderError):
    """The order cannot move to the requested status from its current one."""

    code = "invalid_transition"


class OrderNotFoundError(OrderError):
    """There is no order with the given id."""

    code = "order_not_found"
