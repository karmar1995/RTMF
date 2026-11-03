from __future__ import annotations

from typing import List

from services.use_case.utils.pagination import paginate
from use_case_contracts.ports import SimulatorRepository
from use_case_contracts.dtos import (
    ListRecentRegistrationsResult,
    RegistrationDetails,
    RegistrationSummary,
)
from use_case_contracts.messages import GetRegistrationDetails, ListRecentRegistrations


def handle_list_recent_registrations(
    message: ListRecentRegistrations,
    repo: SimulatorRepository,
) -> ListRecentRegistrationsResult:
    query = (message.query or "").strip().lower()
    status_filter = (message.status or "").strip().lower()

    summaries: List[RegistrationSummary] = []
    for summary in repo.list_recent_registrations():
        if status_filter and summary.status.lower() != status_filter:
            continue
        if query and query not in summary.registration_id.lower() and query not in summary.model_name.lower():
            continue
        summaries.append(summary)

    summaries.sort(key=lambda item: item.created_at, reverse=True)
    registrations, total = paginate(summaries, message.page, message.per_page)
    return ListRecentRegistrationsResult(
        registrations=list(registrations),
        page=message.page,
        per_page=message.per_page,
        total=total,
    )


def handle_get_registration_details(
    message: GetRegistrationDetails,
    repo: SimulatorRepository,
) -> RegistrationDetails:
    details = repo.get_registration_details(message.registration_id)
    if details is None:
        return RegistrationDetails(
            registration_id=message.registration_id,
            model_name="Unknown",
            status="Unknown",
            created_at="",
        )
    return details
