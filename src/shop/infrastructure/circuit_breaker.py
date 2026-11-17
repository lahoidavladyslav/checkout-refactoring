"""Circuit breaker for the payment gateway."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from enum import StrEnum

from shop.application.ports import PaymentGateway
from shop.domain.errors import PaymentGatewayUnavailableError
from shop.domain.money import Money
from shop.domain.payment import CardToken


class CircuitOpenError(PaymentGatewayUnavailableError):
    """The payment provider is failing, calls are rejected without being attempted."""


class State(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerGateway:
    """Wraps a :class:`PaymentGateway` and stops calling it while it keeps failing.

    - ``CLOSED``: calls pass through. ``failure_threshold`` consecutive outages open the
      circuit.
    - ``OPEN``: calls fail at once with :class:`CircuitOpenError`, without touching the network
      and without waiting for a timeout. After ``reset_after`` seconds one call is let through.
    - ``HALF_OPEN``: that single probe decides. Success closes the circuit, an outage re-opens
      it. Other callers keep failing fast while the probe is in flight.

    Only ``PaymentGatewayUnavailableError`` counts as a failure. A decline means the provider
    answered, so it counts as a success for the breaker. The lock protects the state, never the
    remote call.
    """

    def __init__(
        self,
        inner: PaymentGateway,
        *,
        failure_threshold: int = 5,
        reset_after: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        self._inner = inner
        self._threshold = failure_threshold
        self._reset_after = reset_after
        self._clock = clock
        self._lock = threading.Lock()
        self._state = State.CLOSED
        self._failures = 0
        self._opened_at = 0.0

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    def charge(self, amount: Money, card: CardToken) -> bool:
        self._admit()
        try:
            approved = self._inner.charge(amount, card)
        except PaymentGatewayUnavailableError:
            self._record_failure()
            raise
        self._record_success()
        return approved

    def _admit(self) -> None:
        with self._lock:
            if self._state is State.CLOSED:
                return
            if self._state is State.OPEN and self._clock() - self._opened_at >= self._reset_after:
                self._state = State.HALF_OPEN
                return
            raise CircuitOpenError("payment provider is temporarily unavailable")

    def _record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state is State.HALF_OPEN or self._failures >= self._threshold:
                self._state = State.OPEN
                self._opened_at = self._clock()

    def _record_success(self) -> None:
        with self._lock:
            self._state = State.CLOSED
            self._failures = 0
