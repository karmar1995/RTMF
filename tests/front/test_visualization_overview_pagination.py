from __future__ import annotations

from services.front.main import app
from use_case_contracts.dtos import Job4Visualization, JobVisualizationPage
from use_case_contracts.errors import AuthenticationError
from use_case_contracts.messages import ListVisualizationJobs
from conftest import _installed


def test_visualization_overview_renders_jobs_with_pagination() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get("/simulation_visualization")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Job Visualization Overview" in body
    assert "job-1" in body
    assert "Showing 1\u201320 of 25 jobs" in body
    assert 'aria-label="Job visualization pages"' in body
    assert "page=2" in body
    assert "Previous" in body
    assert "Next" in body
    assert 'class="page-item active"' in body


def test_visualization_overview_passes_page_query_parameter() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get("/simulation_visualization?page=2")

    assert response.status_code == 200
    assert usecases.messages[-1] == ListVisualizationJobs(page=2, per_page=20)
    body = response.get_data(as_text=True)
    assert "Showing 21\u201325 of 25 jobs" in body
    assert 'class="page-item active"' in body


def test_visualization_overview_clamps_per_page_query_parameter() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get("/simulation_visualization?per_page=500")

    assert response.status_code == 200
    assert usecases.messages[-1] == ListVisualizationJobs(page=1, per_page=100)
    assert "Showing 1\u201325 of 25 jobs" in response.get_data(as_text=True)


def test_visualization_overview_ignores_invalid_page_parameters() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get("/simulation_visualization?page=abc&per_page=-5")

    assert response.status_code == 200
    assert usecases.messages[-1] == ListVisualizationJobs(page=1, per_page=20)


def test_visualization_overview_renders_empty_state() -> None:
    usecases = _FakeUseCases(job_count=0)
    with _installed(usecases):
        response = app.test_client().get("/simulation_visualization")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "No jobs available." in body
    assert "Showing" not in body


def test_visualization_overview_renders_windowed_pages_not_all_pages() -> None:
    usecases = _FakeUseCases(job_count=2500)
    with _installed(usecases):
        response = app.test_client().get("/simulation_visualization")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Showing 1\u201320 of 2500 jobs" in body
    for page_number in ("1", "2", "3", "125"):
        assert f"page={page_number}" in body
    assert "page=6" not in body
    assert "page=123" not in body
    assert body.count("&hellip;") >= 1


def test_visualization_overview_renders_window_around_current_page() -> None:
    usecases = _FakeUseCases(job_count=2500)
    with _installed(usecases):
        response = app.test_client().get("/simulation_visualization?page=50")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    for page_number in ("48", "49", "50", "51", "52"):
        assert f"page={page_number}" in body
    assert "page=53" not in body
    assert "page=47" not in body


def test_visualization_overview_renders_boundary_pages() -> None:
    usecases = _FakeUseCases(job_count=2500)
    with _installed(usecases):
        response = app.test_client().get("/simulation_visualization?page=125")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'href="/simulation_visualization?page=1&amp;per_page=20"' in body
    assert 'href="/simulation_visualization?page=125&amp;per_page=20"' in body
    assert 'class="page-item active"' in body
    assert 'href="/simulation_visualization?page=2' not in body


def test_visualization_overview_flashes_warning_on_auth_failure() -> None:
    usecases = _FailingUseCases()
    with _installed(usecases):
        client = app.test_client()
        with client.session_transaction() as session:
            session.clear()
        response = client.get("/simulation_visualization")
        with client.session_transaction() as session:
            flashed = session["_flashes"]

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "No jobs available." in body
    assert ("warning", "boom") in flashed


class _FakeUseCases:
    def __init__(self, job_count: int = 25) -> None:
        self.messages: list = []
        self._jobs = [
            Job4Visualization(
                job_id=f"job-{i}",
                model_name="model-a",
                created_at="2026-01-01T00:00:00Z",
            )
            for i in range(1, job_count + 1)
        ]

    def handle(self, message):
        self.messages.append(message)
        if isinstance(message, ListVisualizationJobs):
            start = (message.page - 1) * message.per_page
            return JobVisualizationPage(
                jobs=self._jobs[start : start + message.per_page],
                page=message.page,
                per_page=message.per_page,
                total=len(self._jobs),
            )
        raise AssertionError(f"Unexpected message: {message!r}")


class _FailingUseCases:
    def handle(self, message):
        if isinstance(message, ListVisualizationJobs):
            raise AuthenticationError("boom")
        raise AssertionError(f"Unexpected message: {message!r}")


class _MixedUseCases:
    """One plain job and one evaluation, as the merged list returns them."""

    def __init__(self) -> None:
        self.messages: list = []
        self._jobs = [
            Job4Visualization(
                job_id="job-1",
                model_name="Model A",
                created_at="2026-01-01T00:00:00Z",
                kind="job",
            ),
            Job4Visualization(
                job_id="eval-1",
                model_name="Model B",
                created_at="2026-01-02T00:00:00Z",
                kind="evaluation",
            ),
        ]

    def handle(self, message):
        self.messages.append(message)
        if isinstance(message, ListVisualizationJobs):
            return JobVisualizationPage(
                jobs=self._jobs,
                page=message.page,
                per_page=message.per_page,
                total=len(self._jobs),
            )
        raise AssertionError(f"Unexpected message: {message!r}")


def test_visualization_overview_labels_evaluation_rows() -> None:
    with _installed(_MixedUseCases()):
        response = app.test_client().get("/simulation_visualization")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "eval-1" in body
    assert "Model B" in body
    assert "Evaluation" in body
    # Evaluations are blue, not the yellow used before.
    assert "text-bg-primary" in body
    assert "table-primary" in body
    assert "warning" not in body


def test_visualization_overview_labels_plain_job_rows() -> None:
    with _installed(_MixedUseCases()):
        response = app.test_client().get("/simulation_visualization")

    body = response.get_data(as_text=True)
    assert "job-1" in body
    assert "Model A" in body
    assert ">Job<" in body
    # Jobs stay green.
    assert "text-bg-success" in body
    assert "table-success" in body


def test_visualization_overview_links_evaluation_to_visualize_route() -> None:
    with _installed(_MixedUseCases()):
        response = app.test_client().get("/simulation_visualization")

    body = response.get_data(as_text=True)
    # The mode chooser is reached with the evaluation id, which the resolver
    # now understands.
    assert "/simulation-groups/eval-1/visualize" in body


def test_visualization_overview_defaults_kind_for_legacy_dtos() -> None:
    class _LegacyUseCases:
        def handle(self, message):
            return JobVisualizationPage(
                jobs=[
                    Job4Visualization(
                        job_id="job-legacy",
                        model_name="Model A",
                        created_at="2026-01-01T00:00:00Z",
                    )
                ],
                page=1,
                per_page=20,
                total=1,
            )

    with _installed(_LegacyUseCases()):
        response = app.test_client().get("/simulation_visualization")

    assert response.status_code == 200
    assert "job-legacy" in response.get_data(as_text=True)
