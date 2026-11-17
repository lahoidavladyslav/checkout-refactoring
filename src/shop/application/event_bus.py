"""A minimal in-process event bus."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any

from shop.domain.events import DomainEvent

logger = logging.getLogger(__name__)


class EventBus:
    """Delivers events to subscribers of their exact type.

    A failing subscriber is logged and skipped: an event is a fact that already happened, and
    a broken notification must neither undo it nor stop the other subscribers.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Callable[[Any], None]]] = defaultdict(list)

    def subscribe[E: DomainEvent](self, event_type: type[E], handler: Callable[[E], None]) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, events: Iterable[DomainEvent]) -> None:
        for event in events:
            for handler in self._handlers.get(type(event), []):
                try:
                    handler(event)
                except Exception:
                    logger.exception(
                        "handler %r failed for %s",
                        getattr(handler, "__qualname__", handler),
                        type(event).__name__,
                    )
