"""Composition root: the one place where concrete classes are chosen and wired together."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from shop.application.checkout import CheckoutService
from shop.application.event_bus import EventBus
from shop.application.handlers import log_refund_request
from shop.application.orders import OrderService
from shop.application.payment_methods import CardPayment, CashOnDelivery, Invoice, PaymentMethod
from shop.application.ports import Clock, OrderRepository
from shop.domain.customer import CustomerType
from shop.domain.events import OrderPlaced, RefundRequested
from shop.domain.money import Money
from shop.domain.pricing.calculator import PricingCalculator
from shop.domain.pricing.registry import CUSTOMER_DISCOUNTS, PROMOTIONS, SHIPPING_METHODS
from shop.infrastructure.circuit_breaker import CircuitBreakerGateway
from shop.infrastructure.clock import SystemClock
from shop.infrastructure.notifiers import EmailNotifier, SlackBigOrderNotifier
from shop.infrastructure.payments import HttpPaymentGateway
from shop.infrastructure.repositories import InMemoryOrderRepository

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

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        return cls(
            payments_url=os.environ.get("SHOP_PAYMENTS_URL", defaults.payments_url),
            mail_url=os.environ.get("SHOP_MAIL_URL", defaults.mail_url),
            slack_url=os.environ.get("SHOP_SLACK_URL", defaults.slack_url),
            http_timeout=float(os.environ.get("SHOP_HTTP_TIMEOUT", defaults.http_timeout)),
            payment_timeout=float(os.environ.get("SHOP_PAYMENT_TIMEOUT", defaults.payment_timeout)),
        )


@dataclass(frozen=True, slots=True)
class Container:
    checkout: CheckoutService
    orders: OrderService
    events: EventBus


def build_container(
    settings: Settings,
    *,
    http_client: httpx.Client,
    repository: OrderRepository | None = None,
    clock: Clock | None = None,
) -> Container:
    repository = repository or InMemoryOrderRepository()
    clock = clock or SystemClock()

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

    events = EventBus()
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
    events.subscribe(OrderPlaced, email.notify)
    events.subscribe(OrderPlaced, slack.notify)
    events.subscribe(RefundRequested, log_refund_request)

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
    )
