import asyncio
import logging
from collections import defaultdict
from typing import Callable, Awaitable, Type

from shared.domain_events import DomainEvent
from shared.ports.event_bus_port import EventBusPort, Handler

logger = logging.getLogger(__name__)


class InMemoryEventBus(EventBusPort):
    """Simple in-process event bus."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: Type[DomainEvent], handler: Handler) -> None:
        self._handlers[event_type.__name__].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        handlers = self._handlers.get(event.event_name, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception as exc:
                logger.exception("Event handler error for %s: %s", event.event_name, exc)
