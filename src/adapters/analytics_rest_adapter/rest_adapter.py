from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from adapters.analytics_rest_adapter.config import AnalyticsConfig
from adapters.analytics_rest_adapter.serialization import (
    parse_optional_message,
    parse_parameter_values_list,
    parse_series_id,
    parse_status,
    parse_supported_statistics,
    serialize_constant_params,
    serialize_parameter_defs,
    serialize_result_urls,
)
from use_case_contracts.ports import AnalyticsPort
from use_case_contracts.dtos import (
    MonteCarloFilteringResult,
    MonteCarloFilteringRun,
    MonteCarloFilteringStatistic,
    ParameterValues,
    ResultRef,
    SensitivityAnalysisResult,
)
from use_case_contracts.errors import (
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)


class RestAnalyticsAdapter(AnalyticsPort):
    def __init__(self, config: AnalyticsConfig, http_client: Any | None = None) -> None:
        self._config = config
        self._base_url = _normalize_base_url(config.base_url)
        self._http = http_client

    def initialize_job(
        self,
        job_id: str,
        job_root_url: str,
        results_urls: list[ResultRef],
        input_parameters: list[tuple[str, str]],
        output_parameters: list[tuple[str, str]],
    ) -> None:
        self._request_json(
            method="POST",
            path=f"/jobs/{urllib.parse.quote(job_id, safe='')}/initialize",
            payload={
                "job_root_url": job_root_url,
                "results_urls": serialize_result_urls(results_urls),
                "input_parameters": serialize_parameter_defs(input_parameters),
                "output_parameters": serialize_parameter_defs(output_parameters),
            },
        )

    def job_results_status(self, job_id: str) -> str:
        payload = self._request_json(
            method="GET",
            path=f"/jobs/{urllib.parse.quote(job_id, safe='')}/status",
        )
        return parse_status(payload)

    def job_results_error(self, job_id: str) -> str | None:
        payload = self._request_json(
            method="GET",
            path=f"/jobs/{urllib.parse.quote(job_id, safe='')}/results-error",
        )
        return parse_optional_message(payload)

    def retry_job_results(
        self,
        job_id: str,
        job_root_url: str,
        results_urls: list[ResultRef],
        input_parameters: list[tuple[str, str]],
        output_parameters: list[tuple[str, str]],
    ) -> None:
        self._request_json(
            method="POST",
            path=f"/jobs/{urllib.parse.quote(job_id, safe='')}/retry",
            payload={
                "job_root_url": job_root_url,
                "results_urls": serialize_result_urls(results_urls),
                "input_parameters": serialize_parameter_defs(input_parameters),
                "output_parameters": serialize_parameter_defs(output_parameters),
            },
        )

    def input_parameters_values(self, job_id: str) -> list[ParameterValues] | None:
        payload = self._request_json(
            method="GET",
            path=f"/jobs/{urllib.parse.quote(job_id, safe='')}/input-parameters/values",
        )
        return parse_parameter_values_list(payload)

    def job_repetitions(self, job_id: str) -> list[int] | None:
        payload = self._request_json(
            method="GET",
            path=f"/jobs/{urllib.parse.quote(job_id, safe='')}/repetitions",
        )
        if payload is None:
            return None
        return [int(value) for value in payload]
    def prepare_series(
        self,
        job_id: str,
        x_param: str,
        y_param: str,
        constants: list[tuple[str, str]],
        statistic: str,
    ) -> str:
        payload = self._request_json(
            method="POST",
            path="/series/prepare",
            payload={
                "job_id": job_id,
                "x_param": x_param,
                "y_param": y_param,
                "constants": serialize_constant_params(constants),
                "statistic": _normalize_statistic_name(statistic),
            },
        )
        return parse_series_id(payload)

    def get_series_status(self, series_id: str) -> str:
        payload = self._request_json(
            method="GET",
            path=f"/series/{urllib.parse.quote(series_id, safe='')}/status",
        )
        return parse_status(payload)

    def download_series(self, series_id: str) -> bytes:
        return self._request_bytes(
            method="GET",
            path=f"/series/{urllib.parse.quote(series_id, safe='')}/download",
            accept="application/octet-stream",
        )

    def supported_statistics(self) -> list[str]:
        payload = self._request_json(method="GET", path="/statistics")
        return parse_supported_statistics(payload)

    def merge_series(self, seriesIds : list[str]) -> str:
        payload = self._request_json(
            method="POST",
            path="/multi-series/merge",
            payload={"series_ids": seriesIds},
        )
        return parse_series_id(payload)

    def analyze_sensitivity(
        self,
        csv_data: str | None = None,
        problem: dict[str, object] | None = None,
        n_real: int | None = None,
        output_names: list[str] | None = None,
        results_urls: list[str] | None = None,
        aggregation: str | None = None,
    ) -> SensitivityAnalysisResult:
        payload = self._request_json(
            method="POST",
            path="/sensitivity-analysis",
            payload={
                "csv_data": csv_data,
                "problem": problem,
                "n_real": n_real,
                "output_names": output_names,
                "results_urls": results_urls,
                "aggregation": aggregation,
            },
        )
        return SensitivityAnalysisResult(
            mean_data_csv=payload["mean_data_csv"],
            important_parameters=payload["important_parameters"],
            deterministic_indices_csv=payload["deterministic_indices_csv"],
            stochastic_indices_csv=payload["stochastic_indices_csv"],
        )

    def analyze_monte_carlo_filtering(
        self,
        csv_data: str | None = None,
        problem: dict[str, object] | None = None,
        output_column: str | None = None,
        threshold: float | None = None,
        direction: str | None = None,
        results_urls: list[str] | None = None,
        aggregation: str | None = None,
        alpha: float = 0.05,
        output_aggregations: dict[str, str] | None = None,
        run_output_columns: list[str] | None = None,
    ) -> MonteCarloFilteringResult:
        payload = self._request_json(
            method="POST",
            path="/monte-carlo-filtering",
            payload={
                "csv_data": csv_data,
                "problem": problem,
                "output_column": output_column,
                "threshold": threshold,
                "direction": direction,
                "results_urls": results_urls,
                "aggregation": aggregation,
                "alpha": alpha,
                "output_aggregations": output_aggregations,
                "run_output_columns": run_output_columns,
            },
        )
        return MonteCarloFilteringResult(
            output_column=payload["output_column"],
            threshold=payload["threshold"],
            direction=payload["direction"],
            aggregation=payload["aggregation"],
            behavioural_count=payload["behavioural_count"],
            non_behavioural_count=payload["non_behavioural_count"],
            runs=[
                _monte_carlo_run_from_payload(item)
                for item in payload.get("runs", [])
            ],
            parameters=[
                _monte_carlo_statistic_from_payload(item)
                for item in payload["parameters"]
            ],
        )

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        response = self._request_bytes(
            method=method,
            path=path,
            payload=payload,
            accept="application/json",
        )
        if not response:
            return None
        try:
            return json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExternalServiceError(
                f"Analytics service returned malformed JSON for {method} {self._build_url(path)}"
            ) from exc

    def _request_bytes(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        accept: str,
    ) -> bytes:
        url = self._build_url(path)
        headers = {"Accept": accept}
        data = None
        if self._config.auth_token:
            headers["Authorization"] = f"Bearer {self._config.auth_token}"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        timeout = self._config.timeout_seconds or 10
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body_text = exc.read() if exc.fp else b""
            message = _format_http_error(method=method, url=url, status=exc.code, body=body_text)
            if exc.code in (401, 403):
                raise AuthenticationError(message) from exc
            if exc.code == 404:
                raise NotFoundError(message) from exc
            if exc.code == 400:
                raise ValidationError(message) from exc
            raise ExternalServiceError(message) from exc
        except (urllib.error.URLError, socket.timeout) as exc:
            raise ExternalServiceError(
                f"Analytics service request failed ({method} {url}): {exc}"
            ) from exc

    def _build_url(self, path: str) -> str:
        return urllib.parse.urljoin(f"{self._base_url}/", path.lstrip("/"))


def _normalize_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        raise ValueError("Analytics base URL must not be empty")
    return normalized


def _format_http_error(*, method: str, url: str, status: int, body: bytes) -> str:
    snippet = body.decode("utf-8", errors="replace").strip()
    if len(snippet) > 200:
        snippet = f"{snippet[:200]}..."
    if snippet:
        return f"Analytics service request failed ({method} {url}, status={status}, body={snippet})"
    return f"Analytics service request failed ({method} {url}, status={status})"


def _normalize_statistic_name(statistic: str) -> str:
    normalized = statistic.strip().lower()
    if normalized == "average":
        return "mean"
    return normalized


def _monte_carlo_run_from_payload(payload: dict[str, Any]) -> MonteCarloFilteringRun:
    return MonteCarloFilteringRun(
        index=payload["index"],
        behavioural=bool(payload.get("behavioural", False)),
        parameters=payload.get("parameters", {}),
        outputs=payload.get("outputs", {}),
    )


def _monte_carlo_statistic_from_payload(payload: dict[str, Any]) -> MonteCarloFilteringStatistic:
    return MonteCarloFilteringStatistic(
        parameter=payload["parameter"],
        d_statistic=payload["d_statistic"],
        p_value=payload["p_value"],
        reject_h0=payload["reject_h0"],
        behavioural_samples=payload["behavioural_samples"],
        non_behavioural_samples=payload["non_behavioural_samples"],
        behavioural_ecdf_x=payload.get("behavioural_ecdf_x", []),
        behavioural_ecdf_y=payload.get("behavioural_ecdf_y", []),
        non_behavioural_ecdf_x=payload.get("non_behavioural_ecdf_x", []),
        non_behavioural_ecdf_y=payload.get("non_behavioural_ecdf_y", []),
    )
