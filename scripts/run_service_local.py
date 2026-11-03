#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Sequence


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
SERVICES_DIR = SRC_DIR / "services"
DEFAULT_LOCAL_CONFIG = ROOT_DIR / "config" / "rtmf.local.json"
EXAMPLE_LOCAL_CONFIG = ROOT_DIR / "config" / "rtmf.local.example.json"


class LocalRunnerError(Exception):
    pass


def discover_runnable_services() -> list[str]:
    if not SERVICES_DIR.is_dir():
        return []
    return sorted(
        path.name
        for path in SERVICES_DIR.iterdir()
        if path.is_dir() and (path / "__main__.py").is_file()
    )


def validate_service(service_name: str) -> None:
    service_dir = SERVICES_DIR / service_name
    if not service_dir.is_dir():
        raise LocalRunnerError(
            f"Unknown service: {service_name!r}. "
            f"Expected a directory under {SERVICES_DIR.relative_to(ROOT_DIR)}."
        )
    if not (service_dir / "__main__.py").is_file():
        raise LocalRunnerError(
            f"Service {service_name!r} has no runnable module entrypoint. "
            f"Expected {service_dir.relative_to(ROOT_DIR)}/__main__.py."
        )


def compose_pythonpath(existing: str | None) -> str:
    src = str(SRC_DIR)
    if not existing:
        return src
    parts = existing.split(os.pathsep)
    if src in parts:
        return existing
    return os.pathsep.join([src, existing])


def resolve_config_path(config_arg: str | None, env: dict[str, str]) -> Path | None:
    if config_arg:
        path = Path(config_arg)
        if not path.is_absolute():
            path = ROOT_DIR / path
        if not path.is_file():
            raise LocalRunnerError(f"Requested config file does not exist: {path}")
        return path

    if DEFAULT_LOCAL_CONFIG.is_file():
        return DEFAULT_LOCAL_CONFIG

    current = env.get("RTMF_MAIN_CONFIGURATION_FILE")
    if current:
        path = Path(current)
        if not path.is_absolute():
            path = ROOT_DIR / path
        if not path.is_file():
            raise LocalRunnerError(
                "RTMF_MAIN_CONFIGURATION_FILE points to a missing file: "
                f"{path}"
            )
        return path

    raise LocalRunnerError(
        "No local configuration file selected. Create one with:\n"
        f"  cp {EXAMPLE_LOCAL_CONFIG.relative_to(ROOT_DIR)} "
        f"{DEFAULT_LOCAL_CONFIG.relative_to(ROOT_DIR)}\n"
        "or pass --config PATH, or set RTMF_MAIN_CONFIGURATION_FILE."
    )


def build_child_env(config_path: Path | None, base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env if base_env is not None else os.environ)
    env["PYTHONPATH"] = compose_pythonpath(env.get("PYTHONPATH"))
    if config_path is not None:
        env["RTMF_MAIN_CONFIGURATION_FILE"] = str(config_path)
    return env


def build_command(service_name: str, service_args: Sequence[str] = ()) -> list[str]:
    return [
        sys.executable,
        "-m",
        f"services.{service_name}",
        *service_args,
    ]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an RTMF service directly from the repository source tree."
        ),
        epilog=(
            "Examples:\n"
            "  scripts/run_service_local.py front\n"
            "  scripts/run_service_local.py --config config/rtmf.local.json front\n"
            "  scripts/run_service_local.py job_executor -- --help"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        help=(
            "Path to RTMF_MAIN_CONFIGURATION_FILE. Defaults to "
            "config/rtmf.local.json, then the existing environment variable."
        ),
    )
    parser.add_argument(
        "--list-services",
        action="store_true",
        help="List runnable services discovered from src/services/*/__main__.py.",
    )
    parser.add_argument(
        "service",
        nargs="?",
        help="Service directory name under src/services.",
    )
    parser.add_argument(
        "service_args",
        nargs=argparse.REMAINDER,
        help="Arguments after -- are forwarded to python -m services.<service>.",
    )
    help_positions = [index for index, value in enumerate(argv) if value in {"-h", "--help"}]
    delimiter = argv.index("--") if "--" in argv else None
    if help_positions and (delimiter is None or min(help_positions) < delimiter):
        parser.print_help()
        raise SystemExit(0)

    args = parser.parse_args(argv)
    if args.service_args and args.service_args[0] == "--":
        args.service_args = args.service_args[1:]
    return args


def _print_missing_dependency_hint(stderr: str) -> None:
    marker = "ModuleNotFoundError: No module named "
    if marker not in stderr:
        return
    print(
        "\nA required Python dependency appears to be missing. "
        "Install local development dependencies with:\n"
        "  python -m pip install -e .",
        file=sys.stderr,
    )


def run_child(command: list[str], env: dict[str, str]) -> int:
    process = subprocess.Popen(command, cwd=ROOT_DIR, env=env)

    previous_handlers: dict[int, signal.Handlers] = {}

    def forward(signum, _frame) -> None:
        if process.poll() is None:
            process.send_signal(signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, forward)

    try:
        return process.wait()
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def preflight_import(service_name: str, env: dict[str, str]) -> int:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import importlib; importlib.import_module('services.{service_name}.__main__')",
        ],
        cwd=ROOT_DIR,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return 0

    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
        _print_missing_dependency_hint(completed.stderr)
    else:
        print(
            f"error: could not import services.{service_name}.__main__",
            file=sys.stderr,
        )
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(list(argv if argv is not None else sys.argv[1:]))

    if args.list_services:
        for service in discover_runnable_services():
            print(service)
        return 0

    if not args.service:
        print("error: SERVICE is required. Use --list-services to inspect options.", file=sys.stderr)
        return 2

    try:
        validate_service(args.service)
        config_path = resolve_config_path(args.config, os.environ)
        env = build_child_env(config_path)
        command = build_command(args.service, args.service_args)
    except LocalRunnerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        preflight_result = preflight_import(args.service, env)
        if preflight_result != 0:
            return preflight_result
        return run_child(command, env)
    except ModuleNotFoundError as exc:
        print(f"error: missing Python dependency: {exc.name}", file=sys.stderr)
        print("Install local development dependencies with: python -m pip install -e .", file=sys.stderr)
        return 2
    except subprocess.SubprocessError as exc:
        print(f"error: failed to start service: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
