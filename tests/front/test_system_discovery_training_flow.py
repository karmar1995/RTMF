from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest

from services.front.main import app
from use_case_contracts.dtos import (
    GetSystemDiscoveryTrainingStatusResult,
    ListSystemDiscoveryTrainingsResult,
    OpenSystemDiscoveryTrainingEvaluationResult,
    SaveSystemDiscoveryModelResult,
    SystemDiscoveryEvaluationCategory,
    SystemDiscoveryEvaluationMetric,
    SystemDiscoverySavedModelRecord,
    SystemDiscoverySimulationRecord,
    SystemDiscoverySimulationState,
    SystemDiscoverySimulationVisualization,
    SystemDiscoverySimulationVisualizationState,
    SystemDiscoveryTrainingEvaluationMetadata,
    SystemDiscoveryTrainingEvaluationPlot,
    SystemDiscoveryTrainingEvaluationPlotState,
    SystemDiscoveryTrainingEvaluationState,
    SystemDiscoveryTrainingRecord,
    SystemDiscoveryTrainingState,
    TrainSystemDiscoveryResult,
)
from use_case_contracts.messages import (
    GetSystemDiscoveryTrainingStatus,
    GetSavedSystemDiscoveryModelDetails,
    GetSystemDiscoverySimulationDetails,
    ListSavedSystemDiscoveryModels,
    ListSystemDiscoverySimulations,
    ListSystemDiscoveryTrainings,
    OpenSystemDiscoveryTrainingForm,
    OpenSystemDiscoveryTrainingEvaluation,
    RequireAuthenticatedSession,
    RemoveSavedSystemDiscoveryModel,
    RemoveSystemDiscoveryTrainingQueueEntry,
    SaveSystemDiscoveryModel,
    TrainSystemDiscovery,
)


class FakeUseCases:
    def __init__(self) -> None:
        self.messages = []
        self.trainings = []
        self.saved_models = []
        self.simulations = []
        self.simulation_visualization_state = SystemDiscoverySimulationVisualizationState.PENDING
        self.results_plot_state = SystemDiscoveryTrainingEvaluationPlotState.PENDING
        self.cdf_plot_state = SystemDiscoveryTrainingEvaluationPlotState.READY

    def handle(self, message):
        self.messages.append(message)
        if isinstance(message, RequireAuthenticatedSession):
            return None
        if isinstance(message, OpenSystemDiscoveryTrainingForm):
            return None
        if isinstance(message, TrainSystemDiscovery):
            return TrainSystemDiscoveryResult(training_id="train-1", status="queued")
        if isinstance(message, ListSystemDiscoveryTrainings):
            return ListSystemDiscoveryTrainingsResult(
                trainings=self.trainings,
                failures=[],
                total=len(self.trainings),
            )
        if isinstance(message, GetSystemDiscoveryTrainingStatus):
            record = next(
                record
                for record in self.trainings
                if record.training_id == message.training_id
            )
            return GetSystemDiscoveryTrainingStatusResult(
                training=record,
                failures=[],
            )
        if isinstance(message, OpenSystemDiscoveryTrainingEvaluation):
            record = next(
                record
                for record in self.trainings
                if record.training_id == message.training_id
            )
            if record.state != SystemDiscoveryTrainingState.COMPLETED:
                return OpenSystemDiscoveryTrainingEvaluationResult(
                    training=record,
                    state=SystemDiscoveryTrainingEvaluationState.NOT_COMPLETED,
                    message="Model evaluation is available only for completed trainings.",
                )
            return OpenSystemDiscoveryTrainingEvaluationResult(
                training=record,
                state=SystemDiscoveryTrainingEvaluationState.READY,
                metadata=_metadata(),
                can_save_model=True,
                results_plot=SystemDiscoveryTrainingEvaluationPlot(
                    title="Results",
                    state=self.results_plot_state,
                    plot_html=None,
                    waiting_message="Waiting for visualization."
                    if self.results_plot_state == SystemDiscoveryTrainingEvaluationPlotState.PENDING
                    else "",
                ),
                cdf_plot=SystemDiscoveryTrainingEvaluationPlot(
                    title="CDF",
                    state=self.cdf_plot_state,
                    plot_html="<div>cdf plot</div>"
                    if self.cdf_plot_state == SystemDiscoveryTrainingEvaluationPlotState.READY
                    else None,
                    waiting_message="",
                ),
            )
        if isinstance(message, SaveSystemDiscoveryModel):
            self.saved_models.append(_saved_model(message.training_id))
            self.trainings = [
                record
                for record in self.trainings
                if record.training_id != message.training_id
            ]
            return SaveSystemDiscoveryModelResult(model_id=message.training_id)
        if isinstance(message, RemoveSystemDiscoveryTrainingQueueEntry):
            self.trainings = [
                record
                for record in self.trainings
                if record.training_id != message.training_id
            ]
            return type("Result", (), {"training_id": message.training_id, "removed": True})()
        if isinstance(message, RemoveSavedSystemDiscoveryModel):
            self.saved_models = [
                record
                for record in self.saved_models
                if record.model_id != message.model_id
            ]
            return type("Result", (), {"model_id": message.model_id, "removed": True})()
        if isinstance(message, ListSavedSystemDiscoveryModels):
            return type(
                "Result",
                (),
                {
                    "models": self.saved_models,
                    "total": len(self.saved_models),
                    "page": message.page,
                    "per_page": message.per_page,
                },
            )()
        if isinstance(message, ListSystemDiscoverySimulations):
            return type(
                "Result",
                (),
                {
                    "simulations": self.simulations,
                    "failures": [],
                    "total": len(self.simulations),
                    "page": message.page,
                    "per_page": message.per_page,
                },
            )()
        if isinstance(message, GetSavedSystemDiscoveryModelDetails):
            model = next(
                model
                for model in self.saved_models
                if model.model_id == message.model_id
            )
            return type("Result", (), {"model": model})()
        if isinstance(message, GetSystemDiscoverySimulationDetails):
            simulation = next(
                simulation
                for simulation in self.simulations
                if simulation.simulation_id == message.simulation_id
            )
            return type(
                "Result",
                (),
                {
                    "simulation": simulation,
                    "visualization": SystemDiscoverySimulationVisualization(
                        state=self.simulation_visualization_state,
                        plot_html="<div>simulation plot</div>"
                        if self.simulation_visualization_state
                        == SystemDiscoverySimulationVisualizationState.READY
                        else None,
                        waiting_message="Waiting for visualization."
                        if self.simulation_visualization_state
                        == SystemDiscoverySimulationVisualizationState.PENDING
                        else "",
                    ),
                    "failures": [],
                },
            )()
        raise AssertionError(f"Unexpected message: {message!r}")


@pytest.fixture
def fake_usecases():
    fake = FakeUseCases()
    previous = app.extensions.get("usecases")
    previous_secret = app.config.get("SECRET_KEY")
    app.config["SECRET_KEY"] = "test-secret"
    app.extensions["usecases"] = fake
    yield fake
    app.config["SECRET_KEY"] = previous_secret
    if previous is None:
        app.extensions.pop("usecases", None)
    else:
        app.extensions["usecases"] = previous


def test_given_training_page_when_get_then_form_renders(fake_usecases) -> None:
    response = app.test_client().get("/system_discovery_train")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'method="post"' in body
    assert 'name="training_archive"' in body
    assert "presentation-only" not in body
    assert any(
        isinstance(message, OpenSystemDiscoveryTrainingForm)
        for message in fake_usecases.messages
    )


def test_given_invalid_nlags_json_when_posting_training_then_use_case_is_not_called(fake_usecases) -> None:
    response = app.test_client().post(
        "/system_discovery_train",
        data={
            "training_archive": (io.BytesIO(b"zip"), "data.zip"),
            "nlags-x": "[(1, 2)]",
            "nlags-y": "1",
            "basis": "Polynomial",
            "degree": "2",
            "model": "narmax",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert not any(
        isinstance(message, TrainSystemDiscovery) for message in fake_usecases.messages
    )


@pytest.mark.parametrize("nlags_x", ["", "   \n\t  "])
def test_given_blank_nlags_x_when_posting_training_then_message_uses_none(fake_usecases, nlags_x: str) -> None:
    response = app.test_client().post(
        "/system_discovery_train",
        data={
            "training_archive": (io.BytesIO(b"zip"), "data.zip"),
            "nlags-x": nlags_x,
            "nlags-y": "1",
            "basis": "Polynomial",
            "degree": "2",
            "model": "narmax",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    message = next(
        message
        for message in fake_usecases.messages
        if isinstance(message, TrainSystemDiscovery)
    )
    assert message.nlags_x is None


@pytest.mark.parametrize("nlags_x", ["[1, 2]", "[[1, true]]", "[[1, 1.5]]", "[[]]"])
def test_given_invalid_nlags_shape_when_posting_training_then_use_case_is_not_called(fake_usecases, nlags_x: str) -> None:
    response = app.test_client().post(
        "/system_discovery_train",
        data={
            "training_archive": (io.BytesIO(b"zip"), "data.zip"),
            "nlags-x": nlags_x,
            "nlags-y": "1",
            "basis": "Polynomial",
            "degree": "2",
            "model": "narmax",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert not any(
        isinstance(message, TrainSystemDiscovery) for message in fake_usecases.messages
    )


def test_given_valid_training_post_when_submitted_then_redirects_to_training_detail(fake_usecases) -> None:
    response = app.test_client().post(
        "/system_discovery_train",
        data={
            "training_archive": (io.BytesIO(b"exact-zip"), "data.zip"),
            "nlags-x": "[[1, 2], [3, 4]]",
            "nlags-y": "1",
            "basis": "Polynomial",
            "degree": "2",
            "model": "narmax",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/system-discovery/training/train-1")
    message = next(
        message
        for message in fake_usecases.messages
        if isinstance(message, TrainSystemDiscovery)
    )
    assert message.training_data_archive == b"exact-zip"
    assert message.nlags_x == ((1, 2), (3, 4))


def test_given_invalid_training_post_when_form_rerenders_then_nlags_x_value_is_preserved(fake_usecases) -> None:
    response = app.test_client().post(
        "/system_discovery_train",
        data={
            "training_archive": (io.BytesIO(b"zip"), "data.zip"),
            "nlags-x": "[[1, 2]]",
            "nlags-y": "",
            "basis": "Polynomial",
            "degree": "2",
            "model": "narmax",
        },
        content_type="multipart/form-data",
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 400
    assert 'value="[[1, 2]]"' in body


def test_given_known_trainings_when_queue_get_then_records_are_rendered_and_refresh_use_case_is_used(fake_usecases) -> None:
    fake_usecases.trainings = [
        _record("train-1", SystemDiscoveryTrainingState.RUNNING),
        _record("train-2", SystemDiscoveryTrainingState.COMPLETED),
    ]

    response = app.test_client().get("/system-discovery/trainings")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "/system-discovery/training/train-1" in body
    assert "/system-discovery/training/train-2" in body
    assert "bg-warning" in body
    assert "Running" in body
    assert "bg-success" in body
    assert "Completed" in body
    assert "Raw status" not in body
    assert "Refresh queue" not in body
    assert "Remove" in body
    assert "/system-discovery/training/train-1/remove" in body
    assert [type(message) for message in fake_usecases.messages] == [
        ListSystemDiscoveryTrainings
    ]


def test_given_detail_get_then_training_renders_and_detail_refresh_use_case_is_used(fake_usecases) -> None:
    fake_usecases.trainings = [_record("train-1", SystemDiscoveryTrainingState.RUNNING)]

    response = app.test_client().get("/system-discovery/training/train-1")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "train-1" in body
    assert "Refresh status" not in body
    assert "Raw status" not in body
    assert "Download results" not in body
    assert "Remove" in body
    assert "/system-discovery/training/train-1/remove" in body
    assert [type(message) for message in fake_usecases.messages] == [
        GetSystemDiscoveryTrainingStatus
    ]


def test_given_training_remove_route_when_get_then_method_not_allowed(fake_usecases) -> None:
    response = app.test_client().get("/system-discovery/training/train-1/remove")

    assert response.status_code == 405


def test_given_training_remove_post_when_successful_then_delegates_and_redirects(fake_usecases) -> None:
    fake_usecases.trainings = [_record("train-1", SystemDiscoveryTrainingState.RUNNING)]

    response = app.test_client().post("/system-discovery/training/train-1/remove")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/system-discovery/trainings")
    assert fake_usecases.trainings == []
    assert [type(message) for message in fake_usecases.messages] == [
        RemoveSystemDiscoveryTrainingQueueEntry
    ]


def test_given_training_without_nlags_x_when_detail_get_then_dash_is_rendered(fake_usecases) -> None:
    fake_usecases.trainings = [
        _record("train-1", SystemDiscoveryTrainingState.RUNNING, nlags_x=None)
    ]

    body = app.test_client().get("/system-discovery/training/train-1").get_data(as_text=True)

    assert "<code>—</code>" in body


def test_given_completed_detail_get_then_evaluate_action_is_rendered_beside_back_action(fake_usecases) -> None:
    fake_usecases.trainings = [_record("train-1", SystemDiscoveryTrainingState.COMPLETED)]

    response = app.test_client().get("/system-discovery/training/train-1")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Back to Training queue" in body
    assert "Evaluate model" in body
    assert "/system-discovery/training/train-1/evaluation" in body
    assert body.index("Back to Training queue") < body.index("Evaluate model")
    assert "Waiting for model evaluation." not in body
    assert "Model evaluation is ready." not in body


def test_given_running_detail_get_then_evaluate_action_is_not_rendered(fake_usecases) -> None:
    fake_usecases.trainings = [_record("train-1", SystemDiscoveryTrainingState.RUNNING)]

    body = app.test_client().get("/system-discovery/training/train-1").get_data(as_text=True)

    assert "Evaluate model" not in body
    assert "Waiting for model evaluation." not in body


def test_given_completed_training_when_evaluation_get_then_use_case_result_is_rendered(fake_usecases) -> None:
    fake_usecases.trainings = [_record("train-1", SystemDiscoveryTrainingState.COMPLETED)]

    response = app.test_client().get("/system-discovery/training/train-1/evaluation")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "System Discovery Model Evaluation" in body
    assert "Save model" in body
    assert "Waiting for visualization." in body
    assert "<div>cdf plot</div>" in body
    assert "Sample size" in body
    assert "NSE confidence interval" in body
    assert "PBIAS interpretation" in body
    assert "Very Good" in body
    assert "100.00%" in body
    assert [type(message) for message in fake_usecases.messages] == [
        OpenSystemDiscoveryTrainingEvaluation
    ]


def test_given_training_evaluation_ready_plots_when_rendered_then_plot_html_is_shown(fake_usecases) -> None:
    fake_usecases.trainings = [_record("train-1", SystemDiscoveryTrainingState.COMPLETED)]
    fake_usecases.results_plot_state = SystemDiscoveryTrainingEvaluationPlotState.READY
    fake_usecases.cdf_plot_state = SystemDiscoveryTrainingEvaluationPlotState.READY

    body = app.test_client().get("/system-discovery/training/train-1/evaluation").get_data(as_text=True)

    assert "<div>cdf plot</div>" in body
    assert "Waiting for visualization." not in body
    assert "Visualization not available" not in body


def test_given_save_model_post_when_successful_then_delegates_and_redirects_to_saved_model(fake_usecases) -> None:
    fake_usecases.trainings = [_record("train-1", SystemDiscoveryTrainingState.COMPLETED)]

    response = app.test_client().post("/system-discovery/training/train-1/evaluation/save")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/system-discovery/models/train-1")
    assert [type(message) for message in fake_usecases.messages] == [
        SaveSystemDiscoveryModel
    ]


def test_given_save_model_route_when_get_then_method_not_allowed(fake_usecases) -> None:
    response = app.test_client().get("/system-discovery/training/train-1/evaluation/save")

    assert response.status_code == 405


def test_given_saved_models_when_list_get_then_saved_models_render(fake_usecases) -> None:
    fake_usecases.saved_models = [_saved_model("train-1")]

    response = app.test_client().get("/system-discovery/models")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "model-train-1" in body
    assert "/system-discovery/models/train-1" in body
    assert "Remove model" in body
    assert "/system-discovery/models/train-1/remove" in body
    assert [type(message) for message in fake_usecases.messages] == [
        ListSavedSystemDiscoveryModels
    ]


def test_given_saved_model_details_when_get_then_model_details_render(fake_usecases) -> None:
    fake_usecases.saved_models = [_saved_model("train-1")]

    response = app.test_client().get("/system-discovery/models/train-1")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "System Discovery Saved Model" in body
    assert "Model name" in body
    assert "model-train-1" in body
    assert "Saved" in body
    assert "Source training ID" in body
    assert "basis" in body
    assert "degree" in body
    assert "nlags-x" in body
    assert "nlags-y" in body
    assert "Back to saved models" in body
    assert "Remove model" in body
    assert "/system-discovery/models/train-1/remove" in body
    assert "Training status" not in body
    assert "Download results" not in body


def test_given_saved_model_remove_route_when_get_then_method_not_allowed(fake_usecases) -> None:
    response = app.test_client().get("/system-discovery/models/train-1/remove")

    assert response.status_code == 405


def test_given_saved_model_remove_post_when_successful_then_delegates_and_redirects(fake_usecases) -> None:
    fake_usecases.saved_models = [_saved_model("train-1")]

    response = app.test_client().post("/system-discovery/models/train-1/remove")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/system-discovery/models")
    assert fake_usecases.saved_models == []
    assert [type(message) for message in fake_usecases.messages] == [
        RemoveSavedSystemDiscoveryModel
    ]


def test_given_saved_model_without_nlags_x_when_list_and_detail_render_then_dash_is_rendered(fake_usecases) -> None:
    fake_usecases.saved_models = [_saved_model("train-1", nlags_x=None)]

    list_body = app.test_client().get("/system-discovery/models").get_data(as_text=True)
    detail_body = app.test_client().get("/system-discovery/models/train-1").get_data(as_text=True)

    assert "<code>—</code>" in list_body
    assert "<code>—</code>" in detail_body


def test_given_saved_model_details_when_rendered_then_no_evaluation_metadata_or_plots_are_shown(fake_usecases) -> None:
    fake_usecases.saved_models = [_saved_model("train-1")]
    fake_usecases.results_plot_state = SystemDiscoveryTrainingEvaluationPlotState.UNAVAILABLE
    fake_usecases.cdf_plot_state = SystemDiscoveryTrainingEvaluationPlotState.UNAVAILABLE

    body = app.test_client().get("/system-discovery/models/train-1").get_data(as_text=True)

    assert "Model name" in body
    assert "Source training ID" in body
    assert "Sample size" not in body
    assert "Model evaluation" not in body
    assert "Visualization not available" not in body
    assert "Waiting for visualization." not in body
    assert "Connection refused" not in body
    assert "localhost" not in body
    assert "Traceback" not in body


def test_given_unavailable_visualization_when_evaluation_get_then_metadata_renders_message_without_raw_errors(fake_usecases) -> None:
    fake_usecases.trainings = [_record("train-1", SystemDiscoveryTrainingState.COMPLETED)]
    fake_usecases.results_plot_state = SystemDiscoveryTrainingEvaluationPlotState.UNAVAILABLE
    fake_usecases.cdf_plot_state = SystemDiscoveryTrainingEvaluationPlotState.UNAVAILABLE

    response = app.test_client().get("/system-discovery/training/train-1/evaluation")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Sample size" in body
    assert "NSE confidence interval" in body
    assert "Visualization not available" in body
    assert "Waiting for visualization." not in body
    assert "Connection refused" not in body
    assert "localhost" not in body
    assert "Traceback" not in body


@pytest.mark.parametrize(
    ("state", "expected", "unexpected"),
    [
        (
            SystemDiscoverySimulationVisualizationState.PENDING,
            "Waiting for visualization.",
            "Visualization not available",
        ),
        (
            SystemDiscoverySimulationVisualizationState.UNAVAILABLE,
            "Visualization not available",
            "Waiting for visualization.",
        ),
        (
            SystemDiscoverySimulationVisualizationState.READY,
            "<div>simulation plot</div>",
            "Visualization not available",
        ),
    ],
)
def test_given_simulation_detail_visualization_state_when_rendered_then_shared_plot_message_is_used(
    fake_usecases,
    state: SystemDiscoverySimulationVisualizationState,
    expected: str,
    unexpected: str,
) -> None:
    fake_usecases.simulations = [_simulation("sim-1")]
    fake_usecases.simulation_visualization_state = state

    response = app.test_client().get("/system-discovery/simulations/sim-1")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert expected in body
    assert unexpected not in body
    assert "Simulation ID" in body
    assert "Horizon" in body
    assert "External control signals" in body
    assert "No" in body
    assert "Connection refused" not in body
    assert "localhost" not in body
    assert "Traceback" not in body


def test_system_discovery_plot_rendering_uses_shared_partial() -> None:
    template_root = "src/services/front/templates"

    with open(f"{template_root}/_system_discovery_evaluation_content.html", encoding="utf-8") as file:
        evaluation_template = file.read()
    with open(f"{template_root}/system_discovery_simulation_detail.html", encoding="utf-8") as file:
        simulation_template = file.read()
    with open(f"{template_root}/_system_discovery_plot.html", encoding="utf-8") as file:
        plot_template = file.read()

    assert evaluation_template.count('_system_discovery_plot.html') == 3
    assert simulation_template.count('_system_discovery_plot.html') == 1
    assert plot_template.count("Visualization not available") == 1


def test_given_simulations_when_list_and_detail_render_then_external_control_indicator_is_shown(fake_usecases) -> None:
    fake_usecases.simulations = [
        _simulation("sim-1", uses_external_control_signals=True),
        _simulation("sim-2", uses_external_control_signals=False),
    ]

    list_body = app.test_client().get("/system-discovery/simulations").get_data(as_text=True)
    detail_body = app.test_client().get("/system-discovery/simulations/sim-1").get_data(as_text=True)

    assert "External control signals" in list_body
    assert "Yes" in list_body
    assert "No" in list_body
    assert "External control signals" in detail_body
    assert "Yes" in detail_body
    assert "controls.zip" not in list_body
    assert "data.csv" not in list_body
    assert "time;u" not in detail_body


def test_given_running_training_when_evaluation_get_then_page_rejects_access(fake_usecases) -> None:
    fake_usecases.trainings = [_record("train-1", SystemDiscoveryTrainingState.RUNNING)]

    response = app.test_client().get("/system-discovery/training/train-1/evaluation")

    body = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "Model evaluation is available only for completed trainings." in body


def test_given_removed_user_actions_when_called_then_routes_return_404(fake_usecases) -> None:
    client = app.test_client()

    assert client.post("/system-discovery/trainings/refresh").status_code == 404
    assert client.post("/system-discovery/training/train-1/refresh").status_code == 404
    assert client.get("/system-discovery/training/train-1/results").status_code == 404


def test_given_training_pages_when_rendered_then_dates_are_iso_with_timezone(fake_usecases) -> None:
    fake_usecases.trainings = [_record("train-1", SystemDiscoveryTrainingState.RUNNING)]

    queue_body = app.test_client().get("/system-discovery/trainings").get_data(as_text=True)
    detail_body = app.test_client().get("/system-discovery/training/train-1").get_data(as_text=True)

    assert "2026-06-28T12:00:00Z" in queue_body
    assert "2026-06-28T12:05:00Z" in detail_body
    assert "data-utc-datetime" in queue_body
    assert "data-utc-datetime" in detail_body
    assert ".000000" not in queue_body
    assert ".000000" not in detail_body


def test_given_missing_updated_at_when_queue_renders_then_dash_is_shown(fake_usecases) -> None:
    fake_usecases.trainings = [
        _record("train-1", SystemDiscoveryTrainingState.RUNNING, updated_at=None)
    ]

    body = app.test_client().get("/system-discovery/trainings").get_data(as_text=True)

    assert "—" in body


def test_given_templates_when_rendered_then_no_polling_javascript_is_present(fake_usecases) -> None:
    fake_usecases.trainings = [_record("train-1", SystemDiscoveryTrainingState.COMPLETED)]

    queue_body = app.test_client().get("/system-discovery/trainings").get_data(as_text=True)
    detail_body = app.test_client().get("/system-discovery/training/train-1").get_data(as_text=True)
    evaluation_body = app.test_client().get(
        "/system-discovery/training/train-1/evaluation"
    ).get_data(as_text=True)

    for token in ("fetch(", "setInterval", "setTimeout"):
        assert token not in queue_body
        assert token not in detail_body
        assert token not in evaluation_body


def test_given_sidebar_when_rendered_then_training_queue_link_is_enabled(fake_usecases) -> None:
    body = app.test_client().get("/").get_data(as_text=True)

    assert 'href="/system-discovery/trainings"' in body
    assert "Training queue" in body


def _record(
    training_id: str,
    state: SystemDiscoveryTrainingState,
    updated_at=datetime(2026, 6, 28, 12, 5, tzinfo=timezone.utc),
    nlags_x=((1, 2),),
) -> SystemDiscoveryTrainingRecord:
    return SystemDiscoveryTrainingRecord(
        training_id=training_id,
        created_at=datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc),
        updated_at=updated_at,
        state=state,
        raw_status=state.value,
        training_status="training",
        evaluation_status="evaluation",
        error=None,
        basis="Polynomial",
        degree=2,
        model="narmax",
        nlags_x=nlags_x,
        nlags_y=1,
    )


def _metadata() -> SystemDiscoveryTrainingEvaluationMetadata:
    return SystemDiscoveryTrainingEvaluationMetadata(
        analysis="Model evaluation based on 50 samples.",
        sample_size="50",
        nse=SystemDiscoveryEvaluationMetric(
            value="0.9697",
            confidence_interval="0.9479 - 0.9815",
            confidence_level="95.00%",
            confidence_method="BCa",
        ),
        rmse=SystemDiscoveryEvaluationMetric(
            value="0.1273",
            confidence_interval="0.1071 - 0.1555",
            confidence_level="95.00%",
            confidence_method="BCa",
        ),
        nrmse=SystemDiscoveryEvaluationMetric(value="17.4029"),
        pbias=SystemDiscoveryEvaluationMetric(value="0.3608", note="Overestimation"),
        p_value="0.0000",
        categories=[
            SystemDiscoveryEvaluationCategory("Very Good", "100.00%"),
            SystemDiscoveryEvaluationCategory("Good", "0.00%"),
            SystemDiscoveryEvaluationCategory("Acceptable", "0.00%"),
            SystemDiscoveryEvaluationCategory("Unsatisfactory", "0.00%"),
        ],
    )


def _saved_model(
    model_id: str,
    nlags_x=((1, 2),),
) -> SystemDiscoverySavedModelRecord:
    return SystemDiscoverySavedModelRecord(
        model_id=model_id,
        source_training_id=model_id,
        model_name=f"model-{model_id}",
        saved_at=datetime(2026, 6, 28, 12, 10, tzinfo=timezone.utc),
        nlags_x=nlags_x,
        nlags_y=1,
        basis="Polynomial",
        degree=2,
    )


def _simulation(
    simulation_id: str,
    *,
    uses_external_control_signals: bool = False,
) -> SystemDiscoverySimulationRecord:
    return SystemDiscoverySimulationRecord(
        simulation_id=simulation_id,
        source_model_id="model-1",
        source_model_name="model-train-1",
        created_at=datetime(2026, 6, 28, 12, 15, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 28, 12, 20, tzinfo=timezone.utc),
        state=SystemDiscoverySimulationState.COMPLETED,
        raw_status="completed",
        error=None,
        horizon=12,
        initial_conditions=(1.0, 2.0),
        uses_external_control_signals=uses_external_control_signals,
        aistor_object_key=f"stored/{simulation_id}.zip",
        aistor_uploaded_at=datetime(2026, 6, 28, 12, 21, tzinfo=timezone.utc),
        visualization_plot_id="plot-1",
    )
