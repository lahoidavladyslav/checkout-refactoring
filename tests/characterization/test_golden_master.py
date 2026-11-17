"""Golden master: the new implementation must behave exactly like the legacy one.

Each test runs twice, once per implementation (see the ``runner`` fixture). A failure in the
``legacy`` variant means the case table is wrong; a failure in the ``new`` variant means the
refactoring changed behaviour.
"""

from __future__ import annotations

import pytest

from tests.characterization.cases import ALL_CASES, Case, request
from tests.characterization.model import Runner

pytestmark = pytest.mark.characterization


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda case: case.id)
def test_case(case: Case, runner: Runner) -> None:
    observed = runner.checkout(case.payload, gateway_status=case.gateway_status)

    assert observed == case.expected


def test_case_ids_are_unique() -> None:
    ids = [case.id for case in ALL_CASES]

    assert len(ids) == len(set(ids))


def test_order_ids_are_sequential_and_rejections_do_not_consume_them(runner: Runner) -> None:
    first = runner.checkout(request(100))
    rejected = runner.checkout(request((100, 0)))
    second = runner.checkout(request(100))

    assert (first.order_id, rejected.order_id, second.order_id) == (1, None, 2)


def test_declined_payment_does_not_consume_an_order_id(runner: Runner) -> None:
    runner.checkout(request(100, payment="card", card="tok"), gateway_status="declined")

    second = runner.checkout(request(100))

    assert second.order_id == 1
