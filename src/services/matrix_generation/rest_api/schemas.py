from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MatrixParameterDefinitionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str


class GenerateLinearCombinationsRequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matrix_id: str
    repetitions: int
    parameter_definitions: list[MatrixParameterDefinitionSchema] = Field(default_factory=list)
    fixed_params: dict[str, str] | None = None
    sweep_params: dict[str, list[str]] | None = None
    sample_size: int = 128
    seed: int | None = None


class SensitivityAnalysisParameterSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    lower_bound: int | float
    upper_bound: int | float


class GenerateSensitivityAnalysisRequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matrix_id: str
    sample_size: int
    calc_second_order: bool = False
    round_to_int: bool = True
    parameters: list[SensitivityAnalysisParameterSchema] = Field(default_factory=list)


class UploadMatrixRequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matrix_id: str
    matrix_text: str


class GeneratedMatrixFileResponseSchema(BaseModel):
    matrix_url: str
