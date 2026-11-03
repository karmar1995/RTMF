from __future__ import annotations

import importlib.util
import io
import logging
import sys
import threading
import types
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from urllib.error import HTTPError, URLError

import pytest

from services.jobs_scheduler.core.errors import (
    SlurmConfigurationError,
    SlurmTokenUnavailableError,
)
from services.jobs_scheduler.rest_api.error_mapping import to_http_exception


ROOT = Path(__file__).resolve().parents[2]


def _load_adapter_modules():
    package_name = "adapters.slurm_adapter"
    token_name = f"{package_name}.slurm_token_refresher"
    rest_name = f"{package_name}.slurm_rest_client"
    saved = {name: sys.modules.get(name) for name in (package_name, token_name, rest_name)}

    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(ROOT / "src" / "adapters" / "slurm_adapter")]
        sys.modules[package_name] = package

    token_spec = importlib.util.spec_from_file_location(
        token_name,
        ROOT / "src" / "adapters" / "slurm_adapter" / "slurm_token_refresher.py",
    )
    assert token_spec is not None and token_spec.loader is not None
    token_module = importlib.util.module_from_spec(token_spec)
    sys.modules[token_name] = token_module
    token_spec.loader.exec_module(token_module)

    rest_spec = importlib.util.spec_from_file_location(
        rest_name,
        ROOT / "src" / "adapters" / "slurm_adapter" / "slurm_rest_client.py",
    )
    assert rest_spec is not None and rest_spec.loader is not None
    rest_module = importlib.util.module_from_spec(rest_spec)
    sys.modules[rest_name] = rest_module
    try:
        rest_spec.loader.exec_module(rest_module)
        return token_module, rest_module
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


token_module, rest_module = _load_adapter_modules()
SlurmTokenRefresher = token_module.SlurmTokenRefresher
SlurmRestClient = rest_module.SlurmRestClient
SlurmRestError = rest_module.SlurmRestError
SlurmRestConnectionError = rest_module.SlurmRestConnectionError
SlurmRestProtocolError = rest_module.SlurmRestProtocolError


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_token_cache_reuse(monkeypatch) -> None:
    calls = 0

    def fake_run(command, **kwargs):
        nonlocal calls
        calls += 1
        assert "username=" not in " ".join(command)
        assert "SLURM_JWT" not in kwargs["env"]
        return CompletedProcess(command, 0, stdout="SLURM_JWT=token-1\n", stderr="")

    monkeypatch.setattr(token_module.subprocess, "run", fake_run)
    refresher = SlurmTokenRefresher(command_timeout_seconds=3)

    assert refresher.get_secret() == "token-1"
    assert refresher.get_secret() == "token-1"
    assert calls == 1


def test_token_refresh_before_expiry(monkeypatch) -> None:
    calls = 0
    clock = FakeClock()

    def fake_run(command, **_kwargs):
        nonlocal calls
        calls += 1
        return CompletedProcess(command, 0, stdout=f"SLURM_JWT=token-{calls}\n", stderr="")

    monkeypatch.setattr(token_module.subprocess, "run", fake_run)
    monkeypatch.setattr(token_module.time, "monotonic", clock)
    refresher = SlurmTokenRefresher(lifespan_seconds=900, refresh_after_seconds=600)

    assert refresher.get_secret() == "token-1"
    clock.advance(601)
    assert refresher.get_secret() == "token-2"
    assert calls == 2


def test_concurrent_token_requests_generate_once(monkeypatch) -> None:
    calls = 0
    started = threading.Event()
    release = threading.Event()

    def fake_run(command, **_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=2)
        return CompletedProcess(command, 0, stdout="SLURM_JWT=shared-token\n", stderr="")

    monkeypatch.setattr(token_module.subprocess, "run", fake_run)
    refresher = SlurmTokenRefresher()
    results: list[str] = []

    threads = [threading.Thread(target=lambda: results.append(refresher.get_secret())) for _ in range(5)]
    for thread in threads:
        thread.start()
    assert started.wait(timeout=2)
    release.set()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert results == ["shared-token"] * 5
    assert calls == 1


def test_scontrol_timeout_maps_to_token_unavailable(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        raise TimeoutExpired(command, kwargs["timeout"], stderr="timeout detail")

    monkeypatch.setattr(token_module.subprocess, "run", fake_run)
    refresher = SlurmTokenRefresher(command_timeout_seconds=1)

    with pytest.raises(SlurmTokenUnavailableError) as exc_info:
        refresher.get_secret()

    assert exc_info.value.diagnostic_context["command"] == "scontrol"
    assert exc_info.value.diagnostic_context["timeout_seconds"] == 1


def test_nonzero_scontrol_exit_maps_to_configuration_error(monkeypatch) -> None:
    def fake_run(command, **_kwargs):
        return CompletedProcess(command, 2, stdout="", stderr="slurm.conf not found")

    monkeypatch.setattr(token_module.subprocess, "run", fake_run)
    refresher = SlurmTokenRefresher()

    with pytest.raises(SlurmConfigurationError) as exc_info:
        refresher.get_secret()

    assert exc_info.value.diagnostic_context["returncode"] == 2
    assert exc_info.value.diagnostic_context["stderr_excerpt"] == "slurm.conf not found"


def test_malformed_scontrol_output_maps_to_configuration_error(monkeypatch) -> None:
    def fake_run(command, **_kwargs):
        return CompletedProcess(command, 0, stdout="not-a-token\n", stderr="")

    monkeypatch.setattr(token_module.subprocess, "run", fake_run)
    refresher = SlurmTokenRefresher()

    with pytest.raises(SlurmConfigurationError):
        refresher.get_secret()


def test_token_value_never_appears_in_errors_logs_or_response(monkeypatch, caplog) -> None:
    secret = "secret-token-value"

    def fake_run(command, **_kwargs):
        return CompletedProcess(command, 0, stdout=f"unexpected {secret}\n", stderr="")

    monkeypatch.setattr(token_module.subprocess, "run", fake_run)
    refresher = SlurmTokenRefresher()

    with pytest.raises(SlurmConfigurationError) as exc_info:
        refresher.get_secret()

    error = exc_info.value
    assert secret not in str(error)
    assert secret not in repr(error.diagnostic_context)
    caplog.set_level(logging.ERROR)
    response = to_http_exception(error)
    assert response.status_code == 500
    assert secret not in caplog.text
    assert secret not in response.detail


class FakeTokenRefresher:
    def __init__(self) -> None:
        self.tokens = ["expired-token", "fresh-token"]
        self.calls = 0
        self.invalidated: list[str | None] = []

    def get_secret(self) -> str:
        token = self.tokens[min(self.calls, len(self.tokens) - 1)]
        self.calls += 1
        return token

    def invalidate_secret(self, secret: str | None = None) -> None:
        self.invalidated.append(secret)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self.payload


def _http_error(url: str, code: int) -> HTTPError:
    return HTTPError(url, code, "error", hdrs={}, fp=io.BytesIO(b'{"error":"denied"}'))


def test_401_invalidates_token_and_retries_once(monkeypatch) -> None:
    refresher = FakeTokenRefresher()
    seen_tokens: list[str] = []

    def fake_urlopen(request, **_kwargs):
        seen_tokens.append(request.get_header("X-slurm-user-token"))
        if len(seen_tokens) == 1:
            raise _http_error(request.full_url, 401)
        return FakeResponse(b'{"jobs":[]}')

    monkeypatch.setattr(rest_module, "urlopen", fake_urlopen)
    client = SlurmRestClient(
        base_url="http://slurm:6820",
        api_version="v0.0.43",
        username="slurm_user",
        token_refresher=refresher,
    )

    assert client.list_slurm_jobs() == {"jobs": []}
    assert seen_tokens == ["expired-token", "fresh-token"]
    assert refresher.invalidated == ["expired-token"]


def test_final_403_after_retry_fails_safely(monkeypatch) -> None:
    refresher = FakeTokenRefresher()

    def fake_urlopen(request, **_kwargs):
        raise _http_error(request.full_url, 403)

    monkeypatch.setattr(rest_module, "urlopen", fake_urlopen)
    client = SlurmRestClient(
        base_url="http://slurm:6820",
        api_version="v0.0.43",
        username="slurm_user",
        token_refresher=refresher,
    )

    with pytest.raises(SlurmRestError) as exc_info:
        client.list_slurm_jobs()

    assert exc_info.value.status_code == 403
    assert refresher.invalidated == ["expired-token"]
    assert "expired-token" not in str(exc_info.value)
    assert "fresh-token" not in str(exc_info.value)


def test_slurm_network_failure_raises_connection_error(monkeypatch) -> None:
    def fake_urlopen(_request, **_kwargs):
        raise URLError("connection refused")

    monkeypatch.setattr(rest_module, "urlopen", fake_urlopen)
    client = SlurmRestClient(
        base_url="http://slurm:6820",
        api_version="v0.0.43",
        username="slurm_user",
        token_refresher=FakeTokenRefresher(),
    )

    with pytest.raises(SlurmRestConnectionError):
        client.list_slurm_jobs()


def test_invalid_slurm_json_raises_protocol_error(monkeypatch) -> None:
    def fake_urlopen(_request, **_kwargs):
        return FakeResponse(b"not-json")

    monkeypatch.setattr(rest_module, "urlopen", fake_urlopen)
    client = SlurmRestClient(
        base_url="http://slurm:6820",
        api_version="v0.0.43",
        username="slurm_user",
        token_refresher=FakeTokenRefresher(),
    )

    with pytest.raises(SlurmRestProtocolError):
        client.list_slurm_jobs()
