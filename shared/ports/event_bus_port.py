from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Type
from shared.domain_events import DomainEvent


Handler = Callable[[DomainEvent], Awaitable[None]]


class EventBusPort(ABC):
    """Abstract event bus contract."""

    @abstractmethod
    async def publish(self, event: DomainEvent) -> None:
        ...

    @abstractmethod
    def subscribe(self, event_type: Type[DomainEvent], handler: Handler) -> None:
        ...
