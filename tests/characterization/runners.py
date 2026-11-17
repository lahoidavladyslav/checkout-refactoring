"""Adapters that run one checkout against a concrete implementation."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import legacy.checkout as legacy_checkout
import pytest
import responses
import time_machine

from shop.application.checkout import CheckoutCommand
from shop.composition import Settings, build_container
from shop.domain.cart import OrderLine
from shop.domain.errors import CheckoutError
from shop.domain.money import Money
from shop.domain.payment import CardToken
from tests.characterization.model import (
    MAIL_URL,
    PAYMENTS_URL,
    SERVICE_BY_URL,
    SLACK_URL,
    Call,
    Observed,
    money,
)

FROZEN_NOW = "2025-03-14 12:00:00"


class LegacyRunner:
    """Drives ``legacy.checkout`` with all of its side effects intercepted."""

    name = "legacy"

    def __init__(self, module: Any, mock: responses.RequestsMock) -> None:
        self.module = module
        self._mock = mock
        self._gateway_status = "ok"
        for url in (MAIL_URL, SLACK_URL):
            mock.post(url, json={"queued": True})
        mock.add_callback(
            responses.POST,
            PAYMENTS_URL,
            callback=self._payment_response,
            content_type="application/json",
        )

    def _payment_response(self, _request: Any) -> tuple[int, dict[str, str], str]:
        return 200, {}, json.dumps({"status": self._gateway_status})

    def checkout(self, payload: dict[str, Any], *, gateway_status: str = "ok") -> Observed:
        self._gateway_status = gateway_status
        calls_before = len(self._mock.calls)
        result = self.module.checkout(copy.deepcopy(payload))
        calls = tuple(self._recorded_calls(calls_before))
        if not result["ok"]:
            return Observed(ok=False, msg=result["msg"], calls=calls)
        order = result["order"]
        return Observed(
            ok=True,
            order_id=order["id"],
            total=money(order["total"]),
            status=order["status"],
            calls=calls,
        )

    def _recorded_calls(self, start: int) -> list[Call]:
        recorded = []
        for call in self._mock.calls[start:]:
            body = json.loads(call.request.body)
            recorded.append(Call.of(SERVICE_BY_URL[call.request.url], body))
        return recorded


@pytest.fixture
def legacy_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """The legacy module with its global state reset and its log file in a temp dir."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(legacy_checkout, "orders", [])
    monkeypatch.setattr(legacy_checkout, "last_id", 0)
    return legacy_checkout


@pytest.fixture
def legacy_runner(legacy_module: Any) -> Any:
    with (
        time_machine.travel(FROZEN_NOW, tick=False),
        responses.RequestsMock(assert_all_requests_are_fired=False) as mock,
    ):
        yield LegacyRunner(legacy_module, mock)


# Legacy answers with a message; the new implementation with an error code. This is the only
# translation between the two worlds, and it is one-to-one.
LEGACY_MESSAGE_BY_CODE = {
    "no_items": "no items",
    "bad_email": "bad email",
    "bad_qty": "bad qty",
    "bad_delivery": "bad delivery",
    "payment_failed": "payment failed",
    "cod_limit": "cod limit",
    "invoice_b2b_only": "invoice only b2b",
    # No legacy counterpart: the legacy checkout accepted any payment method. Used only by
    # the intentional divergences in cases.py.
    "unsupported_payment": "unsupported payment",
}


class NewRunner:
    """Drives the new ``CheckoutService`` wired like production, over a fake HTTP transport."""

    name = "new"

    def __init__(self) -> None:
        self._gateway_status = "ok"
        self._recorded: list[Call] = []
        client = httpx.Client(transport=httpx.MockTransport(self._handle))
        self._container = build_container(
            Settings(),
            http_client=client,
            clock=FixedClock(datetime(2025, 3, 14, 12, 0, tzinfo=UTC)),
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        service = SERVICE_BY_URL[str(request.url)]
        self._recorded.append(Call.of(service, json.loads(request.content)))
        if service == "payments":
            return httpx.Response(200, json={"status": self._gateway_status})
        return httpx.Response(200, json={"queued": True})

    def checkout(self, payload: dict[str, Any], *, gateway_status: str = "ok") -> Observed:
        self._gateway_status = gateway_status
        start = len(self._recorded)
        try:
            order = self._container.checkout.place_order(self._command(payload))
        except CheckoutError as error:
            return Observed(
                ok=False,
                msg=LEGACY_MESSAGE_BY_CODE[error.code],
                calls=tuple(self._recorded[start:]),
            )
        return Observed(
            ok=True,
            order_id=order.id,
            total=str(order.total),
            status=order.status.value,
            calls=tuple(self._recorded[start:]),
        )

    @staticmethod
    def _command(payload: dict[str, Any]) -> CheckoutCommand:
        lines = tuple(
            OrderLine(
                unit_price=Money.from_uah(Decimal(repr(item["price"]))),
                quantity=item["qty"],
            )
            for item in payload.get("items", [])
        )
        card = payload.get("card")
        return CheckoutCommand(
            lines=lines,
            email=payload.get("email") or "",
            promo_code=payload.get("promo"),
            customer_type=payload.get("user_type"),
            delivery=payload.get("delivery"),
            city=payload.get("city"),
            payment=payload.get("payment"),
            card=CardToken(card) if card is not None else None,
        )


class FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


@pytest.fixture
def new_runner() -> NewRunner:
    return NewRunner()
