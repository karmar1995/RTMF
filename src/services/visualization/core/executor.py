from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any
from uuid import UUID, uuid4

from services.visualization.core.futures_registry import FuturesRegistry
from services.visualization.enums.plot_status import PlotStatus


class VisualizationExecutor:
    def __init__(
        self,
        max_workers: int = 4,
        delete_after_return: bool = False,
        cleanup_interval: int = 900,
    ) -> None:
        self._executor = ThreadPoolExecutor(max_workers)
        self._futures_registry = FuturesRegistry()
        self._delete_after_return = delete_after_return
        self._cleanup_interval = cleanup_interval
        self._lock = threading.Lock()

        self._monitor_thread = threading.Thread(
            target=self._check_registry, daemon=True
        )
        self._monitor_thread.start()

    def submit_future(self, hash_value: str, func: Any, *args: Any, **kwargs: Any) -> UUID:
        existing_id: UUID | None = self._futures_registry.find_by_hash(hash_value)
        if existing_id is not None:
            return existing_id

        id = uuid4()
        self._futures_registry.add_future(
            id, self._executor.submit(func, *args, **kwargs), hash_value
        )
        return id

    def get_future_status(self, id: UUID) -> dict[str, PlotStatus]:
        future: Future = self._futures_registry.get_future(id)
        if future.done():
            if future.exception() is not None:
                return {"status": PlotStatus.ERROR}
            return {"status": PlotStatus.DONE}
        return {"status": PlotStatus.RUNNING}

    def get_result(self, id: UUID) -> str:
        future: Future = self._futures_registry.get_future(id)
        try:
            result: str = future.result()
            if self._delete_after_return:
                self._futures_registry.delete_future(id)
            return result
        except Exception as e:
            return str(e)

    def _check_registry(self) -> None:
        while True:
            ids: list[UUID] = self._futures_registry.get_futures_ids()
            ids_to_del: list[UUID] = []
            for id in ids:
                timestamp = self._futures_registry.get_timestamp(id)
                if time.time() - timestamp > self._cleanup_interval:
                    ids_to_del.append(id)

            for id in ids_to_del:
                self._futures_registry.delete_future(id)

            time.sleep(self._cleanup_interval)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._futures_registry.shutdown()
