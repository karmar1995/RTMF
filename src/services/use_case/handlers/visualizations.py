from __future__ import annotations

import csv
import io
import logging
import zipfile
import time
from typing import List, Tuple
from urllib.parse import urlparse

from services.use_case.utils.plot_mapping import ParserRecognitionMapping, PlotMapping
from use_case_contracts.ports import SimulatorRepository, JobsRepositoryReaderPort, AnalyticsPort, \
    ParserPort, VisualizationPort
from use_case_contracts.dtos import (
    MonteCarloFilteringResult,
    MonteCarloFilteringPlotResult,
    MonteCarloFilteringPlotState,
    MonteCarloFilteringRun,
    PlotSpec,
    PlotLine,
    PlotArea,
    PlotAnnotation,
    JobVisualizationHeader,
    JobVisualizationConstants,
    JobVisualizationResult,
    JobVisualizationRenderedSeries,
    JobVisualizationStatus,
    DisasterStageMetrics,
)
from use_case_contracts.errors import (
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from use_case_contracts.messages import (
    VisualizeJob,
    BeginJobVisualization,
    GetMonteCarloFilteringPlotState,
    GetVisualizationConstantParams,
    GetJobRepetitions,
    GetJobVisualizationStatus,
    RetryJobResults,
    VisualizeDisasterStages,
    VisualizeMonteCarloFiltering,
)

logger = logging.getLogger(__name__)


def handle_begin_job_visualization(
    message: BeginJobVisualization,
    jobs_repo: JobsRepositoryReaderPort,
    simulators_repo: SimulatorRepository,
    analytics: AnalyticsPort,
    visualization: VisualizationPort,
) -> JobVisualizationHeader:
    job_id = message.job_id

    target, input_params, output_params = _resolve_visualization_target_and_params(
        job_id, jobs_repo, simulators_repo
    )
    analytics.initialize_job(job_id,
                             target.job_root_url,
                             target.result_urls,
                             input_params,
                             output_params)

    status = analytics.job_results_status(message.job_id)
    constants = None
    if status == 'ok':
        constants = JobVisualizationConstants(analytics.input_parameters_values(message.job_id))

    return JobVisualizationHeader(
        warning='',
        input_params=input_params,
        output_params=output_params,
        constants=constants,
        plot_types=visualization.supported_plot_types(),
        results_status=status,
        results_error=analytics.job_results_error(message.job_id) if status == "error" else None,
    )


def handle_retry_job_results(
    message: RetryJobResults,
    jobs_repo: JobsRepositoryReaderPort,
    simulators_repo: SimulatorRepository,
    analytics: AnalyticsPort,
) -> None:
    """Explicitly rebuild job results after a failure, then normalize via the
    next BeginJobVisualization request (the config page reload)."""
    job_id = message.job_id
    target, input_params, output_params = _resolve_visualization_target_and_params(
        job_id, jobs_repo, simulators_repo
    )
    analytics.retry_job_results(job_id,
                                target.job_root_url,
                                target.result_urls,
                                input_params,
                                output_params)


def _resolve_visualization_target_and_params(
    job_id: str,
    jobs_repo: JobsRepositoryReaderPort,
    simulators_repo: SimulatorRepository,
):
    """Resolve the visualization target and its parameter lists, shared by the
    begin and retry handlers so both feed analytics the same job description."""
    # Resolves either a job id or an evaluation id; an evaluation is presented
    # as one big job whose results are every artifact its jobs produced.
    target = jobs_repo.resolve_visualization_target(job_id)
    simulator = simulators_repo.get(target.simulator_id)
    if simulator is None:
        raise NotFoundError(f"Simulator '{target.simulator_id}' not found")

    input_params = _extract_input_params(simulator.input_params)
    output_params = _extract_output_params(simulator.output_params)
    input_params.append(('time', 'float'))

    if not input_params:
        raise ValidationError("Simulator has no input parameters")
    if not output_params:
        raise ValidationError("Simulator has no output parameters")
    return target, input_params, output_params


def handle_job_visualization(
    message: VisualizeJob,
    analytics: AnalyticsPort,
    visualization: VisualizationPort,
    plotsIds: PlotMapping
) -> JobVisualizationResult:
    job_id = message.job_id
    series = message.series
    plot_type = message.plot_type
    return _perform_visualization(
        job_id=job_id,
        series=series,
        plot_type=plot_type,
        analytics=analytics,
        visualization=visualization,
        parser=None,
        plotsIds=plotsIds)


def handle_visualize_disaster_stages(
    message: VisualizeDisasterStages,
    analytics: AnalyticsPort,
    visualization: VisualizationPort,
    parser: ParserPort,
    plotsIds: PlotMapping,
    parserRecognitionIds: ParserRecognitionMapping
) -> JobVisualizationResult:
    job_id = message.job_id
    series = message.series
    plot_type = message.plot_type
    return _perform_visualization(
        job_id=job_id,
        series=[series],
        plot_type=plot_type,
        analytics=analytics,
        visualization=visualization,
        parser=parser,
        plotsIds=plotsIds,
        parserRecognitionIds=parserRecognitionIds)


def handle_get_monte_carlo_filtering_plot_state(
    message: GetMonteCarloFilteringPlotState,
    visualization: VisualizationPort,
) -> MonteCarloFilteringPlotState:
    plot_status = visualization.get_plot_status(message.plot_id)
    plot_html = (
        visualization.get_plot_html(message.plot_id)
        if plot_status == "done"
        else None
    )
    scatter_plot_status = None
    scatter_plot_html = None
    if message.scatter_plot_id:
        scatter_plot_status = visualization.get_plot_status(message.scatter_plot_id)
        if scatter_plot_status == "done":
            scatter_plot_html = visualization.get_plot_html(
                message.scatter_plot_id
            )
    return MonteCarloFilteringPlotState(
        plot_status=plot_status,
        plot_html=plot_html,
        scatter_plot_status=scatter_plot_status,
        scatter_plot_html=scatter_plot_html,
    )


def handle_visualize_monte_carlo_filtering(
    message: VisualizeMonteCarloFiltering,
    jobs_repo: JobsRepositoryReaderPort,
    simulators_repo: SimulatorRepository,
    analytics: AnalyticsPort,
    visualization: VisualizationPort,
) -> MonteCarloFilteringPlotResult:
    job_id = message.job_id

    try:
        target = jobs_repo.resolve_visualization_target(job_id)
        simulator = simulators_repo.get(target.simulator_id)
        if simulator is None:
            raise NotFoundError(f"Simulator '{target.simulator_id}' not found")

        input_params = _extract_input_params(simulator.input_params)
        output_params = _extract_output_params(simulator.output_params)
        if not input_params:
            raise ValidationError("Simulator has no input parameters")
        if not output_params:
            raise ValidationError("Simulator has no output parameters")
        input_names = {name for name, _ in input_params}
        output_names = {name for name, _ in output_params}
        if message.output_column not in output_names:
            raise ValidationError(
                f"Output '{message.output_column}' is not an output parameter of this simulator"
            )
        if message.direction not in ("greater", "less"):
            raise ValidationError("direction must be either 'greater' or 'less'")
        if message.threshold is None:
            raise ValidationError("threshold must be provided")

        scatter_x = message.scatter_x or input_params[0][0]
        scatter_y = message.scatter_y or message.output_column
        if scatter_x not in input_names:
            raise ValidationError(
                f"Scatter X '{scatter_x}' is not an input parameter of this simulator"
            )
        if scatter_y not in output_names:
            raise ValidationError(
                f"Scatter Y '{scatter_y}' is not an output parameter of this simulator"
            )

        results_urls = [ref.url for ref in target.result_urls]
        if not results_urls:
            raise ValidationError("Job has no results to analyze")

        output_aggregations = (
            {scatter_y: message.scatter_aggregation}
            if message.scatter_aggregation
            else None
        )
        result = analytics.analyze_monte_carlo_filtering(
            results_urls=results_urls,
            problem={"names": [name for name, _ in input_params]},
            output_column=message.output_column,
            threshold=message.threshold,
            direction=message.direction,
            aggregation=message.aggregation,
            output_aggregations=output_aggregations,
            run_output_columns=[scatter_y],
        )

        ecdf_id, ecdf_status, ecdf_html, ecdf_waiting = _render_plot(
            visualization=visualization,
            zip_csv_bytes=_ecdf_csv_zip(result),
            plot_spec=PlotSpec(
                plot_type="ECDF",
                vertical_lines=[],
                areas=[],
                annotations=[],
                diagonal_lines=[],
            ),
        )
        scatter_id, scatter_status, scatter_html, _ = _render_plot(
            visualization=visualization,
            zip_csv_bytes=_scatter_csv_zip(result, scatter_x, scatter_y),
            plot_spec=_scatter_plot_spec(scatter_x, scatter_y),
        )

        return MonteCarloFilteringPlotResult(
            plot_type="ECDF",
            plot_html=ecdf_html,
            waiting_message=ecdf_waiting,
            series=[],
            monte_carlo_statistics=result.parameters,
            plot_id=ecdf_id,
            plot_status=ecdf_status,
            behavioural_count=result.behavioural_count,
            non_behavioural_count=result.non_behavioural_count,
            scatter_plot_id=scatter_id,
            scatter_plot_status=scatter_status,
            scatter_plot_html=scatter_html,
            scatter_x=scatter_x,
            scatter_y=scatter_y,
            scatter_input_options=list(input_params),
            scatter_output_options=list(output_params),
            simulator_id=target.simulator_id,
            evaluation_output=result.output_column,
            evaluation_aggregation=message.aggregation,
            behavioural_input_ranges=_behavioural_input_ranges(result.runs),
        )
    except (
        NotFoundError,
        ValidationError,
        ExternalServiceError,
        AuthenticationError,
    ) as exc:
        return MonteCarloFilteringPlotResult(
            series=[],
            plot_type="ECDF",
            plot_html=None,
            waiting_message=str(exc),
        )


def _render_plot(
    *,
    zip_csv_bytes: bytes,
    plot_spec: PlotSpec,
    visualization: VisualizationPort,
) -> tuple[str, str, str | None, str]:
    plot_id = visualization.render_plot(
        zip_csv_bytes=zip_csv_bytes, plot_spec=plot_spec
    )
    status = visualization.get_plot_status(plot_id)
    html = None

    if status == "done":
        html = visualization.get_plot_html(plot_id)
        waiting_message = "Plot generated."
    elif status == "error":
        waiting_message = "Plot generation failed."
    else:
        waiting_message = f"Waiting for the plot, current status: {status}"

    return plot_id, status, html, waiting_message


def _scatter_plot_spec(scatter_x: str, scatter_y: str) -> PlotSpec:
    return PlotSpec(
        plot_type="Scatter",
        vertical_lines=[],
        areas=[],
        annotations=[],
        diagonal_lines=[],
        xaxis_title=scatter_x,
        yaxis_title=scatter_y,
        series_hover_templates={
            "Behavioural": (
                f"<b>Behavioural</b><br>{scatter_x}: %{{x:.2f}}"
                f"<br>{scatter_y}: %{{y:.2f}}<extra></extra>"
            ),
            "Non-behavioural": (
                f"<b>Non-behavioural</b><br>{scatter_x}: %{{x:.2f}}"
                f"<br>{scatter_y}: %{{y:.2f}}<extra></extra>"
            ),
        },
        series_styles={
            "Behavioural": {
                "name": "Behavioural",
                "color": "#2563eb",
                "opacity": 0.7,
            },
            "Non-behavioural": {
                "name": "Non-behavioural",
                "color": "#dc2626",
                "opacity": 0.7,
            },
        },
    )


def _scatter_csv_zip(
    result: MonteCarloFilteringResult,
    scatter_x: str,
    scatter_y: str,
) -> bytes:
    # Non-behavioural first: the plot service adds one trace per y-column, in order, and
    # later traces are drawn on top. Keeping Behavioural last puts the blue points over
    # the red ones where they overlap.
    headers = [scatter_x, "Non-behavioural", "Behavioural"]
    rows: list[tuple] = []
    for run in result.runs:
        x_value = run.parameters.get(scatter_x)
        y_value = run.outputs.get(scatter_y)
        if x_value is None or y_value is None:
            continue
        if run.behavioural:
            rows.append((x_value, "", y_value))
        else:
            rows.append((x_value, y_value, ""))
    return _csv_zip_bytes(headers, rows, filename="mcf_scatter.csv")


def _ecdf_csv_zip(result: MonteCarloFilteringResult) -> bytes:
    headers = ["parameter", "group", "x", "cdf", "d_statistic", "reject_h0"]
    rows: list[tuple] = []
    for statistic in result.parameters:
        for x, y in zip(statistic.behavioural_ecdf_x, statistic.behavioural_ecdf_y):
            rows.append(
                (
                    statistic.parameter,
                    "behavioural",
                    x,
                    y,
                    statistic.d_statistic,
                    int(statistic.reject_h0),
                )
            )
        for x, y in zip(
            statistic.non_behavioural_ecdf_x, statistic.non_behavioural_ecdf_y
        ):
            rows.append(
                (
                    statistic.parameter,
                    "non_behavioural",
                    x,
                    y,
                    statistic.d_statistic,
                    int(statistic.reject_h0),
                )
            )
    return _csv_zip_bytes(headers, rows, filename="mcf_ecdf.csv")


def _behavioural_input_ranges(
    runs: list[MonteCarloFilteringRun],
) -> dict[str, list[float]]:
    """Min/max of each input parameter across the behavioural runs only.

    Every parameter keeps a range even when degenerate (min == max): the
    evaluation form then lets the user widen a held-constant input rather than
    leaving it blank. Used to prefill /evaluation/run from the plot page.
    """
    ranges: dict[str, list[float]] = {}
    for run in runs:
        if not run.behavioural:
            continue
        for name, value in run.parameters.items():
            current = ranges.get(name)
            if current is None:
                ranges[name] = [value, value]
            else:
                if value < current[0]:
                    current[0] = value
                if value > current[1]:
                    current[1] = value
    return ranges


def _perform_visualization(
    job_id,
    series,
    plot_type,
    analytics: AnalyticsPort,
    visualization: VisualizationPort,
    parser: ParserPort | None,
    plotsIds: PlotMapping,
    parserRecognitionIds: ParserRecognitionMapping | None = None,
):
    if not series:
        raise ValidationError("No visualization series provided")

    series_ids = []
    rendered_series_data = []
    parser_data: list[tuple[str, float, float]] = []
    disaster_stage_metrics: DisasterStageMetrics | None = None
    waiting_message = "Plot is being generated. This page will update automatically."
    for series in series:
        x = series.x
        y = series.y
        statistic = series.statistic
        try:
            constants_for_analytics = [
                (key[len("constant_") :], value)
                for key, value in series.constants.items()
            ]
            series_id = analytics.prepare_series(
                job_id=job_id,
                x_param=x,
                y_param=y,
                constants=constants_for_analytics,
                statistic=statistic,
            )
            series_ids.append(series_id)
            rendered_series_data.append(
                JobVisualizationRenderedSeries(
                    x=x, y=y, statistic=statistic, constant_params=series.constants
                )
            )
        except Exception as e:
            return JobVisualizationResult(
                series=[], plot_type=plot_type, plot_html=None, waiting_message=str(e),
                plot_status="error",
            )

    if len(series_ids) > 1:
        series_id_for_download = analytics.merge_series(series_ids)
    else:
        series_id_for_download = series_ids[0]

    html_status = "Data series preparation"
    status = analytics.get_series_status(series_id_for_download)
    if status == "ok":
        zip_bytes = analytics.download_series(series_id=series_id_for_download)
        if len(rendered_series_data) > 1:
            zip_bytes = _rename_merged_series_headers(zip_bytes, rendered_series_data)
        if parser:
            recognition_id = (
                parserRecognitionIds.get(series_id_for_download)
                if parserRecognitionIds is not None
                else None
            )
            if recognition_id is None:
                recognition_id = parser.recognize_stages(zip_bytes)
                if parserRecognitionIds is not None:
                    parserRecognitionIds.store(series_id_for_download, recognition_id)
            if not parser.recognition_finished_successfully(recognition_id):
                recognition_status = parser.get_recognition_status(recognition_id)
                logger.info(
                    "Disaster stage data unavailable",
                    extra={
                        "job_id": job_id,
                        "series_id": series_id_for_download,
                        "recognition_id": recognition_id,
                        "recognition_status": recognition_status,
                    },
                )
                return JobVisualizationResult(
                    series=rendered_series_data,
                    plot_type=plot_type,
                    plot_html=None,
                    waiting_message=(
                        "Waiting for the disaster stages recognition, "
                        f"current status: {recognition_status}"
                    ),
                    disaster_stage_metrics=None,
                )
            recognition_result = parser.get_disaster_stage_recognition(recognition_id)
            parser_data = recognition_result.stages
            disaster_stage_metrics = recognition_result.metrics
            if disaster_stage_metrics is None:
                logger.info(
                    "Disaster stage parser response without metrics",
                    extra={
                        "job_id": job_id,
                        "series_id": series_id_for_download,
                        "recognition_id": recognition_id,
                        "stage_count": len(parser_data),
                    },
                )
            else:
                logger.info(
                    "Disaster stage parser response with metrics",
                    extra={
                        "job_id": job_id,
                        "series_id": series_id_for_download,
                        "recognition_id": recognition_id,
                        "stage_count": len(parser_data),
                    },
                )

        plot_spec = PlotSpec(
            plot_type=plot_type,
            vertical_lines=_parser_data_to_plot_lines(parser_data),
            areas=_parser_data_to_areas(parser_data),
            annotations=_parser_data_to_annotations(parser_data),
            diagonal_lines=[],
            xaxis_title=rendered_series_data[0].x if len(rendered_series_data) > 1 else None,
            yaxis_title=rendered_series_data[0].y if len(rendered_series_data) > 1 else None,
        )

        html_id = plotsIds.get(series_id_for_download, plot_spec)
        if html_id is None:
            html_id = visualization.render_plot(
                zip_csv_bytes=zip_bytes, plot_spec=plot_spec
            )
            plotsIds.store(series_id_for_download, plot_spec, html_id)

        html = None
        html_status = visualization.get_plot_status(html_id)
        if html_status == "done":
            html = visualization.get_plot_html(html_id)
        else:
            waiting_message = f"Waiting for the plot, current status: {html_status}"
    else:
        logger.info(
            "Visualization data series unavailable",
            extra={
                "job_id": job_id,
                "series_id": series_id_for_download,
                "series_status": status,
            },
        )
        waiting_message = f"Waiting for the plot, current status: {html_status}"
        html = None

    return JobVisualizationResult(
        series=rendered_series_data,
        plot_type=plot_type,
        plot_html=html,
        waiting_message=waiting_message,
        disaster_stage_metrics=disaster_stage_metrics,
        plot_id=(html_id if status == "ok" else None),
        plot_status=(html_status if status == "ok" else None),
    )


def handle_get_job_repetitions(
    message: GetJobRepetitions,
    analytics: AnalyticsPort
) -> list[int]:
    _wait_for_job_results(message.job_id, analytics)
    return analytics.job_repetitions(message.job_id)


def handle_get_job_visualization_status(
    message: GetJobVisualizationStatus,
    analytics: AnalyticsPort,
) -> JobVisualizationStatus:
    """Cheap status read for the visualization config pages; must not enqueue work."""
    status = analytics.job_results_status(message.job_id)
    error = (
        analytics.job_results_error(message.job_id) if status == "error" else None
    )
    return JobVisualizationStatus(results_status=status, results_error=error)


def handle_get_visualization_constant_params(
    message: GetVisualizationConstantParams,
    analytics: AnalyticsPort
) -> JobVisualizationConstants:
    _wait_for_job_results(message.job_id, analytics)
    allParams = analytics.input_parameters_values(message.job_id)
    filtered = [param for param in allParams if param.name != message.selected_x ]
    return JobVisualizationConstants(filtered)


def _wait_for_job_results(job_id: str, analytics: AnalyticsPort) -> None:
    status = analytics.job_results_status(job_id)
    while status != "ok":
        if status == "error":
            raise ExternalServiceError(_job_results_error_message(job_id, analytics))
        status = analytics.job_results_status(job_id)
        time.sleep(0.1)


def _job_results_error_message(job_id: str, analytics: AnalyticsPort) -> str:
    detail = analytics.job_results_error(job_id)
    if detail:
        return f"Job results failed to load: {detail}"
    return "Job results failed to load."


def _extract_input_params(raw: List | None) -> List[tuple[str, str]]:
    params = []
    for item in raw or []:
        if isinstance(item, dict):
            name = item.get("name")
            p_type = item.get("type")
        else:
            name = getattr(item, "name", None)
            p_type = getattr(item, "type", None)
        if name and p_type:
            params.append((str(name), _param_type_text(p_type)))
    return params


def _extract_output_params(raw: List | None) -> List[tuple[str, str]]:
    params = []
    for item in raw or []:
        if isinstance(item, dict):
            name = item.get("name")
            p_type = item.get("type")
        else:
            name = getattr(item, "name", None)
            p_type = getattr(item, "type", None)
        if name and p_type:
            params.append((str(name), _param_type_text(p_type)))
    return params


def _extract_csv_bytes(data: bytes) -> bytes:
    if len(data) >= 4 and data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            names = [name for name in zf.namelist() if not name.endswith("/")]
            if len(names) != 1:
                raise ValidationError(f"Expected 1 file in zip, got {names}")
            return zf.read(names[0])
    return data


def _res_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    parts = path.split("/")
    for idx, part in enumerate(parts):
        if part == "results" and idx + 1 < len(parts):
            return parts[idx + 1]
    return ""


def _format_number(value: float, p_type: str) -> str:
    if p_type.lower() == "int":
        return str(int(round(value)))
    text = f"{value:g}"
    return text


def _normalize_bool(value: str) -> str:
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "y", "t"):
        return "true"
    if text in ("false", "0", "no", "n", "f"):
        return "false"
    return text


def _param_type_text(value: object) -> str:
    if hasattr(value, "value"):
        try:
            return str(value.value)
        except Exception:  # noqa: BLE001
            return str(value)
    return str(value)


def _csv_zip_bytes(headers: List[str], rows: List[Tuple], filename: str) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, buffer.getvalue())
    return out.getvalue()


def _rename_merged_series_headers(
    zip_bytes: bytes,
    rendered_series_data: list[JobVisualizationRenderedSeries],
) -> bytes:
    """Rewrite merged CSV column headers to per-series numbered labels."""
    if not rendered_series_data:
        return zip_bytes

    csv_bytes = _extract_csv_bytes(zip_bytes)
    text = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return zip_bytes

    headers = rows[0]
    if len(headers) != len(rendered_series_data) + 1:
        return zip_bytes

    renamed = [headers[0]]
    for i in range(len(rendered_series_data)):
        renamed.append(f"Series {i + 1}")
    rows[0] = renamed

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    content = buffer.getvalue()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("series.csv", content)
    return out.getvalue()


def _parser_data_to_plot_lines(parserData: list[tuple[str, float, float]]) -> list[PlotLine]:
    lines = []
    for disaster_stage_tuple in parserData:
        name = disaster_stage_tuple[0]
        end = disaster_stage_tuple[2]
        lines.append(PlotLine(label=name, point=end, color='red'))
    return lines


def _parser_data_to_areas(parserData: list[tuple[str, float, float]]) -> list[PlotArea]:
    stage_name_to_color = {
        'normal': 'green',
        'shock': 'red',
        'recovery': 'yellow',
        'post-failure': 'green'
    }
    areas = []
    for disaster_stage_tuple in parserData:
        name = disaster_stage_tuple[0].lower()
        start = disaster_stage_tuple[1]
        end = disaster_stage_tuple[2]
        areas.append(PlotArea(begin=start, end=end, color=stage_name_to_color[name]))
    return areas


def _parser_data_to_annotations(parserData: list[tuple[str, float, float]]) -> list[PlotAnnotation]:
    annotations = []
    for disaster_stage_tuple in parserData:
        label = disaster_stage_tuple[0]
        start = disaster_stage_tuple[1]
        end = disaster_stage_tuple[2]
        x = (start + end) / 2
        annotations.append(PlotAnnotation(point=x, text=label, color='black'))
    return annotations
