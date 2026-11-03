import io
import csv
import time
import uuid
import zipfile

import numpy as np

from services.analytics.core.details.monte_carlo_filtering import run_monte_carlo_filtering
from services.analytics.core.details.sensitivity_analysis import run_sobol_analysis
from use_case_contracts.ports import AnalyticsPort
from use_case_contracts.dtos import (
    MonteCarloFilteringResult,
    ParameterValues,
    ResultRef,
    SensitivityAnalysisResult,
)


class FakeAnalytics(AnalyticsPort):
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._series: dict[str, dict] = {}

    def initialize_job(
        self,
        job_id: str,
        job_root_url: str,
        results_urls: list[ResultRef],
        input_parameters: list[tuple[str, str]],
        output_parameters: list[tuple[str, str]],
    ) -> None:
        if job_id not in self._jobs or self._jobs[job_id].get("status") == "unknown":
            self._jobs[job_id] = {
                "status": "processing",
                "start_time": time.time(),
                "job_root_url": job_root_url,
                "results_urls": results_urls,
                "input_parameters": input_parameters,
                "output_parameters": output_parameters,
            }

    def retry_job_results(
        self,
        job_id: str,
        job_root_url: str,
        results_urls: list[ResultRef],
        input_parameters: list[tuple[str, str]],
        output_parameters: list[tuple[str, str]],
    ) -> None:
        entry = self._jobs.get(job_id) or {}
        entry.update(
            {
                "status": "processing",
                "start_time": time.time(),
                "job_root_url": job_root_url,
                "results_urls": results_urls,
                "input_parameters": input_parameters,
                "output_parameters": output_parameters,
            }
        )
        entry.pop("error_message", None)
        self._jobs[job_id] = entry

    def job_results_status(self, job_id: str) -> str:
        entry = self._jobs.get(job_id)
        if entry is None:
            return "unknown"
        if entry.get("error_message") is not None:
            return "error"
        entry["status"] = "ok"
        return "ok"

    def job_results_error(self, job_id: str) -> str | None:
        entry = self._jobs.get(job_id)
        if entry is None:
            return None
        return entry.get("error_message")

    def fail_job_results(self, job_id: str, message: str) -> None:
        """Injection point for frontend tests: mark a job's results as failed."""
        self._jobs[job_id] = {
            "status": "processing",
            "start_time": time.time(),
            "error_message": message,
            "job_root_url": "",
            "results_urls": [],
            "input_parameters": [],
            "output_parameters": [],
        }

    def input_parameters_values(self, job_id: str) -> list[ParameterValues] | None:
        entry = self._jobs.get(job_id)
        if entry is None or entry["status"] != "ok":
            return None
        return [
            ParameterValues(name=name, value=[0.0, 1.0, 2.0])
            for name, _ in entry["input_parameters"]
        ]

    def job_repetitions(self, job_id: str) -> list[int] | None:
        entry = self._jobs.get(job_id)
        if entry is None or entry["status"] != "ok":
            return None
        return [0, 1]

    def prepare_series(
        self,
        job_id: str,
        x_param: str,
        y_param: str,
        constants: list[tuple[str, str]],
        statistic: str,
    ) -> str:
        series_id = uuid.uuid4().hex
        self._series[series_id] = {
            "status": "processing",
            "start_time": time.time(),
            "job_id": job_id,
            "x_param": x_param,
            "y_param": y_param,
            "constants": constants,
            "statistic": statistic,
        }
        return series_id

    def get_series_status(self, series_id: str) -> str:
        entry = self._series.get(series_id)
        if entry is None:
            return "unknown"
        entry["status"] = "ok"
        return "ok"

    def download_series(self, series_id: str) -> bytes:
        entry = self._series.get(series_id)
        if entry is None or entry["status"] != "ok":
            return b""

        constants_dict = dict(entry["constants"])
        param_values = np.array(
            [float(v) for v in constants_dict.values()], dtype=float
        )
        rosenbrock_val = float(
            np.sum(
                100.0 * (param_values[1:] - param_values[:-1] ** 2) ** 2
                + (1 - param_values[:-1]) ** 2
            )
        )

        steps = 100
        failure_width = min(int(rosenbrock_val), steps - 2)
        failure_start = 0
        failure_end = failure_start + failure_width

        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(["step", "result_x"])

        for step in range(steps):
            if failure_start <= step < failure_end:
                result_x = 0.1
            else:
                result_x = 2.0
            writer.writerow([step, round(result_x, 4)])

        csv_content = csv_buffer.getvalue()

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("series.csv", csv_content.encode("utf-8"))
        return zip_buffer.getvalue()

    def supported_statistics(self) -> list[str]:
        return ["mean"]

    def merge_series(self, seriesIds: list[str]) -> str:
        merged_id = uuid.uuid4().hex
        self._series[merged_id] = {
            "status": "ok",
            "start_time": time.time(),
        }
        return merged_id

    def analyze_sensitivity(
        self,
        csv_data: str | None = None,
        problem: dict[str, object] | None = None,
        n_real: int | None = None,
        output_names: list[str] | None = None,
        results_urls: list[str] | None = None,
        aggregation: str | None = None,
    ) -> SensitivityAnalysisResult:
        if results_urls is not None:
            raise NotImplementedError("FakeAnalytics does not support results_urls")
        return run_sobol_analysis(
            csv_data=csv_data,
            problem=problem,
            n_real=n_real,
            output_names=output_names,
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
        if results_urls is not None:
            raise NotImplementedError("FakeAnalytics does not support results_urls")
        return run_monte_carlo_filtering(
            csv_data=csv_data,
            parameter_names=list(problem["names"] if problem else []),
            output_column=output_column,
            threshold=threshold,
            direction=direction,
            alpha=alpha,
            aggregation=aggregation,
            run_output_columns=run_output_columns,
        )
