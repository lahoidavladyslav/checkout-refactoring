"""Defects of the legacy implementation, pinned down as executable documentation.

``test_golden_master.py`` replays the case table against both implementations. The tests here
cover what that table cannot express: behaviour the refactoring deliberately changes.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from tests.characterization.cases import EMAIL, request
from tests.characterization.runners import LegacyRunner

pytestmark = pytest.mark.characterization


class TestKnownDefects:
    """Defects that the refactoring deliberately fixes. See docs/CODE_REVIEW.md."""

    def test_c1_float_tail_is_stored_in_the_order(self, legacy_runner: LegacyRunner) -> None:
        result = legacy_runner.module.checkout(request(99.99, promo="SALE10", delivery="ukr"))

        assert result["order"]["total"] != round(result["order"]["total"], 2)

    def test_s1_client_can_waive_shipping_without_a_promo(
        self, legacy_runner: LegacyRunner
    ) -> None:
        payload = request(100, delivery="courier", city="Lviv", free_ship=True)

        result = legacy_runner.module.checkout(payload)

        assert result["order"]["total"] == 100

    def test_s2_input_dictionary_is_mutated(self, legacy_runner: LegacyRunner) -> None:
        payload = request(100, promo="FREESHIP")

        legacy_runner.module.checkout(payload)

        assert payload["free_ship"] is True

    def test_c5_negative_price_reduces_the_total(self, legacy_runner: LegacyRunner) -> None:
        result = legacy_runner.module.checkout(request(100, -30, delivery="ukr"))

        assert result["order"]["total"] == 115

    def test_c6_change_status_accepts_any_value(self, legacy_runner: LegacyRunner) -> None:
        legacy_runner.module.checkout(request(100))

        assert legacy_runner.module.change_status(1, "delivered") is True
        assert legacy_runner.module.change_status(1, "new") is True
        assert legacy_runner.module.change_status(1, "banana") is True
        assert legacy_runner.module.orders[0]["status"] == "banana"

    def test_c10_timestamp_is_naive(self, legacy_runner: LegacyRunner) -> None:
        result = legacy_runner.module.checkout(request(100))

        created = result["order"]["created"]
        assert isinstance(created, datetime)
        assert created.tzinfo is None

    def test_s3_email_and_items_are_written_to_a_plain_text_log(
        self, legacy_runner: LegacyRunner, tmp_path: Path
    ) -> None:
        legacy_runner.module.checkout(request(100))

        line = json.loads((tmp_path / "orders.log").read_text().splitlines()[0])
        assert line["email"] == EMAIL
        assert line["items"] == [{"price": 100, "qty": 1}]
