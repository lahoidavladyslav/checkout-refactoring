"""Request and response models of the HTTP API.

Pydantic lives here and only here. Requests are validated for *shape* (types, ranges that make a
value representable); business rules such as "an order needs at least one item" belong to the
domain and are reported with the same error envelope.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from shop.application.checkout import CheckoutCommand
from shop.domain.cart import OrderLine
from shop.domain.money import Money
from shop.domain.order import Order, OrderStatus
from shop.domain.payment import CardToken


class ItemIn(BaseModel):
    price: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
    qty: Annotated[int, Field(strict=True)]
    title: str | None = None


class CheckoutIn(BaseModel):
    # Unknown fields are ignored on purpose. This is what keeps a legacy client that still
    # sends `free_ship` working while making sure the flag has no effect.
    model_config = ConfigDict(extra="ignore")

    items: list[ItemIn] = Field(default_factory=list)
    email: str | None = None
    promo: str | None = None
    user_type: str | None = None
    delivery: str | None = None
    city: str | None = None
    payment: str | None = None
    card: SecretStr | None = None

    def to_command(self) -> CheckoutCommand:
        return CheckoutCommand(
            lines=tuple(
                OrderLine(
                    unit_price=Money.from_uah(item.price), quantity=item.qty, title=item.title
                )
                for item in self.items
            ),
            email=self.email or "",
            promo_code=self.promo,
            customer_type=self.user_type,
            delivery=self.delivery,
            city=self.city,
            payment=self.payment,
            card=CardToken(self.card.get_secret_value()) if self.card else None,
        )


class StatusChangeIn(BaseModel):
    status: OrderStatus


class ItemOut(BaseModel):
    price: str
    qty: int
    title: str | None


class OrderOut(BaseModel):
    """An order as seen by clients. Amounts are strings with two decimals, never floats."""

    id: int
    email: str
    items: list[ItemOut]
    total: str
    status: OrderStatus
    created_at: datetime

    @classmethod
    def from_domain(cls, order: Order) -> OrderOut:
        return cls(
            id=order.id,
            email=str(order.email),
            items=[
                ItemOut(price=str(line.unit_price), qty=line.quantity, title=line.title)
                for line in order.lines
            ],
            total=str(order.total),
            status=order.status,
            created_at=order.created_at,
        )


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, str]] | None = None


class ErrorOut(BaseModel):
    error: ErrorBody
