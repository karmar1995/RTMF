from __future__ import annotations

from typing import Any, Callable, Dict, Type

from use_case_contracts.errors import UnregisteredMessageError


Handler = Callable[[Any], Any]


class InProcessBus:
    def __init__(self) -> None:
        self._handlers: Dict[Type[Any], Handler] = {}

    def register(self, message_type: Type[Any], handler: Handler) -> None:
        self._handlers[message_type] = handler

    def handle(self, message: Any) -> Any:
        handler = self._handlers.get(type(message))
        if handler is None:
            raise UnregisteredMessageError(
                f"No handler registered for message type: {type(message).__name__}"
            )
        return handler(message)
