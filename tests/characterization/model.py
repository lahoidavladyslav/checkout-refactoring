"""Implementation-independent description of what a checkout run looks like from outside.

The legacy function and the new service are both reduced to an :class:`Observed` value:
the result, the stored order and every outbound HTTP call. The characterization suite
compares those values, so it pins behaviour and not structure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

PAYMENTS_URL = "https://payments.example.com/charge"
MAIL_URL = "https://mail.example.com/send"
SLACK_URL = "https://slack.example.com/hook"

SERVICE_BY_URL = {PAYMENTS_URL: "payments", MAIL_URL: "mail", SLACK_URL: "slack"}

_CENT = Decimal("0.01")


def money(value: float | int | Decimal) -> str:
    """Render an amount with two decimals, rounding half up.

    ``repr`` is used for floats on purpose: it yields the shortest string that round-trips,
    so the tails produced by binary arithmetic (``89.991``) are rounded as a human would.
    """
    exact = value if isinstance(value, Decimal) else Decimal(repr(value))
    return str(exact.quantize(_CENT, rounding=ROUND_HALF_UP))


def normalize(body: Any) -> Any:
    """Normalise a JSON body so that equal amounts compare equal regardless of their type."""
    if isinstance(body, bool) or body is None or isinstance(body, str):
        return body
    if isinstance(body, int | float | Decimal):
        return money(body)
    if isinstance(body, dict):
        return {key: normalize(value) for key, value in body.items()}
    if isinstance(body, list):
        return [normalize(value) for value in body]
    raise TypeError(f"unsupported JSON value: {body!r}")


@dataclass(frozen=True)
class Call:
    """An outbound HTTP call made while checking out."""

    service: str
    body: str

    @classmethod
    def of(cls, service: str, body: dict[str, Any]) -> Call:
        return cls(service, json.dumps(normalize(body), sort_keys=True))


@dataclass(frozen=True)
class Observed:
    """Everything a caller or an external system can notice about one checkout."""

    ok: bool
    msg: str | None = None
    order_id: int | None = None
    total: str | None = None
    status: str | None = None
    calls: tuple[Call, ...] = ()


class Runner(Protocol):
    """Runs checkouts against one implementation."""

    name: str

    def checkout(self, payload: dict[str, Any], *, gateway_status: str = "ok") -> Observed: ...


def failure(msg: str, *calls: Call) -> Observed:
    return Observed(ok=False, msg=msg, calls=calls)


def success(
    total: str,
    *calls: Call,
    status: str = "new",
    order_id: int = 1,
) -> Observed:
    return Observed(ok=True, order_id=order_id, total=total, status=status, calls=calls)


def charge(amount: str, card: str | None = "tok_visa") -> Call:
    return Call.of("payments", {"amount": amount, "card": card})


def mail(email: str, template: str, total: str) -> Call:
    return Call.of("mail", {"to": email, "template": template, "total": total})


def slack(order_id: int = 1) -> Call:
    return Call.of("slack", {"text": f"Big order {order_id}"})
