from __future__ import annotations

import json

import httpx
import pytest

from shop.domain.customer import CustomerType
from shop.domain.events import OrderPlaced
from shop.domain.money import Money
from shop.infrastructure.notifiers import EmailNotifier, SlackBigOrderNotifier
from tests.factories import NOW


class Recorder:
    def __init__(self, status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status
        self.client = httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status)

    @property
    def bodies(self) -> list[dict[str, object]]:
        return [json.loads(request.content) for request in self.requests]


def placed(total: str, customer_type: CustomerType = CustomerType.REGULAR) -> OrderPlaced:
    return OrderPlaced(
        occurred_at=NOW,
        order_id=9,
        email="buyer@example.com",
        total=Money.from_uah(total),
        customer_type=customer_type,
    )


def email(recorder: Recorder) -> EmailNotifier:
    return EmailNotifier(
        recorder.client,
        "https://mail.example.com/send",
        templates={CustomerType.VIP: "vip_order"},
        default_template="order",
    )


class TestEmail:
    @pytest.mark.parametrize(
        ("customer_type", "template"),
        [
            (CustomerType.REGULAR, "order"),
            (CustomerType.B2B, "order"),
            (CustomerType.VIP, "vip_order"),
        ],
    )
    def test_template_follows_the_customer_segment(
        self, customer_type: CustomerType, template: str
    ) -> None:
        recorder = Recorder()

        email(recorder).notify(placed("145.00", customer_type))

        assert recorder.bodies == [
            {"to": "buyer@example.com", "template": template, "total": 145.0}
        ]

    def test_templates_are_configuration_not_code(self) -> None:
        recorder = Recorder()
        notifier = EmailNotifier(
            recorder.client,
            "https://mail.example.com/send",
            templates={CustomerType.B2B: "invoice_order"},
            default_template="plain",
        )

        notifier.notify(placed("1", CustomerType.B2B))
        notifier.notify(placed("1", CustomerType.VIP))

        assert [body["template"] for body in recorder.bodies] == ["invoice_order", "plain"]

    def test_an_error_response_is_raised_for_the_bus_to_log(self) -> None:
        with pytest.raises(httpx.HTTPStatusError):
            email(Recorder(status=500)).notify(placed("1"))


class TestSlack:
    def slack(self, recorder: Recorder, threshold: str = "10000") -> SlackBigOrderNotifier:
        return SlackBigOrderNotifier(
            recorder.client, "https://slack.example.com/hook", threshold=Money.from_uah(threshold)
        )

    @pytest.mark.parametrize(("total", "posts"), [("10000.00", 0), ("10000.01", 1), ("99999", 1)])
    def test_only_orders_strictly_above_the_threshold_are_announced(
        self, total: str, posts: int
    ) -> None:
        recorder = Recorder()

        self.slack(recorder).notify(placed(total))

        assert len(recorder.requests) == posts

    def test_the_message_names_the_order(self) -> None:
        recorder = Recorder()

        self.slack(recorder).notify(placed("20000"))

        assert recorder.bodies == [{"text": "Big order 9"}]

    def test_the_threshold_is_configurable(self) -> None:
        recorder = Recorder()

        self.slack(recorder, threshold="100").notify(placed("100.01"))

        assert len(recorder.requests) == 1
