from __future__ import annotations

import time
from typing import Any

from use_case_contracts.ports import UseCaseAPI
from adapters.use_case_adapter.fake_delay import RestLatencyEmulator

class TimingMiddleware(UseCaseAPI):
    def __init__(self, inner: UseCaseAPI) -> None:
        self._latency = RestLatencyEmulator(enabled=False, seed=123)
        self._inner = inner

    def handle(self, message: Any) -> Any:
        start = time.perf_counter()
        try:
            self._latency()
            result = self._inner.handle(message)
            self._latency()
            return result
        finally:
            _ = time.perf_counter() - start
