from __future__ import annotations

import io
import json
import logging
import re
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from shop.observability import JsonFormatter, correlation_id
from tests.integration.conftest import Outbound
from tests.integration.test_api import checkout_body


@pytest.fixture
def log_lines() -> Iterator[Callable[[], list[dict[str, Any]]]]:
    """Returns a function that parses everything logged so far as JSON lines."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield lambda: [json.loads(line) for line in stream.getvalue().splitlines()]
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


def test_every_response_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/health")

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


def test_a_client_supplied_id_is_reused(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "trace-42.a_b"})

    assert response.headers["x-request-id"] == "trace-42.a_b"


@pytest.mark.parametrize("supplied", ["x" * 65, "bad id", "line\\nbreak", "<script>"])
def test_an_unsafe_client_id_is_replaced(client: TestClient, supplied: str) -> None:
    response = client.get("/health", headers={"X-Request-ID": supplied})

    assert response.headers["x-request-id"] != supplied
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


def test_ids_differ_between_requests(client: TestClient) -> None:
    first = client.get("/health").headers["x-request-id"]
    second = client.get("/health").headers["x-request-id"]

    assert first != second


def test_the_id_does_not_leak_out_of_the_request(client: TestClient) -> None:
    client.get("/health")

    assert correlation_id.get() is None


def test_an_access_line_is_logged_without_the_query_string(
    client: TestClient, log_lines: Callable[[], list[dict[str, Any]]]
) -> None:
    client.get("/health?email=buyer@example.com", headers={"X-Request-ID": "abc"})

    access = [line for line in log_lines() if line["logger"] == "shop.access"]
    assert access[0]["message"] == "GET /health -> 200"
    assert access[0]["correlation_id"] == "abc"
    assert access[0]["duration_ms"] >= 0
    assert "buyer" not in json.dumps(access)


def test_a_failure_deep_in_the_request_is_logged_with_its_correlation_id(
    client: TestClient, outbound: Outbound, log_lines: Callable[[], list[dict[str, Any]]]
) -> None:
    outbound.mail_status = 500

    client.post("/checkout", json=checkout_body(), headers={"X-Request-ID": "order-77"})

    errors = [line for line in log_lines() if line["level"] == "ERROR"]
    assert len(errors) == 1
    assert errors[0]["correlation_id"] == "order-77"
    assert "EmailNotifier.notify" in errors[0]["message"]


def test_no_email_reaches_the_logs(
    client: TestClient, outbound: Outbound, log_lines: Callable[[], list[dict[str, Any]]]
) -> None:
    outbound.mail_status = 500

    client.post("/checkout", json=checkout_body(email="buyer@example.com"))

    assert "buyer@example.com" not in json.dumps(log_lines())
