from __future__ import annotations

import threading
import csv
import io


from services.analytics.core.details.job_result_parameters_evaluator import JobResultParametersEvaluator
from services.analytics.core.details.main_results_csv_builder import MainResultsCsvBuilder
from services.analytics.core.details.job_results_cache import (
    CacheEntryRequest,
    JobResultFailures,
    JobResultsCache,
)
from services.analytics.core.model.job_result import JobResult, utc_now
from use_case_contracts.ports import ResultsRepositoryPort


class JobResultsEntryCacheBuilder:
    """Build cache entries asynchronously on a dedicated builder-owned thread."""

    def __init__(
        self,
        cache: JobResultsCache,
        results_repository: ResultsRepositoryPort,
        failures: JobResultFailures | None = None,
        on_completed=None,
    ) -> None:
        self._results_repository = results_repository
        self._cache = cache
        self._failures = failures
        self._on_completed = on_completed
        self._request: CacheEntryRequest | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def assign(self, request: CacheEntryRequest) -> None:
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

    def _build(self, request: CacheEntryRequest) -> None:
        try:
            main_results_builder = MainResultsCsvBuilder()
            sources: list[str] = []
            for url in request.results_urls:
                base_url = url.rsplit("/", 1)[0]
                content = self._results_repository.download(url).decode("utf-8")
                postprocessed = self._postprocess_csv_with_s3_urls(base_url, content)
                sources.append(postprocessed)
            main_results = main_results_builder.build(sources)
            evaluator = JobResultParametersEvaluator(
                main_results=main_results,
                job_id=request.job_id
            )
            evaluated_values = evaluator.evaluateParameters(
                request.input_parameters,
                request.output_parameters,
            )
            repetitions = evaluator.getRepetitions()
            self._cache.put(
                job_id=request.job_id,
                job_result=JobResult(
                    job_id=request.job_id,
                    job_root_url=request.job_root_url,
                    main_results=main_results,
                    input_parameters=evaluated_values.input_parameters,
                    output_parameters=evaluated_values.output_parameters,
                    creation_time=utc_now(),
                    repetitions=repetitions
                )
            )
        except Exception as exc:
            # A failed build must surface as a distinct state rather than being
            # silently forgotten. The builder always clears its assignment below,
            # so without this record the job would look 'unknown' (and the front
            # end would keep reloading, re-enqueueing the same doomed build).
            if self._failures is not None:
                self._failures.put(request.job_id, str(exc))
        finally:
            self._clear_assignment()
            if self._on_completed is not None:
                self._on_completed(request.job_id)

    def _postprocess_csv_with_s3_urls(self, base_url: str, file_content: str) -> str:
        base_url = base_url.rstrip("/")

        input_io = io.StringIO(file_content)
        output_io = io.StringIO()

        reader = csv.reader(input_io, delimiter=";")
        writer = csv.writer(output_io, delimiter=";", lineterminator="\n")

        for row in reader:
            processed_row = []
            for cell in row:
                stripped = cell.strip()
                if stripped.lower().endswith(".csv"):
                    processed_row.append(f"{base_url}/{stripped}.zip")
                else:
                    processed_row.append(cell)
            writer.writerow(processed_row)

        return output_io.getvalue()
