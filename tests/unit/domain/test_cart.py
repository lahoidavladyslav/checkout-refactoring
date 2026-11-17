from __future__ import annotations

import pytest

from shop.domain.cart import Cart
from shop.domain.customer import CustomerType, EmailAddress
from shop.domain.errors import InvalidEmailError, InvalidQuantityError, NoItemsError
from shop.domain.money import Money
from tests.factories import line


class TestCart:
    def test_subtotal_and_units(self) -> None:
        cart = Cart.of([line("100", 2), line("50.50", 3)])

        assert cart.subtotal == Money.from_uah("351.50")
        assert cart.units == 5

    def test_empty_cart_is_rejected(self) -> None:
        with pytest.raises(NoItemsError):
            Cart.of([])

    @pytest.mark.parametrize("quantity", [0, -1])
    def test_non_positive_quantity_is_rejected(self, quantity: int) -> None:
        with pytest.raises(InvalidQuantityError):
            Cart.of([line(), line(quantity=quantity)])


class TestEmailAddress:
    @pytest.mark.parametrize("value", ["a@b", "buyer@example.com", "@"])
    def test_accepts_anything_with_an_at_sign(self, value: str) -> None:
        assert str(EmailAddress(value)) == value

    @pytest.mark.parametrize("value", ["", "buyer.example.com"])
    def test_rejects_the_rest(self, value: str) -> None:
        with pytest.raises(InvalidEmailError):
            EmailAddress(value)


class TestCustomerType:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("vip", CustomerType.VIP),
            ("b2b", CustomerType.B2B),
            ("regular", CustomerType.REGULAR),
            (None, CustomerType.REGULAR),
            ("", CustomerType.REGULAR),
            ("gold", CustomerType.REGULAR),
            ("VIP", CustomerType.REGULAR),
        ],
    )
    def test_parse_is_lenient(self, raw: str | None, expected: CustomerType) -> None:
        assert CustomerType.parse(raw) is expected
