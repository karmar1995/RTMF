from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
import threading
import time

from services.jobs_scheduler.core.errors import (
    SlurmConfigurationError,
    SlurmTokenUnavailableError,
)


def _excerpt(value: str | bytes | None, *, limit: int = 500) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated>"


@dataclass(frozen=True)
class SlurmTokenCommandFailure:
    command_name: str
    returncode: int | None = None
    stderr_excerpt: str = ""
    timeout_seconds: float | None = None

    def context(self) -> dict[str, object]:
        result: dict[str, object] = {
            "operation": "generate_slurm_token",
            "adapter": "SlurmTokenRefresher",
            "command": self.command_name,
        }
        if self.returncode is not None:
            result["returncode"] = self.returncode
        if self.stderr_excerpt:
            result["stderr_excerpt"] = self.stderr_excerpt
        if self.timeout_seconds is not None:
            result["timeout_seconds"] = self.timeout_seconds
        return result


def _looks_like_auth_failure(stderr: str) -> bool:
    text = stderr.lower()
    return "authentication" in text or "permission denied" in text or "munge" in text

class SlurmTokenRefresher:
    def __init__(
        self,
        *,
        username: str | None = None,
        lifespan_seconds: int = 900,
        refresh_after_seconds: int = 600,
        command_timeout_seconds: float = 10.0,
        token_command: list[str] | None = None,
    ) -> None:
        if lifespan_seconds <= 0:
            raise RuntimeError("lifespan_seconds must be greater than zero.")
        if refresh_after_seconds <= 0:
            raise RuntimeError("refresh_after_seconds must be greater than zero.")
        if refresh_after_seconds > lifespan_seconds:
            raise RuntimeError(
                "refresh_after_seconds must not be greater than lifespan_seconds."
            )
        if command_timeout_seconds <= 0:
            raise RuntimeError("command_timeout_seconds must be greater than zero.")

        self._username = username.strip() if username is not None else None
        self._lifespan_seconds = lifespan_seconds
        self._refresh_after_seconds = refresh_after_seconds
        self._command_timeout_seconds = command_timeout_seconds
        self._token_command = list(token_command) if token_command is not None else None
        self._lock = threading.Lock()
        self._secret: str | None = None
        self._generated_at: float | None = None

    def get_secret(self) -> str:
        if self._is_secret_fresh():
            return self._secret or ""

        with self._lock:
            if self._is_secret_fresh():
                return self._secret or ""

            secret = self._generate_secret()
            self._secret = secret
            self._generated_at = time.monotonic()
            return secret

    def invalidate_secret(self, secret: str | None = None) -> None:
        with self._lock:
            if secret is None or secret == self._secret:
                self._secret = None
                self._generated_at = None

    def _is_secret_fresh(self) -> bool:
        if self._secret is None or self._generated_at is None:
            return False
        age_seconds = time.monotonic() - self._generated_at
        return age_seconds <= self._refresh_after_seconds

    def _generate_secret(self) -> str:
        command = self._build_command()
        command_name = command[0] if command else "<empty>"
        env = dict(os.environ)
        env.pop("SLURM_JWT", None)
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._command_timeout_seconds,
                env=env,
            )
        except FileNotFoundError as exc:
            failure = SlurmTokenCommandFailure(
                command_name=command_name,
                timeout_seconds=self._command_timeout_seconds,
            )
            raise SlurmConfigurationError(
                "Slurm token generation command was not found.",
                diagnostic_context=failure.context(),
            ) from exc
        except subprocess.TimeoutExpired as exc:
            failure = SlurmTokenCommandFailure(
                command_name=command_name,
                stderr_excerpt=_excerpt(exc.stderr),
                timeout_seconds=self._command_timeout_seconds,
            )
            raise SlurmTokenUnavailableError(
                "Slurm token generation timed out.",
                diagnostic_context=failure.context(),
            ) from exc

        if completed.returncode != 0:
            stderr_excerpt = _excerpt(completed.stderr)
            failure = SlurmTokenCommandFailure(
                command_name=command_name,
                returncode=completed.returncode,
                stderr_excerpt=stderr_excerpt,
                timeout_seconds=self._command_timeout_seconds,
            )
            if _looks_like_auth_failure(stderr_excerpt):
                raise SlurmTokenUnavailableError(
                    "Slurm token generation authentication failed.",
                    diagnostic_context=failure.context(),
                )
            raise SlurmConfigurationError(
                "Slurm token generation command failed.",
                diagnostic_context=failure.context(),
            )

        secret = self._extract_token(completed.stdout)
        if not secret:
            failure = SlurmTokenCommandFailure(
                command_name=command_name,
                timeout_seconds=self._command_timeout_seconds,
            )
            raise SlurmConfigurationError(
                "Slurm token generation returned malformed output.",
                diagnostic_context=failure.context(),
            )
        return secret

    def _build_command(self) -> list[str]:
        if self._token_command is not None:
            return list(self._token_command)

        command = ["scontrol", "token", f"lifespan={self._lifespan_seconds}"]
        return command

    @staticmethod
    def _extract_token(stdout: str) -> str:
        for line in stdout.splitlines():
            text = line.strip()
            if not text:
                continue
            if text.startswith("SLURM_JWT="):
                token = text.split("=", 1)[1].strip()
                if token and not any(char.isspace() for char in token):
                    return token
                return ""
        return ""
