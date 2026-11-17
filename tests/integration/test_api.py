from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import Outbound

ITEM = {"price": "100.00", "qty": 1}


def checkout_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "items": [ITEM],
        "email": "buyer@example.com",
        "delivery": "ukr",
        "payment": "cod",
    }
    body.update(overrides)
    return body


def error_code(response: httpx.Response) -> str:
    code: str = response.json()["error"]["code"]
    return code


class TestPlacingAnOrder:
    def test_creates_an_order(self, client: TestClient) -> None:
        response = client.post("/checkout", json=checkout_body())

        assert response.status_code == 201
        assert response.json() == {
            "id": 1,
            "email": "buyer@example.com",
            "items": [{"price": "100.00", "qty": 1, "title": None}],
            "total": "145.00",
            "status": "new",
            "created_at": "2025-03-14T12:00:00Z",
        }

    def test_card_order_is_paid_and_the_card_goes_only_to_the_provider(
        self, client: TestClient, outbound: Outbound
    ) -> None:
        response = client.post(
            "/checkout", json=checkout_body(payment="card", card="4111111111111111")
        )

        assert response.json()["status"] == "paid"
        assert outbound.bodies("payments") == [{"amount": 145.0, "card": "4111111111111111"}]
        assert "4111" not in response.text
        assert all("4111" not in str(body) for body in outbound.bodies("mail"))

    def test_notifications_are_sent(self, client: TestClient, outbound: Outbound) -> None:
        client.post("/checkout", json=checkout_body(user_type="vip"))

        assert outbound.bodies("mail") == [
            {"to": "buyer@example.com", "template": "vip_order", "total": 140.0}
        ]

    def test_a_broken_mail_service_does_not_fail_the_order(
        self, client: TestClient, outbound: Outbound, caplog: pytest.LogCaptureFixture
    ) -> None:
        outbound.mail_status = 500

        with caplog.at_level(logging.ERROR):
            response = client.post("/checkout", json=checkout_body())

        assert response.status_code == 201
        assert client.get("/orders/1").status_code == 200
        assert "EmailNotifier.notify" in caplog.text

    def test_a_client_cannot_grant_itself_free_shipping(self, client: TestClient) -> None:
        """S1: legacy honoured a client-supplied `free_ship` flag."""
        body = checkout_body(delivery="courier", city="Lviv", free_ship=True)

        response = client.post("/checkout", json=body)

        assert response.status_code == 201
        assert response.json()["total"] == "270.00"


class TestRejections:
    @pytest.mark.parametrize(
        ("overrides", "status", "code"),
        [
            ({"items": []}, 422, "no_items"),
            ({"email": "nope"}, 422, "bad_email"),
            ({"email": None}, 422, "bad_email"),
            ({"items": [{"price": "10", "qty": 0}]}, 422, "bad_qty"),
            ({"delivery": "dhl"}, 422, "bad_delivery"),
            ({"items": [{"price": "5000", "qty": 1}]}, 422, "cod_limit"),
            ({"payment": "invoice"}, 422, "invoice_b2b_only"),
            ({"payment": "card"}, 422, "card_required"),
            ({"payment": "crypto"}, 422, "unsupported_payment"),
            ({"payment": None}, 422, "unsupported_payment"),
        ],
    )
    def test_business_rules(
        self, client: TestClient, overrides: dict[str, Any], status: int, code: str
    ) -> None:
        response = client.post("/checkout", json=checkout_body(**overrides))

        assert response.status_code == status
        assert error_code(response) == code
        assert response.json()["error"]["message"]

    def test_declined_card(self, client: TestClient, outbound: Outbound) -> None:
        outbound.payment_response = httpx.Response(200, json={"status": "declined"})

        response = client.post("/checkout", json=checkout_body(payment="card", card="tok"))

        assert response.status_code == 402
        assert error_code(response) == "payment_failed"
        assert client.get("/orders/1").status_code == 404

    @pytest.mark.parametrize(
        "provider_answer",
        [httpx.Response(503, text="down"), httpx.Response(200, text="<html></html>")],
    )
    def test_payment_provider_trouble_is_a_bad_gateway(
        self, client: TestClient, outbound: Outbound, provider_answer: httpx.Response
    ) -> None:
        outbound.payment_response = provider_answer

        response = client.post("/checkout", json=checkout_body(payment="card", card="tok"))

        assert response.status_code == 502
        assert error_code(response) == "payment_unavailable"

    @pytest.mark.parametrize(
        "body",
        [
            checkout_body(items=[{"price": "10", "qty": 1.5}]),
            checkout_body(items=[{"price": "10", "qty": "2"}]),
            checkout_body(items=[{"price": "10", "qty": True}]),
            checkout_body(items=[{"price": "-1", "qty": 1}]),
            checkout_body(items=[{"price": "10.001", "qty": 1}]),
            checkout_body(items=[{"qty": 1}]),
            checkout_body(items=[{"price": "10"}]),
            checkout_body(items="many"),
        ],
    )
    def test_malformed_input_is_a_validation_error(
        self, client: TestClient, body: dict[str, Any]
    ) -> None:
        response = client.post("/checkout", json=body)

        assert response.status_code == 422
        assert error_code(response) == "validation_error"
        assert response.json()["error"]["details"]

    def test_validation_errors_do_not_echo_the_input(self, client: TestClient) -> None:
        response = client.post("/checkout", json=checkout_body(card=["4111111111111111"]))

        assert response.status_code == 422
        assert "4111" not in response.text


class TestOrderStatus:
    def place(self, client: TestClient, **overrides: Any) -> int:
        order: int = client.post("/checkout", json=checkout_body(**overrides)).json()["id"]
        return order

    def patch(self, client: TestClient, order_id: int, status: str) -> httpx.Response:
        return client.patch(f"/orders/{order_id}/status", json={"status": status})

    def test_lifecycle(self, client: TestClient) -> None:
        order_id = self.place(client)

        statuses = [self.patch(client, order_id, s).json()["status"] for s in ("paid", "shipped")]

        assert statuses == ["paid", "shipped"]
        assert client.get(f"/orders/{order_id}").json()["status"] == "shipped"

    def test_forbidden_transition_is_a_conflict(self, client: TestClient) -> None:
        order_id = self.place(client)

        response = self.patch(client, order_id, "delivered")

        assert response.status_code == 409
        assert error_code(response) == "invalid_transition"
        assert client.get(f"/orders/{order_id}").json()["status"] == "new"

    def test_nothing_goes_back_to_new(self, client: TestClient) -> None:
        order_id = self.place(client)
        self.patch(client, order_id, "paid")

        assert self.patch(client, order_id, "new").status_code == 409

    def test_unknown_status_is_a_validation_error(self, client: TestClient) -> None:
        order_id = self.place(client)

        response = self.patch(client, order_id, "banana")

        assert response.status_code == 422
        assert error_code(response) == "validation_error"

    def test_unknown_order(self, client: TestClient) -> None:
        response = self.patch(client, 99, "paid")

        assert response.status_code == 404
        assert error_code(response) == "order_not_found"


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_openapi_describes_the_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert set(paths) == {"/checkout", "/orders/{order_id}", "/orders/{order_id}/status", "/health"}
