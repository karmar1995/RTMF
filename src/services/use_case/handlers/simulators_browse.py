from __future__ import annotations

from typing import List

from services.use_case.utils.pagination import paginate
from use_case_contracts.ports import SimulatorRepository
from use_case_contracts.dtos import ListSimulatorsResult, SimulatorDetails, SimulatorSummary
from use_case_contracts.messages import GetSimulatorDetails, ListSimulators


def handle_list_simulators(
    message: ListSimulators,
    repo: SimulatorRepository,
) -> ListSimulatorsResult:
    query = (message.query or "").strip().lower()
    summaries: List[SimulatorSummary] = []

    for summary in repo.list_simulators():
        if query and query not in summary.model_name.lower():
            continue
        summaries.append(summary)

    summaries.sort(key=lambda item: item.created_at, reverse=True)
    simulators, total = paginate(summaries, message.page, message.per_page)
    return ListSimulatorsResult(
        simulators=list(simulators),
        page=message.page,
        per_page=message.per_page,
        total=total,
    )


def handle_get_simulator_details(
    message: GetSimulatorDetails,
    repo: SimulatorRepository,
) -> SimulatorDetails:
    record = repo.get(message.simulator_id)
    if record is None:
        return SimulatorDetails(
            model_name="Unknown simulator",
            version="unknown",
            created_at="",
            bin_url="",
            build_spec=None,
            input_params=None,
            output_params=None,
        )

    return record
