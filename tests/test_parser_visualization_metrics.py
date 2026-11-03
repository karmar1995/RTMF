from __future__ import annotations

from functools import partial
from pathlib import Path

from flask import Flask, render_template

from adapters.parser_rest_adapter.parser_rest_adapter import RestParserAdapter
from adapters.parser_rest_adapter.rest_client import (
    ParserRecognitionResponse,
    _parse_recognition_result,
)
from services.use_case.bus import InProcessBus
from services.use_case.handlers.visualizations import handle_visualize_disaster_stages
from services.use_case.utils.plot_mapping import ParserRecognitionMapping, PlotMapping
from use_case_contracts.dtos import (
    DisasterStageMetrics,
    DisasterStageRecognitionResult,
    JobVisualizationRenderedSeries,
    JobVisualizationResult,
)
from use_case_contracts.messages import VisualizeDisasterStages, VisualizationSeries


def test_parser_rest_response_maps_complete_metrics_to_contract_dto() -> None:
    adapter = RestParserAdapter(
        _Client(
            ParserRecognitionResponse(
                phases=[(0.0, 10.0, "normal"), (10.0, 20.0, "shock")],
                metrics={
                    "recovery_time_in_steps": 7.0,
                    "shock_time_in_steps": 3.0,
                    "shock_drop_pct_ref_normal": 12.345,
                    "shock_drop_pct_ref_baseline": 9.876,
                    "shock_stage_avg": 2.25,
                    "shock_stage_std": 0.5,
                },
            )
        )
    )

    result = adapter.get_disaster_stage_recognition("recognition-id")

    assert result.stages == [("normal", 0.0, 10.0), ("shock", 10.0, 20.0)]
    assert result.metrics == DisasterStageMetrics(
        recovery_time_in_steps=7.0,
        shock_time_in_steps=3.0,
        shock_drop_pct_ref_normal=12.345,
        shock_drop_pct_ref_baseline=9.876,
        shock_stage_avg=2.25,
        shock_stage_std=0.5,
    )


def test_parser_rest_response_preserves_zero_metrics() -> None:
    payload = _parse_recognition_result(
        {
            "phases": [[0, 1, "shock"]],
            "metrics": {
                "recovery_time_in_steps": 0,
                "shock_time_in_steps": 0,
                "shock_drop_pct_ref_normal": 0,
                "shock_drop_pct_ref_baseline": 0,
                "shock_stage_avg": 0,
                "shock_stage_std": 0,
            },
        }
    )

    assert payload.metrics == {
        "recovery_time_in_steps": 0.0,
        "shock_time_in_steps": 0.0,
        "shock_drop_pct_ref_normal": 0.0,
        "shock_drop_pct_ref_baseline": 0.0,
        "shock_stage_avg": 0.0,
        "shock_stage_std": 0.0,
    }


def test_parser_rest_response_accepts_missing_metrics_for_backward_compatibility() -> (
    None
):
    payload = _parse_recognition_result({"phases": [[0, 1, "normal"]]})

    assert payload.phases == [(0.0, 1.0, "normal")]
    assert payload.metrics is None


def test_parser_rest_response_accepts_null_metrics() -> None:
    payload = _parse_recognition_result({"phases": [[0, 1, "normal"]], "metrics": None})

    assert payload.phases == [(0.0, 1.0, "normal")]
    assert payload.metrics is None


def test_parser_rest_response_accepts_missing_phases_as_not_ready_data() -> None:
    payload = _parse_recognition_result({})

    assert payload.phases == []
    assert payload.metrics is None


def test_parser_rest_response_accepts_partially_missing_metric_fields() -> None:
    payload = _parse_recognition_result(
        {
            "phases": [[0, 1, "shock"]],
            "metrics": {
                "shock_time_in_steps": 4,
                "shock_drop_pct_ref_baseline": 0,
            },
        }
    )

    assert payload.metrics is not None
    assert payload.metrics["shock_time_in_steps"] == 4.0
    assert payload.metrics["shock_drop_pct_ref_baseline"] == 0.0
    assert payload.metrics["recovery_time_in_steps"] is None


def test_disaster_stage_metrics_reach_visualization_result() -> None:
    metrics = DisasterStageMetrics(
        recovery_time_in_steps=7,
        shock_time_in_steps=3,
        shock_drop_pct_ref_normal=12.34,
        shock_drop_pct_ref_baseline=8.9,
        shock_stage_avg=2.2,
        shock_stage_std=0.4,
    )

    result = handle_visualize_disaster_stages(
        VisualizeDisasterStages(
            job_id="job-1",
            series=VisualizationSeries(
                x="time",
                y="result_x",
                statistic="none",
                constants={"constant_param": "A"},
            ),
            plot_type="line",
        ),
        analytics=_Analytics(),
        visualization=_Visualization(),
        parser=_Parser(metrics),
        plotsIds=_Mapping(),
        parserRecognitionIds=_RecognitionMapping(),
    )

    assert result.disaster_stage_metrics == metrics


def test_first_visualization_request_when_series_data_is_not_ready_returns_waiting_result() -> (
    None
):
    metrics = DisasterStageMetrics(shock_time_in_steps=3)
    analytics = _Analytics(statuses=["preparing", "ok"])
    parser = _Parser(metrics)
    bus = _visualization_bus(analytics=analytics, parser=parser)

    first = bus.handle(_message())
    second = bus.handle(_message())

    assert first.plot_html is None
    assert first.disaster_stage_metrics is None
    assert "Waiting for the plot" in first.waiting_message
    assert parser.recognize_calls == 1
    assert second.plot_html == "<div>plot</div>"
    assert second.disaster_stage_metrics == metrics


def test_visualization_request_when_parser_recognition_is_not_ready_returns_waiting_result() -> (
    None
):
    metrics = DisasterStageMetrics(shock_time_in_steps=3)
    parser = _ControllableParser(metrics=metrics, completed=False)
    bus = _visualization_bus(parser=parser)

    first = bus.handle(_message())
    parser.completed = True
    second = bus.handle(_message())

    assert first.plot_html is None
    assert first.disaster_stage_metrics is None
    assert "Waiting for the disaster stages recognition" in first.waiting_message
    assert parser.recognize_calls == 1
    assert second.plot_html == "<div>plot</div>"
    assert second.disaster_stage_metrics == metrics


def test_visualization_result_preserves_zero_parser_metrics() -> None:
    metrics = DisasterStageMetrics(
        recovery_time_in_steps=0,
        shock_time_in_steps=0,
        shock_drop_pct_ref_normal=0,
        shock_drop_pct_ref_baseline=0,
        shock_stage_avg=0,
        shock_stage_std=0,
    )

    result = _visualization_bus(parser=_Parser(metrics)).handle(_message())

    assert result.disaster_stage_metrics == metrics


def test_visualization_result_accepts_missing_parser_metrics() -> None:
    result = _visualization_bus(parser=_Parser(None)).handle(_message())

    assert result.plot_html == "<div>plot</div>"
    assert result.disaster_stage_metrics is None


def test_visualization_result_accepts_empty_parser_stage_data() -> None:
    result = _visualization_bus(parser=_Parser(metrics=None, stages=[])).handle(
        _message()
    )

    assert result.plot_html == "<div>plot</div>"
    assert result.disaster_stage_metrics is None


def test_parser_metrics_template_formats_units_and_precision() -> None:
    html = _render_job_plot(
        DisasterStageMetrics(
            recovery_time_in_steps=7,
            shock_time_in_steps=3,
            shock_drop_pct_ref_normal=12.345,
            shock_drop_pct_ref_baseline=8.9,
            shock_stage_avg=2.234,
            shock_stage_std=0.456,
        )
    )

    assert "Disaster-stage metrics" in html
    assert "3 steps" in html
    assert "7 steps" in html
    assert "12.35%" in html
    assert "8.90%" in html
    assert "2.23" in html
    assert "0.46" in html


def test_parser_metrics_template_formats_zero_values() -> None:
    html = _render_job_plot(
        DisasterStageMetrics(
            recovery_time_in_steps=0,
            shock_time_in_steps=0,
            shock_drop_pct_ref_normal=0,
            shock_drop_pct_ref_baseline=0,
            shock_stage_avg=0,
            shock_stage_std=0,
        )
    )

    assert "0 steps" in html
    assert "0.00%" in html
    assert "0.00" in html


def test_parser_metrics_template_renders_missing_values_as_dash() -> None:
    assert "—" in _render_job_plot(None)

    html = _render_job_plot(
        DisasterStageMetrics(
            shock_time_in_steps=4,
            shock_drop_pct_ref_baseline=0,
        )
    )

    assert "4 steps" in html
    assert "0.00%" in html
    assert html.count("—") >= 4


class _Client:
    def __init__(self, response: ParserRecognitionResponse) -> None:
        self.response = response

    def recognize_stages(self, time_series_csv_bytes: bytes) -> str:
        return "recognition-id"

    def get_recognition_status(self, recognition_id: str) -> str:
        return "COMPLETED"

    def get_disaster_stage_recognition(
        self, recognition_id: str
    ) -> ParserRecognitionResponse:
        return self.response


class _Parser:
    def __init__(
        self,
        metrics: DisasterStageMetrics | None,
        stages: list[tuple[str, float, float]] | None = None,
    ) -> None:
        self.metrics = metrics
        self.stages = (
            stages
            if stages is not None
            else [("normal", 0.0, 10.0), ("shock", 10.0, 20.0)]
        )
        self.recognize_calls = 0

    def recognize_stages(self, time_series_csv_bytes: bytes) -> str:
        self.recognize_calls += 1
        return "recognition-id"

    def get_recognition_status(self, recognition_id: str) -> str:
        return "COMPLETED"

    def get_disaster_stage_recognition(
        self, recognition_id: str
    ) -> DisasterStageRecognitionResult:
        return DisasterStageRecognitionResult(
            stages=self.stages,
            metrics=self.metrics,
        )

    def get_disaster_stages(
        self, recognition_id: str
    ) -> list[tuple[str, float, float]]:
        return self.get_disaster_stage_recognition(recognition_id).stages

    def recognition_finished_successfully(self, recognition_id: str) -> bool:
        return True


class _ControllableParser(_Parser):
    def __init__(self, metrics: DisasterStageMetrics | None, completed: bool) -> None:
        super().__init__(metrics)
        self.completed = completed

    def get_recognition_status(self, recognition_id: str) -> str:
        return "COMPLETED" if self.completed else "RUNNING"

    def recognition_finished_successfully(self, recognition_id: str) -> bool:
        return self.completed


class _Analytics:
    def __init__(self, statuses: list[str] | None = None) -> None:
        self.statuses = list(statuses or ["ok"])

    def prepare_series(self, **kwargs) -> str:
        return "series-id"

    def get_series_status(self, series_id: str) -> str:
        if len(self.statuses) > 1:
            return self.statuses.pop(0)
        return self.statuses[0]

    def download_series(self, series_id: str) -> bytes:
        return b"zip-bytes"

    def merge_series(self, seriesIds: list[str]) -> str:
        return seriesIds[0]


class _Visualization:
    def render_plot(self, zip_csv_bytes: bytes, plot_spec) -> str:
        return "plot-id"

    def get_plot_status(self, plot_id: str) -> str:
        return "done"

    def get_plot_html(self, plot_id: str) -> str:
        return "<div>plot</div>"


class _Mapping:
    def get(self, series_id: str, plot_spec):
        return None

    def store(self, series_id: str, plot_spec, plot_id: str) -> None:
        pass


class _RecognitionMapping:
    def get(self, series_id: str):
        return None

    def store(self, series_id: str, recognition_id: str) -> None:
        pass


def _visualization_bus(
    analytics: _Analytics | None = None,
    visualization: _Visualization | None = None,
    parser: _Parser | None = None,
) -> InProcessBus:
    bus = InProcessBus()
    bus.register(
        VisualizeDisasterStages,
        partial(
            handle_visualize_disaster_stages,
            analytics=analytics or _Analytics(),
            visualization=visualization or _Visualization(),
            parser=parser or _Parser(None),
            plotsIds=PlotMapping(),
            parserRecognitionIds=ParserRecognitionMapping(),
        ),
    )
    return bus


def _message() -> VisualizeDisasterStages:
    return VisualizeDisasterStages(
        job_id="job-1",
        series=VisualizationSeries(
            x="time",
            y="result_x",
            statistic="none",
            constants={"constant_param": "A"},
        ),
        plot_type="line",
    )


def _render_job_plot(metrics: DisasterStageMetrics | None) -> str:
    app = Flask(
        __name__,
        template_folder=str(
            Path(__file__).resolve().parents[1]
            / "src"
            / "services"
            / "front"
            / "templates"
        ),
    )

    @app.context_processor
    def _sidebar():
        return {"sidebar_groups": ()}

    @app.post("/logout", endpoint="onAuthLogout")
    def _logout():
        return ""

    with app.test_request_context("/"):
        return render_template(
            "job_plot.html",
            active_page="visualization",
            group_id="job-1",
            job_id="job-1",
            visualization_mode="parser",
            visualization_title="Parser Visualization",
            result=JobVisualizationResult(
                series=[
                    JobVisualizationRenderedSeries(
                        x="time",
                        y="result_x",
                        statistic="none",
                        constant_params={},
                    )
                ],
                plot_type="line",
                plot_html="<div>plot</div>",
                waiting_message="",
                disaster_stage_metrics=metrics,
            ),
        )
