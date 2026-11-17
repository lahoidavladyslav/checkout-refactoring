"""Payment provider adapter."""

from __future__ import annotations

import httpx

from shop.domain.errors import PaymentGatewayUnavailableError
from shop.domain.money import Money
from shop.domain.payment import CardToken


class HttpPaymentGateway:
    """Charges cards through the provider's HTTP API."""

    def __init__(self, client: httpx.Client, url: str, *, timeout: float = 10.0) -> None:
        self._client = client
        self._url = url
        self._timeout = timeout

    def charge(self, amount: Money, card: CardToken) -> bool:
        payload = {
            # The provider's contract is a JSON number in hryvnias. Money is exact; the float is
            # created here, at the very edge, from a value with at most two decimals.
            "amount": float(amount.to_uah()),
            "card": card.reveal(),
        }
        try:
            response = self._client.post(self._url, json=payload, timeout=self._timeout)
        except httpx.HTTPError:
            # Do not chain: the original error may echo the request, which carries the card.
            raise PaymentGatewayUnavailableError("payment provider is unreachable") from None
        if response.status_code >= 500:
            raise PaymentGatewayUnavailableError(
                f"payment provider answered {response.status_code}"
            )
        try:
            status = response.json()["status"]
        except (ValueError, KeyError, TypeError):
            raise PaymentGatewayUnavailableError(
                "payment provider sent an unreadable answer"
            ) from None
        return isinstance(status, str) and status == "ok"
