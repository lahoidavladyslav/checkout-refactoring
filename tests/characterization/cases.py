"""Golden-master cases.

Every case describes one checkout request and what the legacy implementation does with it.
The expected values were derived by hand from the legacy source and then confirmed by running
it; the same table is replayed against the new implementation.

Amounts that carry a binary-float tail in the legacy implementation (``89.991``) are expected
in their half-up rounded form: the tail itself is a bug (C1) that is covered separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tests.characterization.model import (
    Observed,
    charge,
    failure,
    mail,
    slack,
    success,
)

EMAIL = "buyer@example.com"


@dataclass(frozen=True)
class Case:
    id: str
    payload: dict[str, Any]
    expected: Observed
    gateway_status: str = "ok"
    tags: frozenset[str] = field(default_factory=frozenset)


def request(
    *prices: float | int | tuple[float | int, float | int],
    **fields: Any,
) -> dict[str, Any]:
    """Build a request payload.

    Each positional argument is either a unit price (quantity 1) or a ``(price, qty)`` pair.
    Delivery defaults to ``ukr`` and payment to ``cod``: the two cheapest paths without
    any outbound call besides the notification.
    """
    items = [
        {"price": p[0], "qty": p[1]} if isinstance(p, tuple) else {"price": p, "qty": 1}
        for p in prices
    ]
    payload: dict[str, Any] = {
        "items": items,
        "email": EMAIL,
        "delivery": "ukr",
        "payment": "cod",
    }
    payload.update(fields)
    return payload


def placed(
    total: str,
    *,
    template: str = "order",
    status: str = "new",
    big: bool = False,
    charged: bool = False,
    card: str = "tok_visa",
) -> Observed:
    """Expected outcome of a successful checkout and the calls that go with it."""
    calls = []
    if charged:
        calls.append(charge(total, card))
    calls.append(mail(EMAIL, template, total))
    if big:
        calls.append(slack())
    return success(total, *calls, status=status)


VALIDATION = [
    Case("no-items-key", {"email": EMAIL}, failure("no items")),
    Case("empty-items", request(email=EMAIL), failure("no items")),
    Case("missing-email", {"items": [{"price": 10, "qty": 1}]}, failure("bad email")),
    Case("empty-email", request(10, email=""), failure("bad email")),
    Case("email-without-at", request(10, email="buyer.example.com"), failure("bad email")),
    Case("zero-qty", request((10, 0)), failure("bad qty")),
    Case("negative-qty", request((10, -2)), failure("bad qty")),
    Case("bad-qty-in-second-item", request(10, (10, 0)), failure("bad qty")),
    Case("empty-items-reported-before-bad-email", {"items": [], "email": "x"}, failure("no items")),
    Case("bad-email-reported-before-bad-qty", request((10, 0), email="x"), failure("bad email")),
]

PROMOTIONS = [
    Case("no-promo-multiple-lines", request((100, 2), 50), placed("295.00")),
    Case("sale10", request(1000, promo="SALE10"), placed("945.00")),
    Case(
        "sale10-keeps-a-float-tail-rounded-half-up",
        request(99.99, promo="SALE10"),
        placed("134.99"),
    ),
    Case("minus50-not-applied-at-exactly-500", request(500, promo="MINUS50"), placed("545.00")),
    Case("minus50-applied-just-above-500", request(500.01, promo="MINUS50"), placed("495.01")),
    Case("minus50-applied", request(600, promo="MINUS50"), placed("595.00")),
    Case("freeship-waives-shipping", request(100, promo="FREESHIP"), placed("100.00")),
    Case(
        "freeship-waives-courier",
        request(100, promo="FREESHIP", delivery="courier"),
        placed("100.00"),
    ),
    Case(
        "freeship-skips-delivery-validation",
        request(100, promo="FREESHIP", delivery="teleport"),
        placed("100.00"),
        tags=frozenset({"quirk"}),
    ),
    Case(
        "freeship-without-delivery",
        {**request(100, promo="FREESHIP"), "delivery": None},
        placed("100.00"),
        tags=frozenset({"quirk"}),
    ),
    Case(
        "unknown-promo-is-ignored",
        request(100, promo="WAT"),
        placed("145.00"),
        tags=frozenset({"quirk"}),
    ),
    Case(
        "promo-codes-are-case-sensitive",
        request(100, promo="sale10"),
        placed("145.00"),
        tags=frozenset({"quirk"}),
    ),
]

CUSTOMERS = [
    Case("vip-discount", request(200, user_type="vip"), placed("235.00", template="vip_order")),
    Case(
        "vip-after-sale10",
        request(1000, promo="SALE10", user_type="vip"),
        placed("900.00", template="vip_order"),
    ),
    Case(
        "vip-after-minus50",
        request(600, promo="MINUS50", user_type="vip"),
        placed("567.50", template="vip_order"),
    ),
    Case(
        "vip-with-freeship",
        request(100, promo="FREESHIP", user_type="vip"),
        placed("95.00", template="vip_order"),
    ),
    Case("b2b-pays-regular-prices", request(100, user_type="b2b"), placed("145.00")),
    Case(
        "unknown-customer-type-is-regular",
        request(100, user_type="gold"),
        placed("145.00"),
        tags=frozenset({"quirk"}),
    ),
]

SHIPPING = [
    Case("nova-below-threshold", request(100, delivery="nova"), placed("170.00")),
    Case("nova-at-exactly-1000-is-not-free", request(1000, delivery="nova"), placed("1070.00")),
    Case("nova-free-just-above-1000", request(1000.01, delivery="nova"), placed("1000.01")),
    Case("nova-free-for-large-orders", request(2000, delivery="nova"), placed("2000.00")),
    Case(
        "nova-threshold-is-checked-after-promo",
        request(1100, delivery="nova", promo="SALE10"),
        placed("1060.00"),
        tags=frozenset({"quirk"}),
    ),
    Case(
        "nova-threshold-is-checked-after-vip",
        request(1050, delivery="nova", user_type="vip"),
        placed("1067.50", template="vip_order"),
        tags=frozenset({"quirk"}),
    ),
    Case("ukr-flat-rate", request(100, delivery="ukr"), placed("145.00")),
    Case("courier-in-kyiv", request(100, delivery="courier", city="Kyiv"), placed("220.00")),
    Case("courier-outside-kyiv", request(100, delivery="courier", city="Lviv"), placed("270.00")),
    Case(
        "courier-without-city",
        request(100, delivery="courier"),
        placed("270.00"),
        tags=frozenset({"quirk"}),
    ),
    Case(
        "courier-city-is-case-sensitive",
        request(100, delivery="courier", city="kyiv"),
        placed("270.00"),
        tags=frozenset({"quirk"}),
    ),
    Case("unknown-delivery", request(100, delivery="dhl"), failure("bad delivery")),
    Case("missing-delivery", {**request(100), "delivery": None}, failure("bad delivery")),
]

PAYMENTS = [
    Case(
        "card-is-charged-with-the-final-total",
        request(100, payment="card", card="tok_visa"),
        placed("145.00", status="paid", charged=True),
    ),
    Case(
        "card-charge-includes-discounts-and-shipping",
        request(1000, payment="card", card="tok_visa", promo="SALE10", delivery="nova"),
        placed("970.00", status="paid", charged=True),
    ),
    Case(
        "card-token-is-forwarded",
        request(100, payment="card", card="tok_other"),
        placed("145.00", status="paid", charged=True, card="tok_other"),
    ),
    Case(
        "card-declined",
        request(100, payment="card", card="tok_visa"),
        failure("payment failed", charge("145.00")),
        gateway_status="declined",
    ),
    Case(
        "card-error-status-is-a-decline",
        request(100, payment="card", card="tok_visa"),
        failure("payment failed", charge("145.00")),
        gateway_status="error",
    ),
    Case("cod-is-created-unpaid", request(100, payment="cod"), placed("145.00")),
    Case("cod-at-exactly-5000", request(4955, payment="cod"), placed("5000.00")),
    Case("cod-above-5000", request(4956, payment="cod"), failure("cod limit")),
    Case(
        "cod-limit-includes-shipping",
        request(4831, payment="cod", delivery="courier", city="Lviv"),
        failure("cod limit"),
    ),
    Case(
        "cod-limit-is-checked-after-promo",
        request(5500, payment="cod", promo="SALE10"),
        placed("4995.00"),
    ),
    Case("invoice-for-b2b", request(100, payment="invoice", user_type="b2b"), placed("145.00")),
    Case(
        "invoice-rejected-for-vip",
        request(100, payment="invoice", user_type="vip"),
        failure("invoice only b2b"),
    ),
    Case(
        "invoice-rejected-without-customer-type",
        request(100, payment="invoice"),
        failure("invoice only b2b"),
    ),
    Case(
        "unknown-payment-method-creates-an-unpaid-order",
        request(100, payment="crypto"),
        placed("145.00"),
        tags=frozenset({"defect"}),
    ),
    Case(
        "missing-payment-method-creates-an-unpaid-order",
        {**request(100), "payment": None},
        placed("145.00"),
        tags=frozenset({"defect"}),
    ),
]

NOTIFICATIONS = [
    Case("regular-customer-gets-the-order-template", request(100), placed("145.00")),
    Case(
        "slack-is-silent-at-exactly-10000",
        request(9955, payment="card", card="tok_visa"),
        placed("10000.00", status="paid", charged=True),
    ),
    Case(
        "slack-fires-above-10000",
        request(9956, payment="card", card="tok_visa"),
        placed("10001.00", status="paid", charged=True, big=True),
    ),
    Case(
        "slack-fires-for-card-orders",
        request(20000, payment="card", card="tok_visa"),
        placed("20045.00", status="paid", charged=True, big=True),
    ),
    Case(
        "slack-fires-for-invoices",
        request(20000, payment="invoice", user_type="b2b"),
        placed("20045.00", big=True),
    ),
    Case(
        "slack-uses-the-vip-total",
        request(10500, user_type="vip", payment="card", card="tok_visa"),
        placed("10020.00", template="vip_order", status="paid", charged=True, big=True),
    ),
]

ALL_CASES: list[Case] = [
    *VALIDATION,
    *PROMOTIONS,
    *CUSTOMERS,
    *SHIPPING,
    *PAYMENTS,
    *NOTIFICATIONS,
]
