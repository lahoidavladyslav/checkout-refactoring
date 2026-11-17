from __future__ import annotations

import threading

import pytest

from shop.domain.errors import PaymentGatewayUnavailableError
from shop.domain.money import Money
from shop.domain.payment import CardToken
from shop.infrastructure.circuit_breaker import CircuitBreakerGateway, CircuitOpenError, State
from tests.fakes import FakePaymentGateway

AMOUNT = Money.from_uah("10")
CARD = CardToken("tok")


class Time:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def time() -> Time:
    return Time()


@pytest.fixture
def inner() -> FakePaymentGateway:
    return FakePaymentGateway()


@pytest.fixture
def breaker(inner: FakePaymentGateway, time: Time) -> CircuitBreakerGateway:
    return CircuitBreakerGateway(inner, failure_threshold=3, reset_after=30, clock=time)


def fail(breaker: CircuitBreakerGateway, times: int) -> None:
    for _ in range(times):
        with pytest.raises(PaymentGatewayUnavailableError):
            breaker.charge(AMOUNT, CARD)


def test_passes_calls_through_while_healthy(
    breaker: CircuitBreakerGateway, inner: FakePaymentGateway
) -> None:
    assert breaker.charge(AMOUNT, CARD) is True
    assert breaker.state is State.CLOSED
    assert len(inner.charges) == 1


def test_a_decline_is_not_a_failure(
    breaker: CircuitBreakerGateway, inner: FakePaymentGateway
) -> None:
    inner.approve = False

    for _ in range(10):
        assert breaker.charge(AMOUNT, CARD) is False

    assert breaker.state is State.CLOSED


def test_opens_after_consecutive_outages(
    breaker: CircuitBreakerGateway, inner: FakePaymentGateway
) -> None:
    inner.unavailable = True

    fail(breaker, 3)

    assert breaker.state is State.OPEN


def test_an_open_circuit_fails_fast_without_calling_the_provider(
    breaker: CircuitBreakerGateway, inner: FakePaymentGateway
) -> None:
    inner.unavailable = True
    fail(breaker, 3)
    calls = len(inner.charges)

    with pytest.raises(CircuitOpenError):
        breaker.charge(AMOUNT, CARD)

    assert len(inner.charges) == calls


def test_the_open_error_is_still_a_payment_outage() -> None:
    assert issubclass(CircuitOpenError, PaymentGatewayUnavailableError)


def test_a_success_resets_the_failure_count(
    breaker: CircuitBreakerGateway, inner: FakePaymentGateway
) -> None:
    inner.unavailable = True
    fail(breaker, 2)
    inner.unavailable = False
    breaker.charge(AMOUNT, CARD)
    inner.unavailable = True

    fail(breaker, 2)

    assert breaker.state is State.CLOSED


def test_a_probe_after_the_reset_time_closes_the_circuit_on_success(
    breaker: CircuitBreakerGateway, inner: FakePaymentGateway, time: Time
) -> None:
    inner.unavailable = True
    fail(breaker, 3)
    inner.unavailable = False
    time.now += 30

    assert breaker.charge(AMOUNT, CARD) is True
    assert breaker.state is State.CLOSED


def test_a_failed_probe_reopens_the_circuit_for_another_full_period(
    breaker: CircuitBreakerGateway, inner: FakePaymentGateway, time: Time
) -> None:
    inner.unavailable = True
    fail(breaker, 3)
    time.now += 30

    fail(breaker, 1)
    time.now += 29

    assert breaker.state is State.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.charge(AMOUNT, CARD)


def test_not_yet_time_for_a_probe(
    breaker: CircuitBreakerGateway, inner: FakePaymentGateway, time: Time
) -> None:
    inner.unavailable = True
    fail(breaker, 3)
    time.now += 29.9

    with pytest.raises(CircuitOpenError):
        breaker.charge(AMOUNT, CARD)


def test_only_one_probe_is_allowed_while_half_open(time: Time) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    class Slow:
        outage = True

        def charge(self, amount: Money, card: CardToken) -> bool:
            calls.append(1)
            if self.outage:
                raise PaymentGatewayUnavailableError
            entered.set()
            release.wait(timeout=5)
            return True

    slow = Slow()
    breaker = CircuitBreakerGateway(slow, failure_threshold=1, reset_after=30, clock=time)
    fail(breaker, 1)
    slow.outage = False
    time.now += 30
    probe = threading.Thread(target=lambda: breaker.charge(AMOUNT, CARD))
    probe.start()
    assert entered.wait(timeout=5)

    with pytest.raises(CircuitOpenError):
        breaker.charge(AMOUNT, CARD)

    release.set()
    probe.join(timeout=5)
    assert breaker.state is State.CLOSED
    assert len(calls) == 2


def test_the_threshold_must_be_positive(inner: FakePaymentGateway) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        CircuitBreakerGateway(inner, failure_threshold=0)
