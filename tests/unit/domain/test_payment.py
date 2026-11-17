from __future__ import annotations

from shop.domain.payment import CardToken

NUMBER = "4111111111111111"


def test_the_token_can_be_revealed_for_the_gateway() -> None:
    assert CardToken(NUMBER).reveal() == NUMBER


def test_repr_is_masked() -> None:
    assert repr(CardToken(NUMBER)) == "CardToken(***)"


def test_str_is_masked() -> None:
    assert str(CardToken(NUMBER)) == "***"


def test_the_number_survives_neither_formatting_nor_containers() -> None:
    token = CardToken(NUMBER)

    rendered = f"{token} {token!r} {[token]} {{'card': {token!r}}}"

    assert NUMBER not in rendered
    assert "4111" not in rendered
