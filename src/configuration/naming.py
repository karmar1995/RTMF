from __future__ import annotations

import re

from configuration.errors import ConfigurationError


_SEPARATORS_RE = re.compile(r"[^A-Za-z0-9]+")


def normalize_service_name(service_name: str) -> str:
    if not isinstance(service_name, str) or not service_name.strip():
        raise ConfigurationError("service_name must be a non-empty string")
    normalized = _SEPARATORS_RE.sub("_", service_name.strip()).strip("_").upper()
    if not normalized:
        raise ConfigurationError(f"Invalid service_name: {service_name!r}")
    return normalized


def service_configuration_env_var(service_name: str) -> str:
    return f"RTMF_{normalize_service_name(service_name)}_CONFIGURATION_FILE"
