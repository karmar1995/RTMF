from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any
import logging
import urllib.parse

import requests

from use_case_contracts.ports import MatrixGenerationPort
from use_case_contracts.dtos import (
    GeneratedMatrixFile,
    MatrixParameterDefinition,
    SensitivityAnalysisParameter,
)
from use_case_contracts.errors import ExternalServiceError

_LINEAR_COMBINATIONS_PATH = "/matrices/linear-combinations"
_SENSITIVITY_ANALYSIS_PATH = "/matrices/sensitivity-analysis"
_SATELLI_COMBINATIONS_PATH = "/matrices/satelli-combinations"
_UPLOAD_MATRIX_PATH = "/matrices/upload"


class MatrixGeneratorAdapterError(ExternalServiceError):
    pass


class MatrixGeneratorServiceUnavailable(MatrixGeneratorAdapterError):
    pass


class MatrixGeneratorInvalidResponse(MatrixGeneratorAdapterError):
    pass


class MatrixGeneratorRestAdapter(MatrixGenerationPort):
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float | int = 30,
        http_client: requests.Session | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._base_url = _normalize_base_url(base_url)
        self._timeout_seconds = timeout_seconds
        self._http = http_client or requests.Session()
        self._logger = logger or logging.getLogger(__name__)

    def generate_linear_combinations(
        self,
        matrix_id: str,
        repetitions: int,
        parameter_definitions: list[MatrixParameterDefinition],
        fixed_params: dict[str, str],
        sweep_params: dict[str, list[str]],
    ) -> GeneratedMatrixFile:
        payload = {
            "matrix_id": matrix_id,
            "repetitions": repetitions,
            "parameter_definitions": [
                _serialize_dataclass_item(definition)
                for definition in parameter_definitions
            ],
            "fixed_params": dict(fixed_params),
            "sweep_params": {name: list(values) for name, values in sweep_params.items()},
        }
        response_payload = self._post_json(
            operation="generate_linear_combinations",
            path=_LINEAR_COMBINATIONS_PATH,
            payload=payload,
        )
        return _parse_generated_matrix_file(response_payload)

    def generate_sensitivity_analysis(
        self,
        matrix_id: str,
        parameters: list[SensitivityAnalysisParameter],
        sample_size: int,
        calc_second_order: bool,
        round_to_int: bool,
    ) -> GeneratedMatrixFile:
        payload = {
            "matrix_id": matrix_id,
            "sample_size": sample_size,
            "calc_second_order": calc_second_order,
            "round_to_int": round_to_int,
            "parameters": [
                _serialize_dataclass_item(parameter)
                for parameter in parameters
            ],
        }
        response_payload = self._post_json(
            operation="generate_sensitivity_analysis",
            path=_SENSITIVITY_ANALYSIS_PATH,
            payload=payload,
        )
        return _parse_generated_matrix_file(response_payload)

    def generate_satelli_matrix_combinations(
        self,
        matrix_id: str,
        repetitions: int,
        parameter_definitions: list[MatrixParameterDefinition],
        fixed_params: dict[str, str],
        sweep_params: dict[str, list[str]],
        sample_size: int = 128,
        seed: int | None = None,
    ) -> GeneratedMatrixFile:
        payload: dict[str, object] = {
            "matrix_id": matrix_id,
            "repetitions": repetitions,
            "parameter_definitions": [
                _serialize_dataclass_item(definition)
                for definition in parameter_definitions
            ],
            "fixed_params": dict(fixed_params),
            "sweep_params": {
                name: list(values) for name, values in sweep_params.items()
            },
            "sample_size": sample_size,
        }
        if seed is not None:
            payload["seed"] = seed
        response_payload = self._post_json(
            operation="generate_satelli_matrix_combinations",
            path=_SATELLI_COMBINATIONS_PATH,
            payload=payload,
        )
        return _parse_generated_matrix_file(response_payload)

    def upload_matrix(
        self,
        matrix_id: str,
        matrix_text: str,
    ) -> GeneratedMatrixFile:
        payload = {
            "matrix_id": matrix_id,
            "matrix_text": matrix_text,
        }
        response_payload = self._post_json(
            operation="upload_matrix",
            path=_UPLOAD_MATRIX_PATH,
            payload=payload,
        )
        return _parse_generated_matrix_file(response_payload)

    def _post_json(
        self,
        *,
        operation: str,
        path: str,
        payload: dict[str, Any],
    ) -> Any:
        url = self._build_url(path)
        try:
            response = self._http.post(
                url,
                json=payload,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise MatrixGeneratorServiceUnavailable(
                f"Matrix Generator request timed out during {operation} ({url})"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise MatrixGeneratorServiceUnavailable(
                f"Matrix Generator connection failed during {operation} ({url}): {exc}"
            ) from exc
        except requests.exceptions.HTTPError as exc:
            raise MatrixGeneratorAdapterError(
                _format_http_error(
                    operation=operation,
                    url=url,
                    status_code=response.status_code,
                    response_text=response.text,
                )
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise MatrixGeneratorAdapterError(
                f"Matrix Generator request failed during {operation} ({url}): {exc}"
            ) from exc

        try:
            return response.json()
        except ValueError as exc:
            raise MatrixGeneratorInvalidResponse(
                f"Matrix Generator returned malformed JSON during {operation} ({url})"
            ) from exc

    def _build_url(self, path: str) -> str:
        return urllib.parse.urljoin(f"{self._base_url}/", path.lstrip("/"))


def _normalize_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        raise ValueError("Matrix Generator base URL must not be empty")
    return normalized


def _serialize_dataclass_item(
    item: MatrixParameterDefinition | SensitivityAnalysisParameter,
) -> dict[str, Any]:
    if is_dataclass(item):
        return asdict(item)
    raise TypeError(f"Expected dataclass DTO, got {type(item)!r}")


def _parse_generated_matrix_file(payload: Any) -> GeneratedMatrixFile:
    if not isinstance(payload, dict):
        raise MatrixGeneratorInvalidResponse(
            "Matrix Generator returned invalid response payload: expected JSON object"
        )

    matrix_url = payload.get("matrix_url")
    if not isinstance(matrix_url, str) or not matrix_url.strip():
        raise MatrixGeneratorInvalidResponse(
            "Matrix Generator response missing non-empty 'matrix_url'"
        )
    return GeneratedMatrixFile(matrix_url=matrix_url)


def _format_http_error(
    *,
    operation: str,
    url: str,
    status_code: int,
    response_text: str | None,
) -> str:
    snippet = (response_text or "").strip()
    if len(snippet) > 200:
        snippet = f"{snippet[:200]}..."
    if snippet:
        return (
            f"Matrix Generator request failed during {operation} "
            f"({url}, status={status_code}, body={snippet})"
        )
    return f"Matrix Generator request failed during {operation} ({url}, status={status_code})"
