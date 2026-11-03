from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class ParamType(Enum):
    INT = "int"
    FLOAT = "float"
    BOOLEAN = "bool"
    STRING = "str"
    INT_TS = "int_ts"
    FLOAT_TS = "float_ts"
    BOOLEAN_TS = "bool_ts"
    STR_TS = "str_ts"


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    type: ParamType


@dataclass(frozen=True)
class BuildSpec:
    spec: dict


@dataclass(frozen=True)
class SimulatorRegistrationRequest:
    model_name: str

    zip_filename: str
    zip_bytes: bytes

    input_params: list  # list[ParameterSpec]
    output_params: list  # list[ParameterSpec]

    build: BuildSpec


@dataclass(frozen=True)
class SimulatorSummary:
    simulator_id: str
    model_name: str
    version: str
    created_at: datetime


@dataclass(frozen=True)
class SimulatorDetails:
    model_name: str
    version: str
    created_at: datetime
    bin_url: str
    build_spec: dict[str, Any] | None = None
    input_params: list[ParameterSpec] | None = None
    output_params: list[ParameterSpec] | None = None


@dataclass(frozen=True)
class RegistrationSummary:
    registration_id: str
    model_name: str
    status: str
    created_at: datetime

@dataclass(frozen=True)
class SimulatorRegistrationResult:
    model_name: str
    version: str
    build_id: str
    status: str


class AbstractSimulatorRepository(ABC):
    """
    Abstract user-end boundary for the Simulators Repository.
    """

    @abstractmethod
    def submit_simulator_registration(self, request: SimulatorRegistrationRequest) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_registration_status(
        self, registration_ids: list[str]
    ) -> list[SimulatorRegistrationResult]:
        raise NotImplementedError

    @abstractmethod
    def get_simulators_details(self, model_ids: list[str]) -> list[SimulatorDetails]:
        """
        Return simulator details for model_names in the same order.

        If a simulator is not found, return a placeholder SimulatorDetails with
        empty fields and a fallback created_at timestamp.
        """
        raise NotImplementedError

    @abstractmethod
    def list_simulators(self) -> list[SimulatorSummary]:
        """
        Return summaries of all simulators.

        Ordering: unspecified unless otherwise documented by implementation.
        """
        raise NotImplementedError

    @abstractmethod
    def list_recent_registrations(self, limit: int = 100) -> list[RegistrationSummary]:
        """
        Return recent registration summaries.

        Ordering: most recent first.
        """
        raise NotImplementedError
