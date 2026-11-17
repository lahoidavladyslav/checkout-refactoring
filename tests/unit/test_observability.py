from __future__ import annotations

import json
import logging
import sys

import pytest

from shop.observability import JsonFormatter, correlation_id, mask_email


def render(message: str = "hello", *args: object, **extra: object) -> dict[str, object]:
    record = logging.LogRecord("shop.test", logging.INFO, __file__, 1, message, args, None)
    for key, value in extra.items():
        setattr(record, key, value)
    parsed: dict[str, object] = json.loads(JsonFormatter().format(record))
    return parsed


class TestMasking:
    @pytest.mark.parametrize(
        ("text", "masked"),
        [
            ("buyer@example.com", "b***@example.com"),
            ("to=john.doe+tag@mail.example.co.uk done", "to=j***@mail.example.co.uk done"),
            ("a@b.c and x@y.zz", "a***@b.c and x***@y.zz"),
            ("no address here", "no address here"),
            ("5 @ home", "5 @ home"),
        ],
    )
    def test_mask_email(self, text: str, masked: str) -> None:
        assert mask_email(text) == masked


class TestJsonFormatter:
    def test_one_valid_json_object_with_the_standard_fields(self) -> None:
        entry = render("order %s placed", 7)

        assert entry["message"] == "order 7 placed"
        assert entry["level"] == "INFO"
        assert entry["logger"] == "shop.test"
        assert str(entry["timestamp"]).endswith("+00:00")

    def test_the_correlation_id_is_included(self) -> None:
        token = correlation_id.set("req-1")
        try:
            assert render()["correlation_id"] == "req-1"
        finally:
            correlation_id.reset(token)

    def test_the_correlation_id_is_null_outside_a_request(self) -> None:
        assert render()["correlation_id"] is None

    def test_emails_are_masked_in_the_message_and_in_extras(self) -> None:
        entry = render("sent to %s", "buyer@example.com", recipient="buyer@example.com", count=2)

        assert entry["message"] == "sent to b***@example.com"
        assert entry["recipient"] == "b***@example.com"
        assert entry["count"] == 2

    def test_emails_are_masked_in_tracebacks(self) -> None:
        try:
            raise RuntimeError("cannot mail buyer@example.com")
        except RuntimeError:
            record = logging.LogRecord(
                "shop.test", logging.ERROR, __file__, 1, "failed", (), sys.exc_info()
            )

        entry = json.loads(JsonFormatter().format(record))

        assert "buyer@example.com" not in entry["exception"]
        assert "b***@example.com" in entry["exception"]

    def test_non_ascii_text_is_kept_readable(self) -> None:
        assert render("замовлення")["message"] == "замовлення"
