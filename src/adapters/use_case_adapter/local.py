from __future__ import annotations

from typing import Any

from services.use_case.bus import InProcessBus
from use_case_contracts.ports import UseCaseAPI


class LocalUseCaseAdapter(UseCaseAPI):
    def __init__(self, bus: InProcessBus) -> None:
        self._bus = bus

    def handle(self, message: Any) -> Any:
        return self._bus.handle(message)
