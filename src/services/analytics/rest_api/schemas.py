from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ParameterDefinition(BaseModel):
    name: str
    type: str


class InitializeJobRequest(BaseModel):
    job_root_url: str
    results_urls: list[str]
    input_parameters: list[ParameterDefinition]
    output_parameters: list[ParameterDefinition]


class ConstantParameter(BaseModel):
    name: str
    value: str


class PrepareSeriesRequest(BaseModel):
    job_id: str
    x_param: str
    y_param: str
    constants: list[ConstantParameter]
    statistic: str


class MergeSeriesRequest(BaseModel):
    series_ids: list[str]


class ParameterValuesResponse(BaseModel):
    name: str
    value: list[int | float | str | bool] | None = None


class SeriesIdResponse(BaseModel):
    series_id: str


class StatusResponse(BaseModel):
    status: str


class JobResultsErrorResponse(BaseModel):
    message: str | None = None


class StatisticsResponse(BaseModel):
    statistics: list[str]


class ErrorResponse(BaseModel):
    detail: str


class EmptyResponse(BaseModel):
    status: Literal["ok"] = "ok"


class SensitivityAnalysisRequest(BaseModel):
    csv_data: str | None = None
    problem: dict
    n_real: int
    output_names: list[str] | None = None
    results_urls: list[str] | None = None
    aggregation: str | None = None


class SensitivityAnalysisResponse(BaseModel):
    mean_data_csv: str
    important_parameters: dict[str, list[str]]
    deterministic_indices_csv: str
    stochastic_indices_csv: str


class MonteCarloFilteringRequest(BaseModel):
    csv_data: str | None = None
    problem: dict
    output_column: str
    threshold: float
    direction: Literal["greater", "less"]
    results_urls: list[str] | None = None
    aggregation: str | None = None
    alpha: float = 0.05
    output_aggregations: dict[str, str] | None = None
    run_output_columns: list[str] | None = None


class MonteCarloFilteringRunResponse(BaseModel):
    index: int
    behavioural: bool
    parameters: dict[str, float] = {}
    outputs: dict[str, float] = {}


class MonteCarloFilteringStatisticResponse(BaseModel):
    parameter: str
    d_statistic: float
    p_value: float
    reject_h0: bool
    behavioural_samples: int
    non_behavioural_samples: int
    behavioural_ecdf_x: list[float] = []
    behavioural_ecdf_y: list[float] = []
    non_behavioural_ecdf_x: list[float] = []
    non_behavioural_ecdf_y: list[float] = []


class MonteCarloFilteringResponse(BaseModel):
    output_column: str
    threshold: float
    direction: str
    aggregation: str | None
    behavioural_count: int
    non_behavioural_count: int
    runs: list[MonteCarloFilteringRunResponse] = []
    parameters: list[MonteCarloFilteringStatisticResponse]
