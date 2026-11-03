from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dependency_injector import providers

from configuration.errors import ConfigurationError

_SERVICE_SECTION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_REQUIRED_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def load_config_files_into_provider(
    config: providers.Configuration,
    *,
    service_name: str,
    main_env_var: str = "RTMF_MAIN_CONFIGURATION_FILE",
    service_env_var: str | None = None,
    main_required: bool = True,
    service_required: bool = False,
    envs_required: bool = True,
) -> None:
    """Load a deployment-local service config into a provider."""

    load_service_config_into_provider(
        config,
        service_name=service_name,
        main_env_var=main_env_var,
        service_env_var=service_env_var,
        main_required=main_required,
        service_required=service_required,
        envs_required=envs_required,
    )


def load_service_config_into_provider(
    config: providers.Configuration,
    *,
    service_name: str,
    extra_service_sections: tuple[str, ...] = (),
    extra_top_level_sections: tuple[str, ...] = (),
    main_env_var: str = "RTMF_MAIN_CONFIGURATION_FILE",
    service_env_var: str | None = None,
    main_required: bool = True,
    service_required: bool = False,
    envs_required: bool = True,
) -> None:
    """Load only selected sections into a Configuration provider.

    By default this loads only services.<service_name> and ignores every other
    service section. Passing service_env_var enables the legacy override merge
    path explicitly; old service-specific env vars are not consulted by default.
    """

    _validate_service_section_name(service_name)
    for section_name in extra_service_sections:
        _validate_service_section_name(section_name)
    for section_name in extra_top_level_sections:
        _validate_service_section_name(section_name)

    main_path = os.environ.get(main_env_var)
    if main_required and not _has_text(main_path):
        raise ConfigurationError(f"Missing required environment variable: {main_env_var}")

    raw_main: dict[str, Any] = {}
    if _has_text(main_path):
        raw_main = _read_json_object(main_path.strip(), label="main configuration")

    raw_override: dict[str, Any] = {}
    service_path = os.environ.get(service_env_var) if service_env_var else None
    if service_env_var and _has_text(service_path):
        raw_override = _read_json_object(
            service_path.strip(),
            label=f"{service_name} service override",
        )
    elif service_env_var and service_required:
        raise ConfigurationError(f"Missing required environment variable: {service_env_var}")
    elif service_required:
        raise ConfigurationError("service_env_var is required when service_required=True")

    merged = _merge_override(raw_main, raw_override, service_name=service_name)
    selected = extract_service_config(
        merged,
        service_name=service_name,
        extra_service_sections=extra_service_sections,
        extra_top_level_sections=extra_top_level_sections,
    )
    load_selected_json_into_provider(
        config,
        selected,
        envs_required=envs_required,
    )


def load_top_level_config_into_provider(
    config: providers.Configuration,
    *,
    section_name: str,
    main_env_var: str = "RTMF_MAIN_CONFIGURATION_FILE",
    main_required: bool = True,
    envs_required: bool = True,
) -> None:
    """Load one top-level deployment config section into a provider."""

    _validate_service_section_name(section_name)

    main_path = os.environ.get(main_env_var)
    if main_required and not _has_text(main_path):
        raise ConfigurationError(f"Missing required environment variable: {main_env_var}")

    raw_main: dict[str, Any] = {}
    if _has_text(main_path):
        raw_main = _read_json_object(main_path.strip(), label="main configuration")

    selected = extract_top_level_config(raw_main, section_name=section_name)
    load_selected_json_into_provider(
        config,
        selected,
        envs_required=envs_required,
    )


def extract_service_config(
    raw_config: Mapping[str, Any],
    *,
    service_name: str,
    extra_service_sections: tuple[str, ...] = (),
    extra_top_level_sections: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Extract service-local config, or explicit multi-section config."""

    services = raw_config.get("services")
    if not isinstance(services, Mapping):
        raise ConfigurationError("Missing configuration object: services")

    selected_service = _get_service_section(services, service_name)
    if not extra_service_sections and not extra_top_level_sections:
        return dict(selected_service)

    selected: dict[str, Any] = {service_name: dict(selected_service)}
    for section_name in extra_service_sections:
        selected[section_name] = dict(_get_service_section(services, section_name))
    for section_name in extra_top_level_sections:
        selected[section_name] = dict(_get_top_level_section(raw_config, section_name))
    return selected


def extract_top_level_config(
    raw_config: Mapping[str, Any],
    *,
    section_name: str,
) -> dict[str, Any]:
    """Extract one top-level config section."""

    return dict(_get_top_level_section(raw_config, section_name))


def load_selected_json_into_provider(
    config: providers.Configuration,
    selected: Mapping[str, Any],
    *,
    envs_required: bool = True,
) -> None:
    """Load selected JSON through Dependency Injector so env interpolation runs."""

    if envs_required:
        # Native Compose may pass blank values from a user's .env template.
        # Check only the selected service, while keeping explicit defaults optional.
        required = set(_REQUIRED_ENV_RE.findall(json.dumps(selected)))
        missing = sorted(name for name in required if not os.environ.get(name, "").strip())
        if missing:
            raise ConfigurationError("Missing or empty required environment variables: " + ", ".join(missing))

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        delete=False,
    ) as temp_file:
        json.dump(selected, temp_file)
        temp_path = temp_file.name

    try:
        config.from_json(temp_path, required=True, envs_required=envs_required)
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass


def _get_service_section(
    services: Mapping[str, Any],
    service_name: str,
) -> Mapping[str, Any]:
    selected = services.get(service_name)
    if selected is None:
        raise ConfigurationError(
            f"Missing service configuration section: services.{service_name}"
        )
    if not isinstance(selected, Mapping):
        raise ConfigurationError(
            f"Service configuration section must be an object: services.{service_name}"
        )
    return selected


def _get_top_level_section(
    raw_config: Mapping[str, Any],
    section_name: str,
) -> Mapping[str, Any]:
    selected = raw_config.get(section_name)
    if selected is None:
        raise ConfigurationError(f"Missing configuration section: {section_name}")
    if not isinstance(selected, Mapping):
        raise ConfigurationError(
            f"Configuration section must be an object: {section_name}"
        )
    return selected


def _merge_override(
    raw_main: Mapping[str, Any],
    raw_override: Mapping[str, Any],
    *,
    service_name: str,
) -> dict[str, Any]:
    if not raw_override:
        return dict(raw_main)
    if "services" in raw_override:
        return _deep_merge(dict(raw_main), raw_override)

    merged = dict(raw_main)
    services = merged.setdefault("services", {})
    if not isinstance(services, dict):
        raise ConfigurationError("Configuration section must be an object: services")

    existing = services.get(service_name, {})
    if existing is None:
        existing = {}
    if not isinstance(existing, Mapping):
        raise ConfigurationError(
            f"Service configuration section must be an object: services.{service_name}"
        )
    services[service_name] = _deep_merge(dict(existing), raw_override)
    return merged


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, Mapping)
        ):
            base[key] = _deep_merge(dict(base[key]), value)
        else:
            base[key] = value
    return base


def _read_json_object(path: str, *, label: str) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigurationError(f"Missing {label} file: {path}")
    try:
        with config_path.open("r", encoding="utf-8") as config_file:
            payload = json.load(config_file)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Invalid JSON in {label} file {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ConfigurationError(
            f"{label.capitalize()} file must contain a JSON object: {path}"
        )
    return payload


def _validate_service_section_name(service_name: str) -> None:
    if not isinstance(service_name, str) or not service_name.strip():
        raise ConfigurationError("service_name must be a non-empty string")
    if (
        service_name.strip() != service_name
        or not _SERVICE_SECTION_RE.fullmatch(service_name)
    ):
        raise ConfigurationError(f"Invalid service_name: {service_name!r}")


def _has_text(value: str | None) -> bool:
    return value is not None and value.strip() != ""
