import threading
import uuid
from collections import deque
from services.simulators_repository.core.details.versioned_simulator_registration_request import (
    VersionedSimulatorRegistrationRequest,
)


class BuildRequestsQueue:
    """
    In-memory queue for build requests that have not been assigned a build job.
    Thread-safe for use from background worker threads and request handlers.
    """

    def __init__(self) -> None:
        self._queue = deque()          # FIFO queue of (build_id, request)
        self._index: dict[str, VersionedSimulatorRegistrationRequest] = {}
        self._lock = threading.Lock()

    def enqueue(self, request: VersionedSimulatorRegistrationRequest) -> str:
        if request is None:
            raise ValueError("request is required")

        build_id = str(uuid.uuid4())
        with self._lock:
            self._queue.append((build_id, request))
            self._index[build_id] = request
        return build_id

    def is_queued(self, build_id: str) -> bool:
        if not isinstance(build_id, str) or not build_id.strip():
            raise ValueError("build_id must be a non-empty string")
        with self._lock:
            return build_id in self._index

    def get_request(self, build_id: str) -> VersionedSimulatorRegistrationRequest | None:
        if not isinstance(build_id, str) or not build_id.strip():
            raise ValueError("build_id must be a non-empty string")
        with self._lock:
            return self._index.get(build_id)

    def dequeue(self) -> tuple[str, VersionedSimulatorRegistrationRequest] | None:
        with self._lock:
            if not self._queue:
                return None
            build_id, request = self._queue.popleft()
            self._index.pop(build_id, None)
            return build_id, request

    def list_queued_ids(self) -> list[str]:
        with self._lock:
            return [build_id for build_id, _ in self._queue]
