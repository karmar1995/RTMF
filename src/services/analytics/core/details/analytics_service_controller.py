import csv
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import io
import threading
import time
import uuid

import pandas as pd

from services.analytics.core.details.job_data_series_evaluator import get_supported_statistics_names
from services.analytics.core.details.cache_entry_requests_processor import CacheEntryRequestsProcessor
from services.analytics.core.details.cache_entry_requests_queue import CacheEntryRequestsQueue
from services.analytics.core.details.data_series_cache import DataSeriesCache, DataSeriesRequest
from services.analytics.core.details.data_series_cache_entry_builder import DataSeriesCacheEntryBuilder
from services.analytics.core.details.data_series_requests_processor import DataSeriesRequestsProcessor
from services.analytics.core.details.data_series_requests_queue import DataSeriesRequestsQueue
from services.analytics.core.details.job_results_cache import (
    CacheEntryRequest,
    JobResultFailures,
    JobResultsCache,
)
from services.analytics.core.details.job_results_cache_entry_builder import JobResultsEntryCacheBuilder
from services.analytics.core.details.job_results_cache_garbage_collector import TimeLimitedCacheGarbageCollector
from services.analytics.core.details.main_results_csv_builder import MainResultsCsvBuilder
from services.analytics.core.details.monte_carlo_filtering import run_monte_carlo_filtering
from services.analytics.core.details.multi_data_series_cache import MultiDataSeriesCache
from services.analytics.core.details.multi_data_series_cache_entry_builder import MultiDataSeriesCacheEntryBuilder
from services.analytics.core.details.results_table_cache import (
    ResultsTable,
    ResultsTableCache,
    ResultsTableEntry,
    results_table_key,
)
from services.analytics.core.details.sensitivity_analysis import run_sobol_analysis
from services.analytics.core.details.timeseries_aggregation import (
    aggregate_timeseries_values as _aggregate_timeseries_values,
)
from services.analytics.core.details.timeseries_aggregation import (
    is_timeseries_reference as _is_timeseries_reference,
)
from services.analytics.core.details.timeseries_aggregation import (
    load_timeseries_dataframe as _load_timeseries_dataframe,
)
from services.analytics.core.details.timeseries_aggregation import (
    resolve_aggregation_spec as _resolve_aggregation_spec,
)
from services.analytics.core.details.timeseries_aggregation import (
    resolve_timeseries_url as _resolve_timeseries_url,
)
from services.analytics.infra.zip_utils import zip_string
from use_case_contracts.dtos import (
    MonteCarloFilteringResult,
    ParameterValues,
    ResultRef,
    SensitivityAnalysisResult,
)
from use_case_contracts.ports import AnalyticsPort, ResultsRepositoryPort

DEFAULT_DOWNLOAD_WORKERS = 12

# How long a job is considered 'in flight' before its tracking entry is treated
# as stale. Guards against a stuck entry (e.g. the server was interrupted before
# the builder's completion callback ran) permanently blocking re-initialization.
JOBS_INFLIGHT_TTL_SECONDS = 15 * 60


class AnalyticsServiceController(AnalyticsPort):
    def __init__(
        self,
        results_repository: ResultsRepositoryPort,
        download_workers: int = DEFAULT_DOWNLOAD_WORKERS,
        jobs_inflight_ttl_seconds: int = JOBS_INFLIGHT_TTL_SECONDS,
    ) -> None:
        self._max_builders = 5
        self.results_repository = results_repository
        self._download_workers = max(1, int(download_workers))
        self._jobs_inflight_ttl_seconds = max(1, int(jobs_inflight_ttl_seconds))
        self._download_executor = ThreadPoolExecutor(
            max_workers=self._download_workers,
            thread_name_prefix="results-download",
        )
        self._jobs_results_cache = JobResultsCache(timedelta(minutes=30))
        self._failure_registry = JobResultFailures()
        self._inflight_jobs: dict[str, float] = {}
        self._inflight_lock = threading.Lock()
        self._ds_cache = DataSeriesCache(timedelta(hours=2))
        self._mds_cache = MultiDataSeriesCache(timedelta(hours=2))
        self._results_table_cache = ResultsTableCache(timedelta(minutes=30))
        self._job_entry_builders = [
            JobResultsEntryCacheBuilder(
                cache=self._jobs_results_cache,
                results_repository=self.results_repository,
                failures=self._failure_registry,
                on_completed=self._on_job_results_build_finished,
            )
            for _ in range(self._max_builders)
        ]
        self._ds_entry_builders = [
            DataSeriesCacheEntryBuilder(
                cache=self._ds_cache,
                job_results_cache=self._jobs_results_cache,
                results_repository=self.results_repository
            )
            for _ in range(self._max_builders)
        ]
        self._ds_requests_queue = DataSeriesRequestsQueue(maxsize=1000)
        self._requests_queue = CacheEntryRequestsQueue(maxsize=1000)
        self._requests_processor = CacheEntryRequestsProcessor(
            requests_queue=self._requests_queue,
            builders=self._job_entry_builders,
        )
        self._ds_queue_processor = DataSeriesRequestsProcessor(
            requests_queue=self._ds_requests_queue,
            builders=self._ds_entry_builders
        )

        self._cache_garbage_collector = TimeLimitedCacheGarbageCollector(
            caches=[self._jobs_results_cache, self._ds_cache, self._results_table_cache],
        )
        self._requests_processor.start()
        self._ds_queue_processor.start()
        self._cache_garbage_collector.start()

    def initialize_job(
        self,
        job_id: str,
        job_root_url: str,
        results_urls: list[ResultRef],
        input_parameters: list[tuple[str, str]],
        output_parameters: list[tuple[str, str]],
    ) -> None:
        if self._jobs_results_cache.get(job_id) is not None:
            return
        if self._failure_registry.get(job_id) is not None:
            # A previous build failed and no explicit retry happened yet: do not
            # re-enqueue the same doomed build on every page load.
            return
        if self._is_inflight(job_id):
            return
        self._mark_inflight(job_id)
        self._enqueue_job(
            job_id=job_id,
            job_root_url=job_root_url,
            results_urls=results_urls,
            input_parameters=input_parameters,
            output_parameters=output_parameters,
        )

    def retry_job_results(
        self,
        job_id: str,
        job_root_url: str,
        results_urls: list[ResultRef],
        input_parameters: list[tuple[str, str]],
        output_parameters: list[tuple[str, str]],
    ) -> None:
        """Explicitly rebuild job results after a failure, clearing the error."""
        self._failure_registry.remove(job_id)
        if self._jobs_results_cache.get(job_id) is not None:
            return
        if self._is_inflight(job_id):
            return
        self._mark_inflight(job_id)
        self._enqueue_job(
            job_id=job_id,
            job_root_url=job_root_url,
            results_urls=results_urls,
            input_parameters=input_parameters,
            output_parameters=output_parameters,
        )

    def job_results_status(self, job_id: str) -> str:
        if self._jobs_results_cache.get(job_id):
            return "ok"
        if self._failure_registry.get(job_id) is not None:
            return "error"
        if self._is_inflight(job_id):
            return "processing"
        for builder in self._job_entry_builders:
            if builder.assigned_job_id() == job_id:
                return "processing"
        return "unknown"

    def job_results_error(self, job_id: str) -> str | None:
        return self._failure_registry.get(job_id)

    def _enqueue_job(
        self,
        *,
        job_id: str,
        job_root_url: str,
        results_urls: list[ResultRef],
        input_parameters: list[tuple[str, str]],
        output_parameters: list[tuple[str, str]],
    ) -> None:
        self._requests_queue.put(CacheEntryRequest(
            job_id=job_id,
            job_root_url=job_root_url,
            results_urls=[_result_url(result_ref) for result_ref in results_urls],
            input_parameters=input_parameters,
            output_parameters=output_parameters
        ))

    def _mark_inflight(self, job_id: str) -> None:
        with self._inflight_lock:
            self._inflight_jobs[job_id] = time.time()

    def _is_inflight(self, job_id: str) -> bool:
        with self._inflight_lock:
            now = time.time()
            stale = [
                queued_id
                for queued_id, started_at in self._inflight_jobs.items()
                if now - started_at >= self._jobs_inflight_ttl_seconds
            ]
            for queued_id in stale:
                self._inflight_jobs.pop(queued_id, None)
            return job_id in self._inflight_jobs

    def _on_job_results_build_finished(self, job_id: str) -> None:
        with self._inflight_lock:
            self._inflight_jobs.pop(job_id, None)

    def input_parameters_values(self, job_id: str) -> list[ParameterValues] | None:
        job_results = self._jobs_results_cache.get(job_id)
        if job_results:
            result: list[ParameterValues] = []
            for (name, _type), values in job_results.input_parameters.items():
                filtered_values = [v for v in values if v is not None]
                result.append(
                    ParameterValues(
                        name=name,
                        value=filtered_values if filtered_values else None,
                    )
                )
            return result
        return None

    def job_repetitions(self, job_id: str) -> list[int] | None:
        job_results = self._jobs_results_cache.get(job_id)
        if job_results:
            return job_results.repetitions
        return None

    def prepare_series(
        self,
        job_id: str,
        x_param: str,
        y_param: str,
        constants: list[tuple[str, str]],
        statistic: str,
    ) -> str | None:
        if self._jobs_results_cache.get(job_id) is None:
            return None

        existingId = self._ds_cache.get_id(
            job_id=job_id,
            x_param=x_param,
            y_param=y_param,
            constants=constants,
            statistic=statistic)

        if existingId is not None:
            return existingId

        new_id = uuid.uuid4().hex
        self._ds_cache.put_in_progress_id(
            job_id=job_id,
            x_param=x_param,
            y_param=y_param,
            constants=constants,
            statistic=statistic,
            in_progress_id=new_id
        )

        dataSeriesRequest = DataSeriesRequest(
            series_id=new_id,
            job_id=job_id,
            x_param=x_param,
            y_param=y_param,
            constants=constants,
            statistic=statistic
        )
        self._ds_requests_queue.put(dataSeriesRequest)
        return dataSeriesRequest.series_id

    def get_series_status(self, seriesId: str) -> str:
        if self._ds_cache.get(seriesId) is not None:
            return "ok"
        if self._mds_cache.get(seriesId) is not None:
            if not self._mds_cache.is_invalid(seriesId):
                return "ok"
            else:
                return "invalid"
        return "unknown"

    def download_series(self, seriesId: str) -> bytes:
        if self._ds_cache.get(seriesId) is not None:
            return zip_string(self._ds_cache.get(seriesId).writeCsv())
        if self._mds_cache.get(seriesId) is not None:
            return zip_string(self._mds_cache.get(seriesId).writeCsv())
        return bytes()

    def supported_statistics(self) -> list[str]:
        return get_supported_statistics_names()

    def merge_series(self, seriesIds: list[str]) -> str | None:
        for seriesId in seriesIds:
            if not self._ds_cache.has_id(seriesId):
                return None

        existingId = self._mds_cache.get_id(seriesIds)
        if existingId is not None:
            return existingId

        new_id = uuid.uuid4().hex
        self._mds_cache.put_in_progress_id(seriesIds, new_id)
        builder = MultiDataSeriesCacheEntryBuilder(
            data_series_cache=self._ds_cache,
            multi_data_series_cache=self._mds_cache
        )

        thread = threading.Thread(
            target=builder.build,
            args=(new_id, seriesIds),
            name=f"multi-data-series-build-{new_id}",
            daemon=True,
        )
        thread.start()
        return new_id


    def analyze_sensitivity(
        self,
        csv_data: str | None = None,
        problem: dict[str, object] | None = None,
        n_real: int | None = None,
        output_names: list[str] | None = None,
        results_urls: list[str] | None = None,
        aggregation: str | None = None,
    ) -> SensitivityAnalysisResult:
        if (csv_data is None) == (results_urls is None):
            raise ValueError("Provide exactly one of csv_data or results_urls")
        timeseries_cache: dict[str, pd.DataFrame] = {}
        if results_urls is not None:
            sources = [
                self.results_repository.download(url).decode("utf-8")
                for url in results_urls
            ]
            if aggregation:
                sources = [
                    _aggregate_timeseries_source(
                        source=source,
                        source_url=url,
                        aggregation=aggregation,
                        output_names=output_names,
                        results_repository=self.results_repository,
                        timeseries_cache=timeseries_cache,
                    )
                    for source, url in zip(sources, results_urls)
                ]
            csv_data = MainResultsCsvBuilder().build(sources)
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
        if (csv_data is None) == (results_urls is None):
            raise ValueError("Provide exactly one of csv_data or results_urls")
        if output_column is None:
            raise ValueError("output_column must be provided")
        if threshold is None:
            raise ValueError("threshold must be provided")
        if direction not in ("greater", "less"):
            raise ValueError("direction must be either 'greater' or 'less'")
        if problem is None:
            raise ValueError("problem must be provided")
        parameter_names = problem.get("names")
        if not parameter_names:
            raise ValueError("problem['names'] must list the input parameter columns")

        aggregation_map: dict[str, str] = {}
        if aggregation:
            aggregation_map[output_column] = aggregation
        for name, method in (output_aggregations or {}).items():
            if method:
                aggregation_map[name] = method

        output_column_aliases: dict[str, str] = {}
        if results_urls is not None:
            table = self._results_table(results_urls)
            resolved_columns = table.materialize(aggregation_map)
            csv_data = table.csv_text()
            output_column_aliases = {
                derived: base
                for base, derived in resolved_columns.items()
                if derived != base
            }
            output_column = resolved_columns.get(output_column, output_column)
            run_output_columns = [
                resolved_columns.get(name, name)
                for name in (run_output_columns or [])
            ]

        return run_monte_carlo_filtering(
            csv_data=csv_data,
            parameter_names=list(parameter_names),
            output_column=output_column,
            threshold=float(threshold),
            direction=direction,
            alpha=alpha,
            aggregation=aggregation,
            run_output_columns=list(run_output_columns or []),
            output_column_aliases=output_column_aliases,
        )

    def _results_table(self, results_urls: list[str]) -> ResultsTable:
        """Return the cached merged table for these results, building it once."""

        key = results_table_key(results_urls)
        entry = self._results_table_cache.get(key)
        if entry is not None:
            return self._results_table_view(key, entry, results_urls)

        with self._results_table_cache.fill_lock(key):
            entry = self._results_table_cache.get(key)
            if entry is not None:
                return self._results_table_view(key, entry, results_urls)
            table = ResultsTable.build(
                results_urls=results_urls,
                sources=self._download_sources(results_urls),
                fetch_timeseries=self._fetch_timeseries_batch,
            )
            self._results_table_cache.put(key, table.snapshot())
            return self._results_table_view(key, table.snapshot(), results_urls)

    def _results_table_view(
        self, key: str, entry: ResultsTableEntry, results_urls: list[str]
    ) -> ResultsTable:
        return ResultsTable(
            entry=entry,
            results_urls=results_urls,
            fetch_timeseries=self._fetch_timeseries_batch,
            on_update=lambda updated: self._results_table_cache.put(key, updated),
            lock=self._results_table_cache.fill_lock(key),
            refresh_entry=lambda: self._results_table_cache.get(key),
        )

    def _fetch_timeseries_batch(self, urls: Sequence[str]) -> dict[str, bytes]:
        """Download every distinct time-series CSV once, in parallel."""

        unique = list(dict.fromkeys(urls))
        if not unique:
            return {}
        if len(unique) == 1:
            return {unique[0]: self.results_repository.download(unique[0])}
        contents = self._download_executor.map(
            self.results_repository.download, unique
        )
        return dict(zip(unique, contents))

    def _download_sources(self, results_urls: list[str]) -> list[str]:
        if len(results_urls) <= 1:
            return [
                self.results_repository.download(url).decode("utf-8")
                for url in results_urls
            ]
        return list(
            self._download_executor.map(self._download_source, results_urls)
        )

    def _download_source(self, url: str) -> str:
        return self.results_repository.download(url).decode("utf-8")


def _aggregate_timeseries_source(
    *,
    source: str,
    source_url: str,
    aggregation: str | None,
    output_names: list[str] | None,
    results_repository: ResultsRepositoryPort,
    timeseries_cache: dict[str, pd.DataFrame] | None = None,
) -> str:
    reader = csv.DictReader(io.StringIO(source), delimiter=";")
    fieldnames = reader.fieldnames
    if not fieldnames:
        return source

    rows = list(reader)
    columns = output_names or fieldnames

    if not any(
        col in row and _is_timeseries_reference(row[col])
        for row in rows
        for col in columns
    ):
        return source

    if timeseries_cache is None:
        timeseries_cache = {}
    for row in rows:
        for column in columns:
            if column not in row:
                continue
            cell = (row.get(column) or "").strip()
            if not _is_timeseries_reference(cell):
                continue
            method = aggregation
            if not method:
                continue
            aggregation_spec = _resolve_aggregation_spec(method)
            timeseries_url = _resolve_timeseries_url(
                source_url=source_url,
                cell=cell,
            )
            dataframe = _load_timeseries_dataframe(
                timeseries_url=timeseries_url,
                results_repository=results_repository,
                timeseries_cache=timeseries_cache,
            )
            row[column] = _aggregate_timeseries_values(
                dataframe=dataframe,
                value_column=column,
                aggregation_spec=aggregation_spec,
            )

    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=fieldnames, delimiter=";", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _result_url(result_ref: ResultRef) -> str:
    return result_ref.url
