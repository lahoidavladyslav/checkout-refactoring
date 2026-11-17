"""Adapters that run one checkout against a concrete implementation."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import legacy.checkout as legacy_checkout
import pytest
import responses
import time_machine

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
