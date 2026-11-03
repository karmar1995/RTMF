from __future__ import annotations

import itertools
import logging
import re

from flask import current_app, render_template, jsonify, request, redirect, url_for
from dataclasses import asdict

from use_case_contracts.dtos import JobVisualizationRenderedSeries, JobVisualizationResult
from use_case_contracts.errors import (
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    TimeSeriesNotAlignedError,
    UnsupportedVisualizationError,
    ValidationError,
)
from use_case_contracts.messages import (
    BeginJobVisualization,
    GetMonteCarloFilteringPlotState,
    GetVisualizationConstantParams,
    GetJobVisualizationStatus,
    RetryJobResults,
    VisualizeDisasterStages,
    VisualizeJob,
    VisualizationSeries,
    GetJobRepetitions,
    VisualizeMonteCarloFiltering,
)

_SERIES_FIELD_RE = re.compile(r"^series_(\d+)_(x|y|stat)$")
_SERIES_CONSTANT_RE = re.compile(r"^series_(\d+)_constant_(.+)$")
logger = logging.getLogger(__name__)

_TIME_SERIES_VISUALIZATION_MODES = {
    "single-time-series": {
        "title": "Single Time Series Visualization",
        "heading": "Single Time Series Visualization",
        "submit_label": "Continue",
        "submit_message_factory": lambda job_id, series_list, plot_type, args: VisualizeJob(
            job_id=job_id,
            series=series_list,
            plot_type=plot_type,
        ),
    },
    "multiple-time-series": {
        "title": "Multiple Time Series Visualization",
        "heading": "Multiple Time Series Visualization",
        "submit_label": "Generate Plot",
        "submit_message_factory": lambda job_id, series_list, plot_type, args: VisualizeJob(
            job_id=job_id,
            series=_expand_range_series(
                series_list[0] if series_list else None,
                args,
            ),
            plot_type=plot_type,
        ),
    },
    "multiple-scalar": {
        "title": "Multiple Scalar Visualization",
        "heading": "Multiple Scalar Visualization",
        "submit_label": "Generate Plot",
        "submit_message_factory": lambda job_id, series_list, plot_type, args: VisualizeJob(
            job_id=job_id,
            series=_expand_range_series(
                series_list[0] if series_list else None,
                args,
            ),
            plot_type=plot_type,
        ),
    },
    "parser": {
        "title": "Parser Visualization",
        "heading": "Parser Visualization",
        "submit_label": "Continue",
        "submit_message_factory": lambda job_id, series_list, plot_type, args: VisualizeDisasterStages(
            job_id=job_id,
            series=series_list[0],
            plot_type=plot_type,
        ),
    },
}


def show_visualization_modes(job_id: str):
    return render_template(
        "job_visualization_modes.html",
        active_page="visualization",
        job_id=job_id,
    )

def begin_visualize_job(job_id: str):
    result, plot_types, error_message = _get_job_visualization_page_context(job_id)
    return render_template(
        "job_visualize.html",
        active_page="visualization",
        group_id=job_id,
        result=result,
        plot_types=plot_types,
        error_message=error_message,
    )


def retry_visualize_job(job_id: str):
    """Explicitly rebuild job results after a failed build (POST from the error
    card). Redirects back to the same config page, which then re-runs
    BeginJobVisualization and shows the waiting state while it rebuilds."""
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        logger.warning("Use-case layer not configured for results retry, job %s", job_id)
    else:
        try:
            usecases.handle(RetryJobResults(job_id=job_id))
        except (
            NotFoundError,
            ValidationError,
            TimeSeriesNotAlignedError,
            UnsupportedVisualizationError,
            AuthenticationError,
            ExternalServiceError,
        ) as exc:
            logger.warning("Failed to retry job results for job %s: %s", job_id, exc)
    next_url = request.form.get("next") or request.referrer or url_for(
        "onSimulationGroupVisualize", job_id=job_id
    )
    return redirect(next_url)


def show_single_time_series_visualization(job_id: str):
    return _show_time_series_visualization(job_id, "single-time-series")


def show_multiple_time_series_visualization(job_id: str):
    return _show_time_series_visualization(job_id, "multiple-time-series")


def show_multiple_scalar_visualization(job_id: str):
    return _show_time_series_visualization(job_id, "multiple-scalar")


def show_time_series_with_parser_visualization(job_id: str):
    return _show_time_series_visualization(job_id, "parser")


def show_monte_carlo_filtering_visualization(job_id: str):
    result, _, error_message = _get_job_visualization_page_context(job_id)
    return _render_monte_carlo_filtering_page(
        job_id=job_id,
        result=result,
        error_message=error_message,
    )


def get_monte_carlo_filtering_plot_state(
    job_id: str, plot_id: str, scatter_plot_id: str | None = None
):
    return _get_plot_state(job_id, plot_id, scatter_plot_id)


def get_job_plot_state(job_id: str, plot_id: str):
    return _get_plot_state(job_id, plot_id, None)


def _render_monte_carlo_filtering_page(
    *,
    job_id: str,
    result,
    error_message,
):
    return render_template(
        "monte_carlo_filtering_visualization.html",
        active_page="visualization",
        group_id=job_id,
        result=result,
        error_message=error_message,
    )


def _show_time_series_visualization(job_id: str, mode: str):
    mode_config = _get_time_series_visualization_mode(mode)
    template = (
        "multiple_time_series_visualization.html"
        if mode in ("multiple-time-series", "multiple-scalar")
        else "single_time_series_visualization.html"
    )
    result, plot_types, error_message = _get_job_visualization_page_context(job_id)
    return render_template(
        template,
        active_page="visualization",
        group_id=job_id,
        result=result,
        plot_types=plot_types,
        error_message=error_message,
        visualization_mode=mode,
        visualization_title=mode_config["title"],
        visualization_heading=mode_config["heading"],
        visualization_submit_label=mode_config["submit_label"],
        scalar_mode=(mode == "multiple-scalar"),
    )


def get_visualization_constant_params(job_id, selected_x):
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return []
    try:
        params = usecases.handle(
            GetVisualizationConstantParams(
                job_id=job_id,
                selected_x=selected_x
            )
        )
        dicts = [asdict(p) for p in params.constants]
        res = jsonify(dicts)
        return res
    except (
        NotFoundError,
        ValidationError,
        TimeSeriesNotAlignedError,
        UnsupportedVisualizationError,
        AuthenticationError,
        ExternalServiceError,
    ) as exc:
        return []


def get_visualization_repetitions(job_id: str):
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return jsonify({"repetitions": []})
    try:
        reps = usecases.handle(
            GetJobRepetitions(
                job_id=job_id
            )
        )
        res = jsonify({"repetitions": reps})
        return res
    except (
        NotFoundError,
        ValidationError,
        TimeSeriesNotAlignedError,
        UnsupportedVisualizationError,
        AuthenticationError,
        ExternalServiceError,
    ) as exc:
        logger.warning("Failed to load visualization repetitions for job %s: %s", job_id, exc)
        return jsonify({"repetitions": []})


def get_job_visualization_status(job_id: str):
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return jsonify({"results_status": "error", "results_error": "Use-case layer not configured!"}), 503

    try:
        status = usecases.handle(GetJobVisualizationStatus(job_id=job_id))
    except NotFoundError as exc:
        return jsonify({"results_status": "error", "results_error": str(exc)}), 404
    except ValidationError as exc:
        return jsonify({"results_status": "error", "results_error": str(exc)}), 400
    except ExternalServiceError as exc:
        return jsonify({"results_status": "error", "results_error": str(exc)}), 502
    except AuthenticationError as exc:
        return jsonify({"results_status": "error", "results_error": str(exc)}), 401

    response = jsonify(asdict(status))
    response.headers["Cache-Control"] = "no-store"
    return response


def _get_plot_state(job_id, plot_id, scatter_plot_id):
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return jsonify({"error": "Use-case layer not configured!"}), 503

    try:
        state = usecases.handle(
            GetMonteCarloFilteringPlotState(
                job_id=job_id,
                plot_id=plot_id,
                scatter_plot_id=scatter_plot_id or None,
            )
        )
    except NotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except ExternalServiceError as exc:
        return jsonify({"error": str(exc)}), 502
    except AuthenticationError as exc:
        return jsonify({"error": str(exc)}), 401

    response = jsonify(asdict(state))
    response.headers["Cache-Control"] = "no-store"
    return response


def visualize_job(job_id, request):
    mode = request.args.get("mode")
    if mode == "mcf":
        return _visualize_monte_carlo_filtering(job_id, request.args)

    series_list = _parse_visualization_series(request.args)
    plot_type = request.args.get("plot_type")
    mode = request.args.get("mode")
    mode_config = _get_time_series_visualization_mode(mode)
    plot_html = None

    def defaultReturn(message):
        result = JobVisualizationResult(
            series=_rendered_series_from_request(series_list),
            plot_type=plot_type,
            plot_html=plot_html,
            waiting_message=message,
            plot_status="error",
        )
        return render_template(
            "job_plot.html",
            active_page="visualization",
            group_id=job_id,
            job_id=job_id,
            result=result,
            visualization_mode=mode,
            visualization_title=mode_config["title"] if mode_config else None,
        )

    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return defaultReturn("Use-case layer not configured!")
    if not series_list:
        return defaultReturn("No visualization series selected.")
    try:
        if mode == "parser" and len(series_list) != 1:
            return defaultReturn("Parser visualization requires exactly one visualization series.")

        if mode_config:
            message = mode_config["submit_message_factory"](job_id, series_list, plot_type, request.args)
        else:
            message = VisualizeJob(
                job_id=job_id,
                series=series_list,
                plot_type=plot_type,
            )
        result = usecases.handle(message)

        return render_template(
            "job_plot.html",
            active_page="visualization",
            group_id=job_id,
            job_id=job_id,
            result=result,
            visualization_mode=mode,
            visualization_title=mode_config["title"] if mode_config else None,
        )

    except (
        NotFoundError,
        ValidationError,
        TimeSeriesNotAlignedError,
        UnsupportedVisualizationError,
        AuthenticationError,
        ExternalServiceError,
    ) as exc:
        return defaultReturn(str(exc))


def _monte_carlo_waiting_result(message: str, plot_type: str = "ECDF") -> JobVisualizationResult:
    return JobVisualizationResult(
        series=[],
        plot_type=plot_type,
        plot_html=None,
        waiting_message=message,
    )


def _visualize_monte_carlo_filtering(job_id: str, args):
    def render(result):
        return render_template(
            "job_plot.html",
            active_page="visualization",
            group_id=job_id,
            job_id=job_id,
            result=result,
            visualization_mode="mcf",
            visualization_title="Monte Carlo Filtering",
        )

    return render(_run_monte_carlo_filtering(job_id, args))


def _run_monte_carlo_filtering(job_id: str, args):
    usecases = current_app.extensions.get("usecases")
    aggregation = args.get("aggregation")
    plot_type = "ECDF"

    if usecases is None:
        return _monte_carlo_waiting_result(
            "Use-case layer not configured!", plot_type
        )

    y = args.get("y")
    threshold = args.get("threshold")
    direction = args.get("direction")

    if not (y and threshold and direction):
        return _monte_carlo_waiting_result(
            "Output, threshold and direction are required.", plot_type
        )
    try:
        threshold_value = float(threshold)
    except (TypeError, ValueError):
        return _monte_carlo_waiting_result("Threshold must be a number.", plot_type)
    if direction not in ("greater", "less"):
        return _monte_carlo_waiting_result(
            "Direction must be 'greater' or 'less'.", plot_type
        )

    try:
        # Fall back to the Monte Carlo Filtering form's aggregation only when the scatter
        # select was not submitted at all. An explicitly empty scatter_aggregation means the
        # user picked "None" on the plot page, and must not be overridden.
        if "scatter_aggregation" in args:
            scatter_aggregation = args.get("scatter_aggregation") or None
        else:
            scatter_aggregation = args.get("aggregation") or None

        message = VisualizeMonteCarloFiltering(
            job_id=job_id,
            output_column=y,
            threshold=threshold_value,
            direction=direction,
            aggregation=aggregation or None,
            scatter_x=args.get("scatter_x") or None,
            scatter_y=args.get("scatter_y") or None,
            scatter_aggregation=scatter_aggregation,
        )
        return usecases.handle(message)
    except (
        NotFoundError,
        ValidationError,
        TimeSeriesNotAlignedError,
        UnsupportedVisualizationError,
        AuthenticationError,
        ExternalServiceError,
    ) as exc:
        return _monte_carlo_waiting_result(str(exc), plot_type)


def _parse_visualization_series(args) -> list[VisualizationSeries]:
    series_entries: dict[int, dict] = {}
    has_indexed_series = False

    for key, value in args.items():
        field_match = _SERIES_FIELD_RE.match(key)
        if field_match:
            has_indexed_series = True
            series_index = int(field_match.group(1))
            field_name = field_match.group(2)
            entry = series_entries.setdefault(series_index, {"constants": {}})
            entry[field_name] = value
            continue

        constant_match = _SERIES_CONSTANT_RE.match(key)
        if constant_match:
            has_indexed_series = True
            series_index = int(constant_match.group(1))
            constant_name = constant_match.group(2)
            entry = series_entries.setdefault(series_index, {"constants": {}})
            entry["constants"][f"constant_{constant_name}"] = value

    if has_indexed_series:
        parsed_series: list[VisualizationSeries] = []
        for series_index in sorted(series_entries):
            entry = series_entries[series_index]
            x = entry.get("x")
            y = entry.get("y")
            statistic = entry.get("stat")
            if not (x and y and statistic):
                continue
            parsed_series.append(
                VisualizationSeries(
                    x=x,
                    y=y,
                    statistic=statistic,
                    constants=entry.get("constants", {}),
                )
            )
        return parsed_series

    x = args.get("x")
    y = args.get("y")
    statistic = args.get("stat")
    if not (x and y and statistic):
        return []

    constant_params = {
        key: value
        for key, value in args.items()
        if key.startswith("constant_")
    }
    repetition = args.get("repetition")
    if repetition:
        constant_params["constant_repetition"] = repetition
    return [
        VisualizationSeries(
            x=x,
            y=y,
            statistic=statistic,
            constants=constant_params,
        )
    ]


def _expand_range_series(
    base_series: VisualizationSeries | None,
    args,
) -> list[VisualizationSeries]:
    """Expand range selections into one visualization series per value combination.

    The Cartesian product of all swept parameter values is generated, so sweeping
    x values of one parameter and y values of another produces x * y series.
    """
    if base_series is None:
        return []

    ranged_values: dict[str, list[str]] = {}
    for key in args:
        match = re.match(r"^range_(?P<name>.+)$", key)
        if match:
            name = match.group("name")
            ranged_values[name] = args.getlist(key, type=str)

    if not ranged_values:
        return [base_series]

    expanded: list[VisualizationSeries] = []
    for swept_values in itertools.product(
        *[ranged_values[name] for name in sorted(ranged_values)]
    ):
        constants = dict(base_series.constants)
        for swept_name, value in zip(sorted(ranged_values), swept_values):
            constants[f"constant_{swept_name}"] = value
        expanded.append(
            VisualizationSeries(
                x=base_series.x,
                y=base_series.y,
                statistic=base_series.statistic,
                constants=constants,
            )
        )

    deduped: list[VisualizationSeries] = []
    seen: set[tuple] = set()
    for series in expanded:
        key = tuple(sorted(series.constants.items()))
        if key not in seen:
            seen.add(key)
            deduped.append(series)
    return deduped


def _rendered_series_from_request(
    series_list: list[VisualizationSeries],
) -> list[JobVisualizationRenderedSeries]:
    return [
        JobVisualizationRenderedSeries(
            x=series.x,
            y=series.y,
            statistic=series.statistic,
            constant_params=series.constants,
        )
        for series in series_list
    ]



def _get_job_visualization_page_context(job_id: str):
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return None, [], "Use-case adapter is not configured."

    try:
        result = usecases.handle(
            BeginJobVisualization(
                job_id=job_id
            )
        )
        return result, result.plot_types or [], None
    except (
        NotFoundError,
        ValidationError,
        TimeSeriesNotAlignedError,
        UnsupportedVisualizationError,
        AuthenticationError,
        ExternalServiceError,
    ) as exc:
        return None, [], str(exc)


def _get_time_series_visualization_mode(mode: str) -> dict:
    return _TIME_SERIES_VISUALIZATION_MODES.get(mode)
