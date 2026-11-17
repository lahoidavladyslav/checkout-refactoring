from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from shop.domain.errors import PaymentGatewayUnavailableError
from shop.domain.money import Money
from shop.domain.payment import CardToken
from shop.infrastructure.payments import HttpPaymentGateway

URL = "https://payments.example.com/charge"
CARD = CardToken("4111111111111111")
AMOUNT = Money.from_uah("145.50")


def gateway(handler: Callable[[httpx.Request], httpx.Response]) -> HttpPaymentGateway:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpPaymentGateway(client, URL, timeout=3.0)


def test_approved() -> None:
    assert gateway(lambda _: httpx.Response(200, json={"status": "ok"})).charge(AMOUNT, CARD)


@pytest.mark.parametrize("status", ["declined", "error", "", None, 1])
def test_anything_but_ok_is_a_decline(status: object) -> None:
    result = gateway(lambda _: httpx.Response(200, json={"status": status})).charge(AMOUNT, CARD)

    assert result is False


def test_a_json_decline_with_an_error_status_code_is_still_a_decline() -> None:
    declined = gateway(lambda _: httpx.Response(402, json={"status": "declined"}))

    assert declined.charge(AMOUNT, CARD) is False


def test_request_carries_the_amount_in_hryvnias_and_the_card() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "ok"})

    gateway(handler).charge(AMOUNT, CARD)

    assert str(seen[0].url) == URL
    assert json.loads(seen[0].content) == {"amount": 145.5, "card": "4111111111111111"}


def test_a_timeout_is_set_on_every_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "ok"})

    gateway(handler).charge(AMOUNT, CARD)

    assert seen[0].extensions["timeout"]["read"] == 3.0


@pytest.mark.parametrize("code", [500, 502, 503])
def test_server_errors_mean_unavailable(code: int) -> None:
    with pytest.raises(PaymentGatewayUnavailableError):
        gateway(lambda _: httpx.Response(code, text="<html>bad gateway</html>")).charge(
            AMOUNT, CARD
        )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>maintenance</html>"),
        httpx.Response(200, json={"state": "ok"}),
        httpx.Response(200, json=["ok"]),
        httpx.Response(200, text=""),
    ],
)
def test_an_unreadable_answer_means_unavailable(response: httpx.Response) -> None:
    with pytest.raises(PaymentGatewayUnavailableError):
        gateway(lambda _: response).charge(AMOUNT, CARD)


def test_a_network_failure_means_unavailable_and_does_not_leak_the_card() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(PaymentGatewayUnavailableError) as raised:
        gateway(handler).charge(AMOUNT, CARD)

    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert "4111" not in str(raised.value)
