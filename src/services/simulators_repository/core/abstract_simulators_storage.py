from abc import ABC, abstractmethod
from dataclasses import dataclass
from services.simulators_repository.core.abstract_simulator_repository import SimulatorSummary


@dataclass(frozen=True)
class SimulatorEntry:
    model_name: str
    version: str
    image_reference_url: str
    image_digest: str
    image_tags: list[str]
    input_params: list[tuple[str, str]]
    output_params: list[tuple[str, str]]
    simulator_id: str = ""


class AbstractSimulatorsStorage(ABC):
    """
    Abstract boundary for simulator persistence.
    """

    @abstractmethod
    def get_latest_simulator_by_model_name(self, model_name: str) -> SimulatorEntry | None:
        raise NotImplementedError

    @abstractmethod
    def get_simulator(self, simulator_id: str) -> SimulatorEntry | None:
        raise NotImplementedError

    @abstractmethod
    def insert(self, entry: SimulatorEntry) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_simulator(self, model_name: str, key: str, value: object) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_simulator(self, model_name: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def list_simulator_names(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def list_simulators_ids(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def get_simulators_summaries(self) -> list[SimulatorSummary]:
        raise NotImplementedError
