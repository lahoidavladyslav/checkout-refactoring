from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from shop.application.handlers import log_refund_request
from shop.composition import Settings
from shop.domain.events import RefundRequested
from shop.domain.money import Money
from shop.infrastructure.clock import SystemClock
from shop.main import build_app
from tests.factories import NOW


def test_settings_have_safe_defaults() -> None:
    settings = Settings()

    assert settings.cod_limit == Money.from_uah(5000)
    assert settings.big_order_threshold == Money.from_uah(10000)
    assert settings.payment_timeout > 0
    assert settings.http_timeout > 0


def test_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOP_PAYMENTS_URL", "https://pay.test/charge")
    monkeypatch.setenv("SHOP_HTTP_TIMEOUT", "2.5")

    settings = Settings.from_env()

    assert settings.payments_url == "https://pay.test/charge"
    assert settings.http_timeout == 2.5
    assert settings.mail_url == Settings().mail_url


def test_the_production_app_starts_and_serves() -> None:
    with TestClient(build_app()) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_the_production_app_rejects_a_bad_request_without_any_network() -> None:
    with TestClient(build_app()) as client:
        response = client.post("/checkout", json={"items": [], "email": "buyer@example.com"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_items"


def test_the_system_clock_is_timezone_aware_and_current() -> None:
    now = SystemClock().now()

    assert now.tzinfo is not None
    assert abs(now - NOW) > timedelta(days=1)  # sanity: it is not a frozen value


def test_refund_requests_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    event = RefundRequested(occurred_at=NOW, order_id=7, amount=Money.from_uah("145"))

    with caplog.at_level(logging.INFO):
        log_refund_request(event)

    assert "refund of 145.00 requested for order 7" in caplog.text
