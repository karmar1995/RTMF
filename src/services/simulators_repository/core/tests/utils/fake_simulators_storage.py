from datetime import datetime

from services.simulators_repository.core.abstract_simulator_repository import SimulatorSummary
from services.simulators_repository.core.abstract_simulators_storage import AbstractSimulatorsStorage, SimulatorEntry


class FakeSimulatorsStorage(AbstractSimulatorsStorage):
    def __init__(
        self,
        fail_inserts: bool = False,
        fail_updates: bool = False,
    ) -> None:
        self._entries = {}
        self._fail_inserts = fail_inserts
        self._fail_updates = fail_updates

    def get_latest_simulator_by_model_name(self, model_name: str) -> SimulatorEntry | None:
        return self._entries.get(model_name)

    def get_simulator(self, simulator_id: str) -> SimulatorEntry | None:
        for entry in self._entries.values():
            if entry.simulator_id == simulator_id:
                return entry
        return self._entries.get(simulator_id)

    def insert(self, entry: SimulatorEntry) -> None:
        if self._fail_inserts:
            raise RuntimeError("Simulated insert failure")
        self._entries[entry.model_name] = entry

    def update_simulator(self, model_name: str, key: str, value: object) -> None:
        if self._fail_updates:
            raise RuntimeError("Simulated update failure")
        entry = self._entries.get(model_name)
        if entry is None:
            raise KeyError(f"Simulator '{model_name}' not found")
        if key not in entry.__dataclass_fields__:
            raise ValueError(f"Unknown simulator field: {key}")
        updated = {
            field: getattr(entry, field)
            for field in entry.__dataclass_fields__.keys()
        }
        updated[key] = value
        self._entries[model_name] = SimulatorEntry(**updated)

    def delete_simulator(self, model_name: str) -> bool:
        return self._entries.pop(model_name, None) is not None

    def list_simulator_names(self) -> list[str]:
        return sorted(self._entries.keys())

    def list_simulators_ids(self) -> list[str]:
        return sorted(entry.simulator_id for entry in self._entries.values())

    def get_simulators_summaries(self) -> list[SimulatorSummary]:
        return [
            SimulatorSummary(
                simulator_id=entry.simulator_id,
                model_name=entry.model_name,
                version=entry.version,
                created_at=datetime(2000, 1, 1),
            )
            for entry in sorted(self._entries.values(), key=lambda item: item.simulator_id)
        ]
