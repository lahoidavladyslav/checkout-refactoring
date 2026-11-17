from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from shop.api.app import create_app
from shop.composition import Settings, build_container
from tests.fakes import FakeClock


@dataclass
class Outbound:
    """The external world as seen by the application: scripted answers and recorded calls."""

    payment_response: httpx.Response = field(
        default_factory=lambda: httpx.Response(200, json={"status": "ok"})
    )
    mail_status: int = 200
    requests: list[httpx.Request] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith("https://payments."):
            return self.payment_response
        if url.startswith("https://mail."):
            return httpx.Response(self.mail_status)
        return httpx.Response(200)

    def bodies(self, host: str) -> list[dict[str, Any]]:
        return [
            json.loads(request.content)
            for request in self.requests
            if request.url.host.startswith(host)
        ]


@pytest.fixture
def outbound() -> Outbound:
    return Outbound()


@pytest.fixture
def client(outbound: Outbound) -> Iterator[TestClient]:
    http = httpx.Client(transport=httpx.MockTransport(outbound.handle))
    container = build_container(Settings(), http_client=http, clock=FakeClock())
    app = create_app(checkout=container.checkout, orders=container.orders, on_shutdown=http.close)
    with TestClient(app) as test_client:
        yield test_client
