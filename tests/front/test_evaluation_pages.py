from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from services.front.main import app
from use_case_contracts.dtos import (
    CurrentSessionContext,
    EvaluationProgress,
    EvaluationResult,
    EvaluationSummary,
    EvaluationVisualization,
    EvaluationVisualizationState,
    GetEvaluationDetailsResult,
    ListEvaluationsResult,
    ListSimulatorsResult,
    ParameterSpec,
    SimulatorDetails,
    SimulatorSummary,
)
from use_case_contracts.errors import AuthorizationDeniedError, UnauthenticatedError
from use_case_contracts.messages import (
    GetCurrentSessionContext,
    GetEvaluationDetails,
    GetSimulatorDetails,
    ListEvaluations,
    ListSimulators,
    OpenEvaluationRunForm,
    RequireAuthenticatedSession,
    RunEvaluation,
)
from use_case_contracts.permissions import (
    JOB_CREATE,
    JOB_READ,
    SIMULATOR_READ,
)


def test_evaluation_page_routes_render_successfully() -> None:
    with _installed(_FakeUseCases()):
        client = app.test_client()
        for route in ("/evaluation/run", "/evaluations", f"/evaluations/{'a' * 16}"):
            response = client.get(route)
            assert response.status_code == 200, route


def test_run_evaluation_form_lists_models() -> None:
    with _installed(_FakeUseCases()):
        body = app.test_client().get("/evaluation/run").get_data(as_text=True)

    assert "Run Evaluation" in body
    assert "model-1" in body
    assert "My Model (v1)" in body
    assert 'name="kmax"' in body
    assert 'name="output"' in body
    assert 'name="repetitions"' in body


def test_run_evaluation_form_accepts_prefill_query_params() -> None:
    with _installed(_FakeUseCases()):
        response = app.test_client().get(
            "/evaluation/run",
            query_string={
                "model": "model-1",
                "output": "output-1",
                "aggregation": "mean",
                "bounds": '{"x": [0.0, 1.0]}',
            },
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "applyPrefill" in body
    assert "prefill.get('bounds')" in body


def test_evaluation_queue_lists_evaluations_with_statuses() -> None:
    with _installed(_FakeUseCases()):
        body = app.test_client().get("/evaluations").get_data(as_text=True)

    assert "Evaluation Queue" in body
    assert f"/evaluations/{'a' * 16}" in body
    assert "Running" in body
    assert "Success" in body
    assert "2026-01-01T12:00:00Z" in body


def test_evaluation_submit_redirects_to_details() -> None:
    with _installed(_FakeUseCases()):
        response = app.test_client().post(
            "/evaluation/run/submit",
            data={
                "model": "model-1",
                "output": "output-1",
                "repetitions": "64",
                "kmax": "20",
                "epsilon": "0.01",
                "batch_size": "2",
                "lhs_candidates": "1000",
                "random_state": "7",
                "params[x][min]": "0.0",
                "params[x][max]": "1.0",
            },
        )

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/evaluations/{'a' * 16}")


def test_evaluation_details_shows_success_result_and_visualization() -> None:
    with _installed(_FakeUseCases()):
        body = app.test_client().get(f"/evaluations/{'a' * 16}").get_data(
            as_text=True
        )

    assert "Evaluation Details" in body
    assert "Success" in body
    assert "Best value" in body
    assert "0.25" in body
    assert "important-param" in body
    assert '<div id="plot">convergence</div>' in body
    assert 'http-equiv="refresh"' not in body


def test_evaluation_details_shows_running_status_with_live_progress() -> None:
    with _installed(_FakeUseCases()):
        body = app.test_client().get(f"/evaluations/{'b' * 16}").get_data(
            as_text=True
        )

    assert "Running" in body
    assert "Evaluation is still running" in body
    # The finished-result card stays hidden while the evaluation is running.
    assert "Optimization Result" not in body
    # ...but progress and both live plots are already on the page.
    assert "Progress" in body
    assert "3 / 30" in body
    assert "Jobs submitted" in body
    assert "sensitivity: 1" in body
    assert "ssbo: 12" in body
    assert '<div id="plot">live-convergence</div>' in body
    assert '<div id="plot">live-exploration</div>' in body
    assert "SSBO convergence" in body
    assert "Explored points" in body
    assert 'http-equiv="refresh"' in body


def test_evaluation_details_shows_both_plots_when_successful() -> None:
    with _installed(_FakeUseCases()):
        body = app.test_client().get(f"/evaluations/{'a' * 16}").get_data(
            as_text=True
        )

    assert "SSBO convergence" in body
    assert "Explored points" in body
    assert 'http-equiv="refresh"' not in body


def test_evaluation_details_refreshes_while_plot_pending() -> None:
    with _installed(_FakeUseCases()):
        body = app.test_client().get(f"/evaluations/{'c' * 16}").get_data(
            as_text=True
        )

    assert "Success" in body
    assert "Waiting for visualization" in body
    assert 'http-equiv="refresh"' in body
    assert 'content="5"' in body


def test_sidebar_shows_evaluation_entries_with_permissions() -> None:
    permissions = {SIMULATOR_READ, JOB_CREATE, JOB_READ}
    with _installed(_FakeUseCases(permissions)):
        body = app.test_client().get("/").get_data(as_text=True)

    assert 'href="/evaluation/run"' in body
    assert 'href="/evaluations"' in body
    assert "Run Evaluation" in body
    assert "Evaluation Queue" in body
    assert "Evaluation</span>" in body


def test_sidebar_hides_evaluation_entries_without_permissions() -> None:
    with _installed(_FakeUseCases({SIMULATOR_READ})):
        body = app.test_client().get("/").get_data(as_text=True)

    assert 'href="/evaluation/run"' not in body
    assert 'href="/evaluations"' not in body
    assert "Evaluation</span>" not in body


def test_manually_entered_evaluation_routes_are_denied_without_permission() -> None:
    with _installed(_FakeUseCases({SIMULATOR_READ})):
        run_response = app.test_client().get("/evaluation/run")
        queue_response = app.test_client().get("/evaluations")

    assert run_response.status_code == 403
    assert queue_response.status_code == 403


@contextmanager
def _installed(usecases):
    previous_usecases = app.extensions.get("usecases")
    previous_auth_enforced = app.config.get("AUTH_ENFORCED")
    app.extensions["usecases"] = usecases
    app.config["AUTH_ENFORCED"] = True
    try:
        yield
    finally:
        if previous_usecases is None:
            app.extensions.pop("usecases", None)
        else:
            app.extensions["usecases"] = previous_usecases
        if previous_auth_enforced is None:
            app.config.pop("AUTH_ENFORCED", None)
        else:
            app.config["AUTH_ENFORCED"] = previous_auth_enforced


class _FakeUseCases:
    def __init__(self, permissions: set[str] | None = None) -> None:
        self.permissions = frozenset(
            permissions if permissions is not None else {SIMULATOR_READ, JOB_CREATE, JOB_READ}
        )

    def handle(self, message):
        if isinstance(message, RequireAuthenticatedSession):
            return None
        if isinstance(message, GetCurrentSessionContext):
            return CurrentSessionContext(
                subject_id="subject-1",
                permissions=self.permissions,
            )
        if isinstance(message, OpenEvaluationRunForm):
            if JOB_CREATE in self.permissions:
                return None
            raise AuthorizationDeniedError("Not authorized.")
        if isinstance(message, ListSimulators):
            if SIMULATOR_READ not in self.permissions:
                raise AuthorizationDeniedError("Not authorized.")
            simulators = [_simulator()]
            return ListSimulatorsResult(
                simulators=simulators,
                page=message.page,
                per_page=message.per_page,
                total=len(simulators),
            )
        if isinstance(message, GetSimulatorDetails):
            return SimulatorDetails(
                model_name="My Model",
                version="v1",
                created_at="2026-01-01T00:00:00Z",
                bin_url="docker://model-1",
                input_params=[ParameterSpec("x", "float")],
                output_params=[ParameterSpec("output-1", "float")],
            )
        if isinstance(message, ListEvaluations):
            if JOB_READ not in self.permissions:
                raise AuthorizationDeniedError("Not authorized.")
            return ListEvaluationsResult(evaluations=[_queued_summary(), _success_summary()])
        if isinstance(message, GetEvaluationDetails):
            if JOB_READ not in self.permissions:
                raise AuthorizationDeniedError("Not authorized.")
            return _details(message.evaluation_id)
        if isinstance(message, RunEvaluation):
            if JOB_CREATE not in self.permissions:
                raise AuthorizationDeniedError("Not authorized.")
            return _success_summary()
        raise AssertionError(f"Unexpected message: {message!r}")


def _simulator() -> SimulatorSummary:
    return SimulatorSummary(
        model_name="My Model",
        version="v1",
        created_at="2026-01-01T00:00:00Z",
        simulator_id="model-1",
    )


def _queued_summary() -> EvaluationSummary:
    return EvaluationSummary(
        evaluation_id="b" * 16,
        simulator_id="model-1",
        status="running",
        created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )


def _success_summary() -> EvaluationSummary:
    return EvaluationSummary(
        evaluation_id="a" * 16,
        simulator_id="model-1",
        status="success",
        created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )


def _details(evaluation_id: str) -> GetEvaluationDetailsResult:
    if evaluation_id == "b" * 16:
        return GetEvaluationDetailsResult(
            evaluation_id=evaluation_id,
            simulator_id="model-1",
            status="running",
            created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            result=None,
            convergence_visualization=EvaluationVisualization(
                state=EvaluationVisualizationState.READY,
                plot_html='<div id="plot">live-convergence</div>',
            ),
            exploration_visualization=EvaluationVisualization(
                state=EvaluationVisualizationState.READY,
                plot_html='<div id="plot">live-exploration</div>',
            ),
            progress=EvaluationProgress(
                evaluation_id=evaluation_id,
                status="optimizing",
                stage="optimizing",
                iteration=3,
                kmax=30,
                best_value=0.25,
                important_parameters=["important-param"],
                ssbo_history=[{"iteration": 0, "best_value": 0.9}],
                jobs_submitted=13,
                jobs_by_stage={"sensitivity": 1, "ssbo": 12},
            ),
        )
    if evaluation_id == "d" * 16:
        # A finished evaluation that still reports its progress card: the
        # stage must read "finished", never the phase it ran in.
        return GetEvaluationDetailsResult(
            evaluation_id=evaluation_id,
            simulator_id="model-1",
            status="success",
            created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            result=None,
            progress=EvaluationProgress(
                evaluation_id=evaluation_id,
                status="success",
                stage="finished",
                iteration=30,
                kmax=30,
                best_value=0.25,
                important_parameters=["x"],
                ssbo_history=[{"iteration": 29, "best_value": 0.25}],
                jobs_submitted=13,
                jobs_by_stage={"sensitivity": 1, "ssbo": 12},
            ),
        )
    if evaluation_id == "c" * 16:
        return GetEvaluationDetailsResult(
            evaluation_id=evaluation_id,
            simulator_id="model-1",
            status="success",
            created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            result=EvaluationResult(
                evaluation_id=evaluation_id,
                status="success",
                details={
                    "best_params": {"x": 1.5},
                    "best_value": 0.25,
                    "important_parameters": ["important-param"],
                    "iterations": 30,
                    "history": [
                        {"iteration": 1, "best_value": 0.5, "skipped": False},
                        {"iteration": 2, "best_value": 0.25, "skipped": False},
                    ],
                },
            ),
            convergence_visualization=EvaluationVisualization(
                state=EvaluationVisualizationState.PENDING,
                waiting_message="Waiting for visualization.",
            ),
        )
    return GetEvaluationDetailsResult(
        evaluation_id=evaluation_id,
        simulator_id="model-1",
        status="success",
        created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        result=EvaluationResult(
            evaluation_id=evaluation_id,
            status="success",
            details={
                "best_params": {"x": 1.5},
                "best_value": 0.25,
                "important_parameters": ["important-param"],
                "iterations": 30,
                "history": [
                    {"iteration": 1, "best_value": 0.5, "skipped": False},
                    {"iteration": 2, "best_value": 0.25, "skipped": False},
                ],
            },
        ),
        convergence_visualization=EvaluationVisualization(
            state=EvaluationVisualizationState.READY,
            plot_html='<div id="plot">convergence</div>',
        ),
    )


def test_evaluation_details_shows_finished_stage_for_a_completed_run() -> None:
    with _installed(_FakeUseCases()):
        body = app.test_client().get(f"/evaluations/{'d' * 16}").get_data(
            as_text=True
        )

    assert "Progress" in body
    assert "finished" in body
    # The phase it ran in must not survive as the reported stage.
    assert "optimizing" not in body
    # Progress details are still shown once the run is over.
    assert "30 / 30" in body


def test_completed_evaluation_is_not_treated_as_running() -> None:
    with _installed(_FakeUseCases()):
        body = app.test_client().get(f"/evaluations/{'d' * 16}").get_data(
            as_text=True
        )

    assert "Evaluation is still running" not in body
    assert 'http-equiv="refresh"' not in body
