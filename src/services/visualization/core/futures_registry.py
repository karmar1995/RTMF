from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from typing import Any
from uuid import UUID

from services.visualization.core.errors import FutureNotFoundError


class FuturesRegistry:
    def __init__(self) -> None:
        self._futures: dict[UUID, tuple[Future, str, float]] = {}
        self._lock = threading.Lock()

    def add_future(self, id: UUID, future: Future, hash_value: str) -> None:
        with self._lock:
            self._futures[id] = (future, hash_value, time.time())

    def get_future(self, id: UUID) -> Future:
        val = self._futures.get(id)
        if val is None:
            raise FutureNotFoundError(f"Future {id} not found")
        future, _, _ = val
        return future

    def get_futures_ids(self) -> list[UUID]:
        return list(self._futures.keys())

    def get_timestamp(self, id: UUID) -> float:
        val = self._futures.get(id)
        if val is None:
            raise FutureNotFoundError(f"Future {id} not found")
        _, _, timestamp = val
        return timestamp

    def find_by_hash(self, target_hash: str) -> UUID | None:
        for uuid, (_, hash_value, _) in self._futures.items():
            if hash_value == target_hash:
                return uuid
        return None

    def delete_future(self, id: UUID) -> None:
        with self._lock:
            del self._futures[id]

    def shutdown(self) -> None:
        self._futures.clear()
