"""Event handlers that need nothing but logging."""

from __future__ import annotations

import logging

from shop.domain.events import RefundRequested

logger = logging.getLogger(__name__)


def log_refund_request(event: RefundRequested) -> None:
    """Record that a refund is due. Executing it is the payment provider's business."""
    logger.info("refund of %s requested for order %s", event.amount, event.order_id)
