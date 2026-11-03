import re

from use_case_contracts.ports import SimulatorRepository
from use_case_contracts.dtos import *


class FakeSimulatorRepository(SimulatorRepository):
    def get(self, simulator_id: str) -> SimulatorDetails | None:
        match = re.fullmatch(r"t(\d+)", simulator_id)
        if not match:
            return None
        n = int(match.group(1))
        if n < 1:
            return None
        input_params = [
            ParameterSpec(f"param_{chr(ord('a') + i)}", ParamType.FLOAT)
            for i in range(n)
        ]
        return SimulatorDetails(
            model_name="TestModel",
            version="1.0.0",
            created_at="2026-05-28T14:10:00",
            bin_url="rtmf/test-model:1.0.0",
            input_params=input_params,
            output_params=[
                ParameterSpec("result_x", ParamType.FLOAT),
            ],
        )

    def list_simulators(self) -> list[SimulatorSummary]:
        raise NotImplementedError("Implement me!")
