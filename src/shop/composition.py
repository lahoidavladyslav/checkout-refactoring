"""Composition root: the one place where concrete classes are chosen and wired together.

Two modes, chosen by ``Settings.database_url``:

- **in-memory** (default): orders live in process memory and events are delivered synchronously,
  in-process, right after the order is stored. Good for development and tests.
- **PostgreSQL**: orders and their events are written in one transaction (a transactional outbox);
  a separate worker process (``python -m shop.worker``) delivers the events with retries.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta

import httpx

from shop.application.checkout import CheckoutService
from shop.application.event_bus import EventBus
from shop.application.handlers import log_refund_request
from shop.application.orders import OrderService
from shop.application.outbox import OutboxRelay, RetryPolicy, Subscription
from shop.application.payment_methods import CardPayment, CashOnDelivery, Invoice, PaymentMethod
from shop.application.ports import Clock, OrderRepository
from shop.domain.customer import CustomerType
from shop.domain.events import DomainEvent, OrderPlaced, RefundRequested
from shop.domain.money import Money
from shop.domain.pricing.calculator import PricingCalculator
from shop.domain.pricing.registry import CUSTOMER_DISCOUNTS, PROMOTIONS, SHIPPING_METHODS
from shop.infrastructure.circuit_breaker import CircuitBreakerGateway
from shop.infrastructure.clock import SystemClock
from shop.infrastructure.notifiers import EmailNotifier, SlackBigOrderNotifier
from shop.infrastructure.payments import HttpPaymentGateway
from shop.infrastructure.repositories import InMemoryOrderRepository
from shop.infrastructure.sql.engine import create_db_engine
from shop.infrastructure.sql.outbox import SqlOutboxStore
from shop.infrastructure.sql.repository import SqlOrderRepository

COD_LIMIT = Money.from_uah(5000)
BIG_ORDER_THRESHOLD = Money.from_uah(10000)


@dataclass(frozen=True, slots=True)
class Settings:
    payments_url: str = "https://payments.example.com/charge"
    mail_url: str = "https://mail.example.com/send"
    slack_url: str = "https://slack.example.com/hook"
    http_timeout: float = 5.0
    payment_timeout: float = 10.0
    payment_breaker_threshold: int = 5
    payment_breaker_reset_seconds: float = 30.0
    cod_limit: Money = COD_LIMIT
    big_order_threshold: Money = BIG_ORDER_THRESHOLD
    database_url: str | None = None
    outbox_max_attempts: int = 6
    outbox_base_delay_seconds: float = 10.0
    outbox_poll_seconds: float = 2.0

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        d = cls()
        return cls(
            payments_url=env.get("SHOP_PAYMENTS_URL", d.payments_url),
            mail_url=env.get("SHOP_MAIL_URL", d.mail_url),
            slack_url=env.get("SHOP_SLACK_URL", d.slack_url),
            http_timeout=float(env.get("SHOP_HTTP_TIMEOUT", d.http_timeout)),
            payment_timeout=float(env.get("SHOP_PAYMENT_TIMEOUT", d.payment_timeout)),
            payment_breaker_threshold=int(
                env.get("SHOP_PAYMENT_BREAKER_THRESHOLD", d.payment_breaker_threshold)
            ),
            payment_breaker_reset_seconds=float(
                env.get("SHOP_PAYMENT_BREAKER_RESET", d.payment_breaker_reset_seconds)
            ),
            database_url=env.get("SHOP_DATABASE_URL") or None,
            outbox_max_attempts=int(env.get("SHOP_OUTBOX_MAX_ATTEMPTS", d.outbox_max_attempts)),
            outbox_base_delay_seconds=float(
                env.get("SHOP_OUTBOX_BASE_DELAY", d.outbox_base_delay_seconds)
            ),
            outbox_poll_seconds=float(env.get("SHOP_OUTBOX_POLL", d.outbox_poll_seconds)),
        )


@dataclass(frozen=True, slots=True)
class Container:
    checkout: CheckoutService
    orders: OrderService
    events: EventBus
    relay: OutboxRelay | None = field(default=None)


def _subscriptions(
    settings: Settings, http_client: httpx.Client
) -> Mapping[type[DomainEvent], Sequence[Subscription]]:
    """Who is told about what. The order matters: email goes out before the Slack alert."""
    email = EmailNotifier(
        http_client,
        settings.mail_url,
        templates={CustomerType.VIP: "vip_order"},
        default_template="order",
        timeout=settings.http_timeout,
    )
    slack = SlackBigOrderNotifier(
        http_client,
        settings.slack_url,
        threshold=settings.big_order_threshold,
        timeout=settings.http_timeout,
    )
    return {
        OrderPlaced: [Subscription("email", email.notify), Subscription("slack", slack.notify)],
        RefundRequested: [Subscription("refund_log", log_refund_request)],
    }


def build_container(
    settings: Settings,
    *,
    http_client: httpx.Client,
    repository: OrderRepository | None = None,
    clock: Clock | None = None,
) -> Container:
    clock = clock or SystemClock()
    subscriptions = _subscriptions(settings, http_client)
    events = EventBus()
    relay: OutboxRelay | None = None

    if repository is None and settings.database_url:
        engine = create_db_engine(settings.database_url)
        repository = SqlOrderRepository(engine, record_events=True)
        # The services publish to a bus nobody listens to: the events are already in the outbox,
        # and the relay delivers them, so nothing is delivered twice.
        relay = OutboxRelay(
            store=SqlOutboxStore(engine),
            subscriptions=subscriptions,
            clock=clock,
            policy=RetryPolicy(
                max_attempts=settings.outbox_max_attempts,
                base_delay=timedelta(seconds=settings.outbox_base_delay_seconds),
            ),
        )
    else:
        repository = repository or InMemoryOrderRepository()
        for event_type, subs in subscriptions.items():
            for subscription in subs:
                events.subscribe(event_type, subscription.handler)

    gateway = CircuitBreakerGateway(
        HttpPaymentGateway(http_client, settings.payments_url, timeout=settings.payment_timeout),
        failure_threshold=settings.payment_breaker_threshold,
        reset_after=settings.payment_breaker_reset_seconds,
    )
    payment_methods: dict[str, PaymentMethod] = {
        "card": CardPayment(gateway),
        "cod": CashOnDelivery(limit=settings.cod_limit),
        "invoice": Invoice(),
    }
    pricing = PricingCalculator(PROMOTIONS, CUSTOMER_DISCOUNTS, SHIPPING_METHODS)
    return Container(
        checkout=CheckoutService(
            pricing=pricing,
            payment_methods=payment_methods,
            orders=repository,
            events=events,
            clock=clock,
        ),
        orders=OrderService(orders=repository, events=events, clock=clock),
        events=events,
        relay=relay,
    )
