"""Notification adapters: email and Slack over HTTP."""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from shop.domain.customer import CustomerType
from shop.domain.events import OrderPlaced
from shop.domain.money import Money


class EmailNotifier:
    """Sends the order confirmation, with a template chosen by the customer segment."""

    def __init__(
        self,
        client: httpx.Client,
        url: str,
        *,
        templates: Mapping[CustomerType, str],
        default_template: str,
        timeout: float = 5.0,
    ) -> None:
        self._client = client
        self._url = url
        self._templates = templates
        self._default_template = default_template
        self._timeout = timeout

    def notify(self, event: OrderPlaced) -> None:
        template = self._templates.get(event.customer_type, self._default_template)
        response = self._client.post(
            self._url,
            json={"to": event.email, "template": template, "total": float(event.total.to_uah())},
            timeout=self._timeout,
        )
        response.raise_for_status()


class SlackBigOrderNotifier:
    """Posts to a Slack hook when an order is strictly above a threshold."""

    def __init__(
        self,
        client: httpx.Client,
        url: str,
        *,
        threshold: Money,
        timeout: float = 5.0,
    ) -> None:
        self._client = client
        self._url = url
        self._threshold = threshold
        self._timeout = timeout

    def notify(self, event: OrderPlaced) -> None:
        if event.total <= self._threshold:
            return
        response = self._client.post(
            self._url, json={"text": f"Big order {event.order_id}"}, timeout=self._timeout
        )
        response.raise_for_status()
