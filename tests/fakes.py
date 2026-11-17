"""Hand-written fakes for the application ports."""

from __future__ import annotations

from datetime import datetime

from shop.application.checkout import CheckoutService
from shop.application.event_bus import EventBus
from shop.application.orders import OrderService
from shop.application.payment_methods import CardPayment, CashOnDelivery, Invoice, PaymentMethod
from shop.domain.errors import PaymentGatewayUnavailableError
from shop.domain.events import OrderPlaced
from shop.domain.money import Money
from shop.domain.payment import CardToken
from shop.domain.pricing.calculator import PricingCalculator
from shop.domain.pricing.registry import CUSTOMER_DISCOUNTS, PROMOTIONS, SHIPPING_METHODS
from shop.infrastructure.repositories import InMemoryOrderRepository
from tests.factories import NOW


class FakeClock:
    def __init__(self, moment: datetime = NOW) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


class FakePaymentGateway:
    """Approves by default; can be told to decline or to be unreachable."""

    def __init__(self) -> None:
        self.approve = True
        self.unavailable = False
        self.charges: list[tuple[Money, CardToken]] = []

    def charge(self, amount: Money, card: CardToken) -> bool:
        self.charges.append((amount, card))
        if self.unavailable:
            raise PaymentGatewayUnavailableError
        return self.approve


class RecordingNotifier:
    def __init__(self) -> None:
        self.received: list[OrderPlaced] = []

    def notify(self, event: OrderPlaced) -> None:
        self.received.append(event)


class World:
    """A fully wired application over fakes, the way a test wants to look at it."""

    def __init__(self) -> None:
        self.gateway = FakePaymentGateway()
        self.repository = InMemoryOrderRepository()
        self.events = EventBus()
        self.clock = FakeClock()
        self.notifier = RecordingNotifier()
        self.events.subscribe(OrderPlaced, self.notifier.notify)

        methods: dict[str, PaymentMethod] = {
            "card": CardPayment(self.gateway),
            "cod": CashOnDelivery(limit=Money.from_uah(5000)),
            "invoice": Invoice(),
        }
        self.checkout = CheckoutService(
            pricing=PricingCalculator(PROMOTIONS, CUSTOMER_DISCOUNTS, SHIPPING_METHODS),
            payment_methods=methods,
            orders=self.repository,
            events=self.events,
            clock=self.clock,
        )
        self.orders = OrderService(orders=self.repository, events=self.events, clock=self.clock)
