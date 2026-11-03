from __future__ import annotations

from services.use_case.handlers.simulations import handle_list_visualization_jobs
from use_case_contracts.dtos import Job4Visualization, JobVisualizationPage
from use_case_contracts.messages import ListVisualizationJobs


def test_handler_forwards_pagination_to_repository() -> None:
    jobs_repo = _StubJobsRepository()
    result = handle_list_visualization_jobs(
        ListVisualizationJobs(page=3, per_page=25),
        jobsRepo=jobs_repo,
        simulatorsRepo=None,
    )

    assert jobs_repo.calls == [(3, 25)]
    assert result == JobVisualizationPage(
        jobs=[Job4Visualization(job_id="job-51", model_name="model-a", created_at="2026-01-01T00:00:00Z")],
        page=3,
        per_page=25,
        total=51,
    )


def test_handler_uses_default_pagination_when_unspecified() -> None:
    jobs_repo = _StubJobsRepository()
    handle_list_visualization_jobs(ListVisualizationJobs(), jobsRepo=jobs_repo, simulatorsRepo=None)

    assert jobs_repo.calls == [(1, 20)]


class _StubJobsRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def list_jobs_for_visualization(self, page: int = 1, per_page: int = 20) -> JobVisualizationPage:
        self.calls.append((page, per_page))
        return JobVisualizationPage(
            jobs=[Job4Visualization(job_id="job-51", model_name="model-a", created_at="2026-01-01T00:00:00Z")],
            page=page,
            per_page=per_page,
            total=51,
        )
