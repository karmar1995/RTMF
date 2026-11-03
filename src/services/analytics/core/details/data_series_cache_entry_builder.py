from __future__ import annotations

import threading
import uuid

from services.analytics.core.details.data_series_cache import DataSeriesCache, DataSeriesCacheEntry, DataSeriesRequest
from services.analytics.core.details.job_data_series_evaluator import JobDataSeriesEvaluator
from services.analytics.core.details.job_results_cache import JobResultsCache
from services.analytics.core.model import parameter_name_is_time_series
from use_case_contracts.ports import ResultsRepositoryPort


class DataSeriesCacheEntryBuilder:
    """Build cache entries asynchronously on a dedicated builder-owned thread."""

    def __init__(
        self,
        cache: DataSeriesCache,
        job_results_cache: JobResultsCache,
        results_repository: ResultsRepositoryPort,
    ) -> None:
        self._results_repository = results_repository
        self._job_results_cache = job_results_cache
        self._cache = cache
        self._request: DataSeriesRequest | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def assign(self, request: DataSeriesRequest) -> None:
        """Assign a request to this builder and start processing it."""

        with self._lock:
            if self._request is not None:
                raise RuntimeError("builder is already busy")
            self._request = request
            self._thread = threading.Thread(
                target=self._build,
                args=(request,),
                daemon=True,
            )
            thread = self._thread
        thread.start()

    def assigned_job_id(self) -> str | None:
        """Return the currently assigned job id, if any."""

        with self._lock:
            if self._request is None:
                return None
            return self._request.job_id

    def busy(self) -> bool:
        """Return whether this builder is currently processing an assigned request."""

        with self._lock:
            return self._request is not None

    def _clear_assignment(self) -> None:
        with self._lock:
            self._request = None
            self._thread = None

    def _build(self, request: DataSeriesRequest) -> None:
        try:
            job_results = self._job_results_cache.get(request.job_id)
            if job_results is None:
                raise ValueError(f"job result not found in cache: {request.job_id}")

            evaluator = JobDataSeriesEvaluator(
                main_results=job_results.main_results,
                results_repository=self._results_repository,
            )

            y_param_is_time_series = False
            for output_param in job_results.output_parameters:
                if output_param[0] == request.y_param and parameter_name_is_time_series(output_param[1]):
                    y_param_is_time_series = True

            if request.x_param == "time":
                if y_param_is_time_series:
                    data_series = evaluator.evaluateTimeSeries(
                        y_param=request.y_param,
                        constants=request.constants,
                        statistic=request.statistic,
                    )
                else:
                    raise ValueError(f"Cannot compute time statistics for non-time-series output!")
            else:
                if y_param_is_time_series:
                    data_series = evaluator.aggregateTimeSeries(
                        x_param=request.x_param,
                        y_param=request.y_param,
                        constants=request.constants,
                        statistic=request.statistic,
                    )
                else:
                    data_series = evaluator.evaluateSeries(
                        x_param=request.x_param,
                        y_param=request.y_param,
                        constants=request.constants,
                        statistic=request.statistic,
                    )

            key = self._cache.build_key(
                job_id=request.job_id,
                x_param=request.x_param,
                y_param=request.y_param,
                constants=request.constants,
                statistic=request.statistic,
            )
            entry_id = request.series_id

            self._cache.put(
                entry_id,
                DataSeriesCacheEntry(
                    entry_id=entry_id,
                    key=key,
                    data_series=data_series,
                ),
            )
        finally:
            self._clear_assignment()
