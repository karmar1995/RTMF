from __future__ import annotations

from dataclasses import dataclass, field


MATRIX_CONTENT_TYPE = "text/plain"


@dataclass(frozen=True, slots=True)
class MatrixParameterDefinition:
    name: str
    type: str


@dataclass(frozen=True, slots=True)
class GenerateLinearCombinationsRequest:
    matrix_id: str
    repetitions: int
    parameter_definitions: list[MatrixParameterDefinition] = field(default_factory=list)
    fixed_params: dict[str, str] | None = None
    sweep_params: dict[str, list[str]] | None = None
    sample_size: int = 128
    seed: int | None = None


@dataclass(frozen=True, slots=True)
class SensitivityAnalysisParameter:
    name: str
    lower_bound: int | float
    upper_bound: int | float


@dataclass(frozen=True, slots=True)
class GenerateSensitivityAnalysisRequest:
    matrix_id: str
    parameters: list[SensitivityAnalysisParameter] = field(default_factory=list)
    sample_size: int = 1
    calc_second_order: bool = False
    round_to_int: bool = True


@dataclass(frozen=True, slots=True)
class UploadMatrixRequest:
    matrix_id: str
    matrix_text: str


@dataclass(frozen=True, slots=True)
class GeneratedMatrixFile:
    matrix_url: str

@dataclass(frozen=True)
class UploadResult:
    url: str
    etag: str | None = None
    version_id: str | None = None
