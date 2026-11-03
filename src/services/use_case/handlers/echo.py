from __future__ import annotations

from use_case_contracts.dtos import EchoResult
from use_case_contracts.messages import Echo


def handle_echo(message: Echo) -> EchoResult:
    return EchoResult(payload=message.payload)
