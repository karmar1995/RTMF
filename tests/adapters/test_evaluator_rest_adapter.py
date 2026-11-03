from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from adapters.evaluator_rest_adapter.composition_root import (
    EvaluatorRestAdapterContainer,
)
from use_case_contracts.errors import (
    AuthenticationError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from use_case_contracts.ports import EvaluatorPort


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _port(
    monkeypatch: pytest.MonkeyPatch, response: _Response | Exception
) -> tuple[EvaluatorPort, list[Any]]:
    captured: list[Any] = []

    def fake_urlopen(request: urllib.request.Request, timeout: int) -> _Response:
        captured.append((request, timeout))
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    container = EvaluatorRestAdapterContainer()
    container.config.from_dict(
        {
            "base_url": "http://evaluator",
            "timeout_seconds": 7,
            "auth_token": "token",
        }
    )
    return container.evaluator_port(), captured


def _http_error(status: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "http://evaluator/evaluations/",
        status,
        "error",
        hdrs=None,
        fp=io.BytesIO(body),
    )


def _multipart_text_field(body: bytes, name: str) -> str:
    text = body.decode("utf-8")
    start = text.index(f'Content-Disposition: form-data; name="{name}"')
    body_start = text.index("\r\n\r\n", start) + 4
    end = text.index("\r\n--", body_start)
    return text[body_start:end]


def test_given_problem_when_evaluate_then_multipart_with_config_file_is_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port, captured = _port(
        monkeypatch,
        _Response(json.dumps({"evaluation_id": "a" * 16}).encode("utf-8")),
    )

    result = port.evaluate(
        "sim-1",
        number_of_repetitions=64,
        kmax=20,
        epsilon=0.01,
        batch_size=2,
        lhs_candidates=1000,
        random_state=7,
        problem={"names": ["x"], "bounds": [[0.0, 1.0]], "output": "y"},
    )

    request, timeout = captured[0]
    body = request.data
    assert result == "a" * 16
    assert timeout == 7
    assert request.full_url == "http://evaluator/evaluations/"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer token"
    assert request.get_header("Content-type").startswith("multipart/form-data")
    assert _multipart_text_field(body, "simulator_id") == "sim-1"
    assert _multipart_text_field(body, "number_of_repetitions") == "64"
    assert _multipart_text_field(body, "kmax") == "20"
    assert _multipart_text_field(body, "epsilon") == "0.01"
    assert _multipart_text_field(body, "batch_size") == "2"
    assert _multipart_text_field(body, "lhs_candidates") == "1000"
    assert _multipart_text_field(body, "random_state") == "7"
    assert b'name="config_file"; filename="problem.json"' in body
    assert b'"names"' in body
    assert b'"bounds"' in body


def test_given_no_problem_when_evaluate_then_config_file_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port, captured = _port(
        monkeypatch,
        _Response(json.dumps({"evaluation_id": "b" * 16}).encode("utf-8")),
    )

    result = port.evaluate("sim-1")

    body = captured[0][0].data
    assert result == "b" * 16
    assert b"config_file" not in body


def test_given_status_response_when_read_then_status_is_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port, captured = _port(
        monkeypatch,
        _Response(
            json.dumps({"evaluation_id": "c" * 16, "status": "running"}).encode("utf-8")
        ),
    )

    status = port.get_evaluation_status("c" * 16)

    request = captured[0][0]
    assert status == "running"
    assert request.full_url == f"http://evaluator/evaluations/{'c' * 16}/status"
    assert request.get_method() == "GET"


def test_given_progress_response_when_read_then_progress_is_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "evaluation_id": "c" * 16,
        "status": "optimizing",
        "stage": "optimizing",
        "iteration": 3,
        "kmax": 30,
        "best_params": {"x": 1.5},
        "best_value": 0.25,
        "important_parameters": ["x"],
        "ssbo_history": [
            {
                "iteration": 0,
                "best_value": 0.9,
                "new_point": [0.1],
                "new_value": 0.9,
            }
        ],
        "jobs_submitted": 13,
        "jobs_by_stage": {"sensitivity": 1, "ssbo": 12},
    }
    port, captured = _port(
        monkeypatch,
        _Response(json.dumps(payload).encode("utf-8")),
    )

    progress = port.get_evaluation_progress("c" * 16)

    request = captured[0][0]
    assert request.full_url == f"http://evaluator/evaluations/{'c' * 16}/progress"
    assert progress.status == "optimizing"
    assert progress.stage == "optimizing"
    assert progress.iteration == 3
    assert progress.kmax == 30
    assert progress.best_value == 0.25
    assert progress.important_parameters == ["x"]
    assert progress.ssbo_history[0]["new_point"] == [0.1]
    assert progress.jobs_submitted == 13
    assert progress.jobs_by_stage == {"sensitivity": 1, "ssbo": 12}


def test_given_minimal_progress_response_when_read_then_defaults_are_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port, _captured = _port(
        monkeypatch,
        _Response(json.dumps({"evaluation_id": "c" * 16, "status": "queued"}).encode()),
    )

    progress = port.get_evaluation_progress("c" * 16)

    assert progress.iteration == 0
    assert progress.kmax == 0
    assert progress.best_value is None
    assert progress.ssbo_history == []
    assert progress.jobs_submitted == 0
    assert progress.jobs_by_stage == {}


def test_given_malformed_progress_when_read_then_error_is_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port, _captured = _port(
        monkeypatch,
        _Response(json.dumps({"status": "optimizing"}).encode()),
    )

    with pytest.raises(ExternalServiceError):
        port.get_evaluation_progress("c" * 16)


def test_given_results_response_when_read_then_result_is_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "evaluation_id": "d" * 16,
        "status": "success",
        "details": {
            "best_params": {"x": 1.5},
            "best_value": 0.25,
            "iterations": 30,
            "history": [{"iteration": 1, "best_value": 0.5, "skipped": False}],
        },
    }
    port, _captured = _port(
        monkeypatch,
        _Response(json.dumps(payload).encode("utf-8")),
    )

    result = port.get_evaluation_results("d" * 16)

    assert result.evaluation_id == "d" * 16
    assert result.status == "success"
    assert result.details["best_params"] == {"x": 1.5}
    assert result.details["history"][0]["iteration"] == 1


def test_given_list_response_when_read_then_summaries_are_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "evaluations": [
            {
                "evaluation_id": "e" * 16,
                "simulator_id": "sim-1",
                "status": "success",
                "created_at": "2026-01-01T10:00:00Z",
            },
            {
                "evaluation_id": "f" * 16,
                "simulator_id": "sim-2",
                "status": "queued",
                "created_at": None,
            },
        ]
    }
    port, captured = _port(
        monkeypatch,
        _Response(json.dumps(payload).encode("utf-8")),
    )

    summaries = port.list_evaluations()

    assert captured[0][0].full_url == "http://evaluator/evaluations/"
    assert len(summaries) == 2
    assert summaries[0].evaluation_id == "e" * 16
    assert summaries[0].simulator_id == "sim-1"
    assert summaries[0].status == "success"
    assert summaries[0].created_at.isoformat().startswith("2026-01-01T10:00:00")
    assert summaries[1].status == "queued"
    assert summaries[1].created_at is None


@pytest.mark.parametrize(
    ("response", "expected_error"),
    [
        (_http_error(404, b"missing"), NotFoundError),
        (_http_error(409, b"not complete"), ConflictError),
        (_http_error(400, b"bad"), ValidationError),
        (_http_error(401, b"denied"), AuthenticationError),
        (_http_error(500, b"boom"), ExternalServiceError),
        (urllib.error.URLError("connection refused"), ExternalServiceError),
        (_Response(b"not-json"), ExternalServiceError),
    ],
)
def test_given_failure_response_when_calling_port_then_error_is_raised(
    monkeypatch: pytest.MonkeyPatch,
    response: _Response | Exception,
    expected_error: type[Exception],
) -> None:
    port, _captured = _port(monkeypatch, response)

    with pytest.raises(expected_error):
        port.get_evaluation_status("a" * 16)


def test_given_composition_root_configuration_when_resolving_port_then_evaluator_port_is_exposed() -> None:
    container = EvaluatorRestAdapterContainer()
    container.config.from_dict(
        {
            "base_url": "http://evaluator",
            "timeout_seconds": 3,
            "auth_token": "",
        }
    )

    port = container.evaluator_port()

    assert isinstance(port, EvaluatorPort)
