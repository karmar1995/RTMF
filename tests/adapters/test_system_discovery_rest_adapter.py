from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from adapters.system_discovery_rest_adapter.composition_root import (
    SystemDiscoveryRestAdapterContainer,
)
from adapters.system_discovery_rest_adapter.errors import (
    SystemDiscoveryProtocolError,
    SystemDiscoveryRequestRejectedError,
    SystemDiscoveryResourceNotFoundError,
    SystemDiscoveryServiceUnavailableError,
)
from adapters.system_discovery_rest_adapter.mapping.serialization import (
    serialize_system_parameters,
)
from use_case_contracts.dtos import (
    SystemDiscoveryParameters,
    SystemDiscoverySimulationRequest,
    SystemDiscoveryTrainingRequest,
)
from use_case_contracts.ports import SystemDiscoveryPort


class _Headers:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get_content_type(self) -> str:
        return self._content_type


class _Response:
    def __init__(self, body: bytes, content_type: str = "application/json") -> None:
        self._body = body
        self.headers = _Headers(content_type)

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _port(monkeypatch: pytest.MonkeyPatch, response: _Response | Exception) -> tuple[SystemDiscoveryPort, list[Any]]:
    captured: list[Any] = []

    def fake_urlopen(request: urllib.request.Request, timeout: int) -> _Response:
        captured.append((request, timeout))
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    container = SystemDiscoveryRestAdapterContainer()
    container.config.from_dict(
        {
            "base_url": "http://system-discovery",
            "timeout_seconds": 7,
            "auth_token": "token",
        }
    )
    return container.system_discovery_port(), captured


def _http_error(status: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "http://system-discovery/api",
        status,
        "error",
        hdrs=None,
        fp=io.BytesIO(body),
    )


def _multipart_text_field(body: bytes, name: str) -> str:
    text = body.decode("utf-8")
    marker = f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
    start = text.index(marker) + len(marker)
    end = text.index("\r\n--", start)
    return text[start:end]


def test_given_parameters_without_nlags_x_when_serialized_then_python_literal_none_is_used() -> None:
    value = serialize_system_parameters(
        SystemDiscoveryParameters(
            nlags_x=None,
            nlags_y=1,
            basis="Polynomial",
            degree=1,
            model="my_model_name",
        )
    )

    assert value == (
        "{'nlags-x': None, 'nlags-y': 1, 'basis': 'Polynomial', "
        "'degree': 1, 'model': 'my_model_name'}"
    )
    assert '"nlags-x"' not in value
    assert "null" not in value


def test_given_parameters_with_nlags_x_when_serialized_then_nested_lists_are_used() -> None:
    value = serialize_system_parameters(
        SystemDiscoveryParameters(
            nlags_x=((1, 2), (1, 2)),
            nlags_y=1,
            basis="Polynomial",
            degree=1,
            model="my_model_name",
        )
    )

    assert value == (
        "{'nlags-x': [[1, 2], [1, 2]], 'nlags-y': 1, 'basis': 'Polynomial', "
        "'degree': 1, 'model': 'my_model_name'}"
    )


def test_given_training_request_when_submitted_then_it_maps_archive_parameters_and_submission_response(monkeypatch: pytest.MonkeyPatch) -> None:
    port, captured = _port(
        monkeypatch,
        _Response(json.dumps({"sd_training_id": "train-1", "status": "queued"}).encode("utf-8")),
    )

    result = port.submit_training(
        SystemDiscoveryTrainingRequest(
            training_data_archive=b"zip-bytes",
            system_parameters=SystemDiscoveryParameters(
                nlags_x=((1, 2), (3, 4)),
                nlags_y=1,
                basis="Polynomial",
                degree=2,
                model="model-a",
            ),
        )
    )

    request, timeout = captured[0]
    body = request.data
    assert result.training_id == "train-1"
    assert result.status == "queued"
    assert timeout == 7
    assert request.full_url == "http://system-discovery/api/v1/train"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer token"
    assert b'name="data"; filename="training_data.zip"' in body
    assert b"zip-bytes" in body
    assert b'name="system_parameters"' in body
    assert _multipart_text_field(body, "system_parameters") == (
        "{'nlags-x': [[1, 2], [3, 4]], 'nlags-y': 1, 'basis': 'Polynomial', "
        "'degree': 2, 'model': 'model-a'}"
    )


def test_given_training_request_without_nlags_x_when_submitted_then_parameters_contain_python_none(monkeypatch: pytest.MonkeyPatch) -> None:
    port, captured = _port(
        monkeypatch,
        _Response(json.dumps({"sd_training_id": "train-1", "status": "queued"}).encode("utf-8")),
    )

    port.submit_training(
        SystemDiscoveryTrainingRequest(
            training_data_archive=b"zip-bytes",
            system_parameters=SystemDiscoveryParameters(
                nlags_x=None,
                nlags_y=1,
                basis="Polynomial",
                degree=2,
                model="model-a",
            ),
        )
    )

    body = captured[0][0].data
    system_parameters = _multipart_text_field(body, "system_parameters")
    assert system_parameters == (
        "{'nlags-x': None, 'nlags-y': 1, 'basis': 'Polynomial', "
        "'degree': 2, 'model': 'model-a'}"
    )
    assert "'nlags-x': None" in system_parameters
    assert '"nlags-x": null' not in system_parameters
    assert "null" not in system_parameters


def test_given_training_status_response_when_read_then_requested_training_id_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    port, _captured = _port(
        monkeypatch,
        _Response(
            json.dumps(
                {
                    "job_id": "external-job-name",
                    "status": "running",
                    "training_status": "training",
                    "evaluation_status": "waiting",
                    "error": None,
                }
            ).encode("utf-8")
        ),
    )

    status = port.get_training_status("train-1")

    assert status.training_id == "train-1"
    assert status.status == "running"
    assert status.training_status == "training"
    assert status.evaluation_status == "waiting"
    assert status.error is None


def test_given_training_results_zip_when_downloaded_then_raw_bytes_are_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    port, _captured = _port(monkeypatch, _Response(b"zip-result", "application/zip"))

    result = port.download_training_results("train-1")

    assert result.content == b"zip-result"


def test_given_simulation_request_without_optional_fields_when_submitted_then_optional_form_fields_are_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    port, captured = _port(
        monkeypatch,
        _Response(json.dumps({"sd_simulation_id": "sim-1", "status": "queued"}).encode("utf-8")),
    )

    result = port.submit_system_discovery_simulation(
        SystemDiscoverySimulationRequest(
            model_and_input_archive=b"simulation-zip",
            horizon=None,
            initial_conditions=None,
        )
    )

    body = captured[0][0].data
    assert result.simulation_id == "sim-1"
    assert result.status == "queued"
    assert b'name="data"; filename="simulation_data.zip"' in body
    assert b"simulation-zip" in body
    assert b'name="horizon"' not in body
    assert b'name="initial_conditions"' not in body


def test_given_simulation_request_with_optional_fields_when_submitted_then_fields_are_serialized(monkeypatch: pytest.MonkeyPatch) -> None:
    port, captured = _port(
        monkeypatch,
        _Response(json.dumps({"sd_simulation_id": "sim-2", "status": "queued"}).encode("utf-8")),
    )

    port.submit_system_discovery_simulation(
        SystemDiscoverySimulationRequest(
            model_and_input_archive=b"simulation-zip",
            horizon=12,
            initial_conditions=(0.7, 2.1, 3.5),
        )
    )

    body = captured[0][0].data
    assert b'name="horizon"' in body
    assert b"\r\n12\r\n" in body
    assert b'name="initial_conditions"' in body
    assert b"\r\n0.7 2.1 3.5\r\n" in body


def test_given_simulation_status_response_when_read_then_status_is_mapped(monkeypatch: pytest.MonkeyPatch) -> None:
    port, _captured = _port(
        monkeypatch,
        _Response(
            json.dumps(
                {
                    "sd_simulation_id": "sim-1",
                    "status": "running",
                    "error": "pending input",
                }
            ).encode("utf-8")
        ),
    )

    status = port.get_system_discovery_simulation_status("sim-1")

    assert status.simulation_id == "sim-1"
    assert status.status == "running"
    assert status.error == "pending input"


def test_given_simulation_results_zip_when_downloaded_then_raw_bytes_are_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    port, _captured = _port(monkeypatch, _Response(b"simulation-results", "application/zip"))

    result = port.download_system_discovery_simulation_results("sim-1")

    assert result.content == b"simulation-results"


@pytest.mark.parametrize(
    ("response", "expected_error"),
    [
        (_http_error(422, b"invalid request"), SystemDiscoveryRequestRejectedError),
        (_http_error(404, b"missing"), SystemDiscoveryResourceNotFoundError),
        (_http_error(503, b"down"), SystemDiscoveryServiceUnavailableError),
        (urllib.error.URLError("connection refused"), SystemDiscoveryServiceUnavailableError),
        (_Response(b"not-json"), SystemDiscoveryProtocolError),
        (_Response(b"{}", "text/plain"), SystemDiscoveryProtocolError),
    ],
)
def test_given_failure_response_when_calling_port_then_boundary_safe_error_is_raised(
    monkeypatch: pytest.MonkeyPatch,
    response: _Response | Exception,
    expected_error: type[Exception],
) -> None:
    port, _captured = _port(monkeypatch, response)

    with pytest.raises(expected_error):
        port.get_system_discovery_simulation_status("sim-1")


def test_given_non_zip_media_type_when_downloading_archive_then_protocol_error_is_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    port, _captured = _port(monkeypatch, _Response(b"plain", "text/plain"))

    with pytest.raises(SystemDiscoveryProtocolError):
        port.download_training_results("train-1")


def test_given_composition_root_configuration_when_resolving_port_then_system_discovery_port_is_exposed() -> None:
    container = SystemDiscoveryRestAdapterContainer()
    container.config.from_dict(
        {
            "base_url": "http://system-discovery",
            "timeout_seconds": 3,
            "auth_token": "",
        }
    )

    port = container.system_discovery_port()

    assert isinstance(port, SystemDiscoveryPort)
