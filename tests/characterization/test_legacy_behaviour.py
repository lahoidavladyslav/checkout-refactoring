"""Characterization of the legacy implementation.

These tests pin down what ``legacy.checkout`` does today, including behaviour that is
plainly a defect. They are the safety net for the refactoring: the same table of cases is
replayed against the new implementation in ``test_golden_master.py``.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from tests.characterization.cases import ALL_CASES, EMAIL, Case, request
from tests.characterization.runners import LegacyRunner

pytestmark = pytest.mark.characterization


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda case: case.id)
def test_legacy_matches_the_case_table(case: Case, legacy_runner: LegacyRunner) -> None:
    observed = legacy_runner.checkout(case.payload, gateway_status=case.gateway_status)

    assert observed == case.expected


def test_case_ids_are_unique() -> None:
    ids = [case.id for case in ALL_CASES]

    assert len(ids) == len(set(ids))


def test_order_ids_are_sequential_and_failures_do_not_consume_them(
    legacy_runner: LegacyRunner,
) -> None:
    first = legacy_runner.checkout(request(100))
    rejected = legacy_runner.checkout(request((100, 0)))
    second = legacy_runner.checkout(request(100))

    assert (first.order_id, rejected.order_id, second.order_id) == (1, None, 2)


def test_declined_payment_does_not_consume_an_order_id(legacy_runner: LegacyRunner) -> None:
    legacy_runner.checkout(request(100, payment="card", card="tok"), gateway_status="declined")

    second = legacy_runner.checkout(request(100))

    assert second.order_id == 1


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
