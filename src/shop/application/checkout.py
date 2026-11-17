"""The checkout use case."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from shop.application.event_bus import EventBus
from shop.application.payment_methods import Deferred, PaymentContext, PaymentMethod
from shop.application.ports import Clock, OrderRepository
from shop.domain.cart import Cart, OrderLine
from shop.domain.customer import CustomerType, EmailAddress
from shop.domain.errors import NoItemsError
from shop.domain.order import Order
from shop.domain.payment import CardToken
from shop.domain.pricing.calculator import PricingCalculator


@dataclass(frozen=True, slots=True)
class CheckoutCommand:
    """A request to place an order, already parsed into domain types by the caller."""

    lines: tuple[OrderLine, ...]
    email: str
    promo_code: str | None = None
    customer_type: str | None = None
    delivery: str | None = None
    city: str | None = None
    payment: str | None = None
    card: CardToken | None = None


class CheckoutService:
    def __init__(
        self,
        *,
        pricing: PricingCalculator,
        payment_methods: Mapping[str, PaymentMethod],
        orders: OrderRepository,
        events: EventBus,
        clock: Clock,
    ) -> None:
        self._pricing = pricing
        self._payment_methods = payment_methods
        self._orders = orders
        self._events = events
        self._clock = clock

    def place_order(self, command: CheckoutCommand) -> Order:
        # The order of the checks is observable (a request with two problems reports the first
        # one) and is the one the legacy checkout had: items, email, quantities.
        if not command.lines:
            raise NoItemsError
        email = EmailAddress(command.email)
        cart = Cart.of(command.lines)

        customer_type = CustomerType.parse(command.customer_type)
        quote = self._pricing.quote(
            cart,
            promo_code=command.promo_code,
            customer_type=customer_type,
            delivery=command.delivery,
            city=command.city,
        )

        method = self._payment_methods.get(command.payment or "", Deferred())
        paid = method.settle(
            PaymentContext(total=quote.total, customer_type=customer_type, card=command.card)
        )

        order = Order.place(
            id=self._orders.next_id(),
            email=email,
            lines=cart.lines,
            total=quote.total,
            customer_type=customer_type,
            created_at=self._clock.now(),
        )
        if paid:
            order.pay()
        self._orders.add(order)

        self._events.publish(order.pull_events())
        return order
