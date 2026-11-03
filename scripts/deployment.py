#!/usr/bin/env python3
"""Prepare one Compose application for the services installed on this machine."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from lib.deployment import (
    DeploymentError,
    environment_example,
    read_environment,
    read_manifest,
    render_bundles,
    validate_environment,
    validate_required_environment,
    write_bundles,
    write_text,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "config/deployment.json"
DEFAULT_OUTPUT = ROOT / "dist/deployment"
# A deployment kit contains tooling and public templates only. Never copy trees.
KIT_FILES = (
    "scripts/deployment.py", "scripts/render_deployment.py", "scripts/lib/deployment.py",
    "scripts/init_deployment.sh", "scripts/deploy_service.sh", "scripts/deploy_services.sh",
    "scripts/status_service.sh", "scripts/status_services.sh",
    "scripts/logs_service.sh", "scripts/logs_services.sh",
    "scripts/stop_service.sh", "scripts/stop_services.sh",
    "config/deployment.example.json", "docs/DEPLOYMENT.md", "docs/CONFIGURATION.md",
    "docs/INFRASTRUCTURE.md", "docs/SINGLE_SERVER_VM.md", "docs/KEYCLOAK.md", "docs/IMAGES.md",
    "docs/STARTUP.md", "db_mgmt/00_create_db.sql", "db_mgmt/01_schema.sql",
    "db_mgmt/02_sanity_check.sql", "db_mgmt/db_config.sh",
    "db_mgmt/schema_creation.sh", "db_mgmt/sanity_check.sh",
)
KIT_README = """# RTMF deployment kit

Follow [Deployment](docs/DEPLOYMENT.md) for the ordered setup and startup
commands. Choose the full framework or the services installed on this machine.
Use the image namespace and release tag supplied by the publisher.

This kit contains public templates, preparation scripts, the database schema,
and installation documentation. It has no application source or Dockerfiles;
use published images. Configure the manifest and `.env`, render the selected
services, then operate the generated bundle with Docker Compose.

Preparation needs Python 3.11+. A prepared bundle needs only Docker Engine and
the Compose plugin. Keep filled `.env` files private.
"""


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    actions = result.add_subparsers(dest="action", required=True)
    initialize = actions.add_parser("init", help="Create editable deployment inputs or a standalone deployment kit.")
    initialize.add_argument("--target-dir", type=Path)
    initialize.add_argument("--output-dir", type=Path, help="Where to create the user-managed .env; defaults to dist/deployment in the kit.")
    initialize.add_argument("--force", action="store_true", help="Overwrite deployment input files.")
    for action in ("render", "deploy", "status", "logs", "stop"):
        sub = actions.add_parser(action)
        sub.add_argument("services", nargs="*", help="Render: services installed on this machine. Other commands: targets in the existing Compose application.")
        sub.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
        sub.add_argument("--secrets-file", type=Path, help="Literal KEY=value file. Shell variables take precedence.")
        sub.add_argument("--single", action="store_true", help=argparse.SUPPRESS)
        sub.add_argument("--dry-run", action="store_true", help="Print operations without contacting Docker; render still writes its generated files.")
        if action == "render":
            sub.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
            sub.add_argument("--repository", help="Service image repository prefix, e.g. ghcr.io/org/rtmf.")
            sub.add_argument("--image-tag", "--tag", dest="tag")
            sub.add_argument("--image", help="Explicit image reference; select one service.")
            sub.add_argument("--project-name", help="Compose application project name.")
            image_mode = sub.add_mutually_exclusive_group()
            image_mode.add_argument("--local-image", action="store_true", help="Use rtmf/<service>:<tag>.")
            image_mode.add_argument("--harbor-image", action="store_true", help="Use --registry and --project as the image repository prefix.")
            sub.add_argument("--registry")
            sub.add_argument("--project", help="Registry namespace, used with --registry.")
            sub.add_argument("--check", action="store_true", help="Validate without writing output.")
            sub.add_argument("--check-env", action="store_true", help="Also require selected services' secrets to be non-empty.")
        if action == "deploy":
            sub.add_argument("--no-pull", action="store_true")
            sub.add_argument("--pull-only", action="store_true")
            sub.add_argument("--no-recreate", action="store_true")
            sub.add_argument("--remove-orphans", action="store_true")
        if action == "logs":
            sub.add_argument("-f", "--follow", action="store_true")
            sub.add_argument("--tail", type=int, default=200)
        if action == "stop":
            sub.add_argument("--down", action="store_true", help="Remove the whole machine's Compose application; do not select individual services.")
            sub.add_argument("--remove", action="store_true", help="Remove the stopped application containers.")
    return result


def initialize(args: argparse.Namespace) -> None:
    target = args.target_dir.resolve() if args.target_dir else ROOT
    if target != ROOT:
        # Read all sources first, so an incomplete source kit cannot create half a kit.
        sources = [(relative, (ROOT / relative).read_bytes()) for relative in KIT_FILES]
        for relative, content in sources:
            path = target / relative
            if path.exists() and not args.force:
                continue
            write_text(path, content.decode("utf-8"), mode=0o755 if relative.endswith((".sh", ".py")) else 0o644)
        readme = target / "README.md"
        if not readme.exists() or args.force:
            write_text(readme, KIT_README)
    template = target / "config/deployment.example.json"
    manifest = target / "config/deployment.json"
    if not manifest.exists() or args.force:
        write_text(manifest, template.read_text(encoding="utf-8"), mode=0o600)
    bundles = render_bundles(read_manifest(manifest))
    output = args.output_dir if args.output_dir is not None else target / "dist/deployment"
    secrets = output / ".env"
    if not secrets.exists() or args.force:
        required = set().union(*(bundle.required for bundle in bundles))
        optional = set().union(*(bundle.optional for bundle in bundles)) - required
        write_text(secrets, environment_example(required, optional), mode=0o600)
    print(f"Edit {manifest} and {secrets}")
    print(f"Prepare: python3 {target / 'scripts/render_deployment.py'} --output-dir {output}")
    print(f"Start: cd {output} && docker compose up -d")


def selected_environment(args: argparse.Namespace) -> dict[str, str]:
    path = args.secrets_file
    if path is None and (args.output_dir / ".env").is_file():
        path = args.output_dir / ".env"
    return read_environment(path)


def render(args: argparse.Namespace):
    if args.single and len(args.services) != 1:
        raise DeploymentError("This command requires exactly one service")
    repository = args.repository
    if args.local_image:
        if repository or args.registry or args.project or args.image:
            raise DeploymentError("--local-image cannot be combined with image repository overrides")
        repository = "rtmf"
    if args.registry or args.project or args.harbor_image:
        registry = args.registry or os.environ.get("HARBOR_REGISTRY")
        project = args.project or os.environ.get("HARBOR_PROJECT")
        if not registry or not project or repository:
            raise DeploymentError("Use --registry and --project together, without --repository")
        repository = f"{registry.rstrip('/')}/{project.strip('/')}"
    bundles = render_bundles(read_manifest(args.manifest), args.services,
                             repository=repository, tag=args.tag, image=args.image,
                             project_name=args.project_name)
    check_environment = args.check_env
    environment = selected_environment(args) if check_environment else dict(os.environ)
    if check_environment:
        validate_environment(bundles, environment)
    if not getattr(args, "check", False):
        write_bundles(bundles, args.output_dir)
    for bundle in bundles:
        print(f"{bundle.service}: {len(bundle.required)} required environment variables")
    if not args.check:
        print(f"Compose application: {args.output_dir / 'compose.yaml'}")
    return bundles, environment


def run(command: list[str], environment: dict[str, str], dry_run: bool) -> None:
    print(shlex.join(command), flush=True)
    if not dry_run:
        if shutil.which("docker", path=environment.get("PATH")) is None:
            raise DeploymentError("docker command is not available")
        subprocess.run(command, env=environment, check=True)


def operate(args: argparse.Namespace) -> None:
    if args.single and len(args.services) != 1:
        raise DeploymentError("This command requires exactly one service")
    path = (args.output_dir / "compose.yaml").resolve()
    try:
        application = json.loads(path.read_text(encoding="utf-8"))
        available = application["services"]
        metadata = json.loads((args.output_dir / "environment.json").read_text(encoding="utf-8"))
        if not isinstance(available, dict) or not isinstance(metadata["services"], dict):
            raise ValueError("Invalid service definitions")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DeploymentError(f"Cannot read the prepared Compose application at {path}; run render first") from exc
    services = list(dict.fromkeys(args.services))
    if any(service not in available for service in services):
        raise DeploymentError("Unknown service selected in the prepared Compose application")
    if args.action == "stop" and args.down and services:
        raise DeploymentError("--down removes the whole application; omit service names, or use stop without --down")
    environment = dict(os.environ) if args.dry_run else selected_environment(args)
    if args.action == "deploy" and not args.dry_run and not args.pull_only:
        # Include explicitly declared dependencies, but not outbound HTTP clients.
        pending = list(services or available)
        selected = set()
        while pending:
            service = pending.pop()
            if service in selected:
                continue
            if service not in available:
                raise DeploymentError(f"Unknown Compose dependency: {service}")
            selected.add(service)
            pending.extend(available[service].get("depends_on", {}))
        required = {name for service in selected for name in metadata["services"].get(service, {}).get("required", [])}
        validate_required_environment(required, environment)
    # Compatibility commands operate on exactly the same prepared project as native Compose.
    base = ["docker", "compose", "-f", str(path)]
    commands = []
    if args.action == "deploy":
        if not args.no_pull or args.pull_only:
            commands.append(base + ["pull", *(["--include-deps"] if services else []), *services])
        if not args.pull_only:
            up = base + ["up", "-d"]
            if args.no_recreate:
                up.append("--no-recreate")
            if args.remove_orphans:
                up.append("--remove-orphans")
            commands.extend([up + services, base + ["ps", *services]])
    elif args.action == "status":
        commands.append(base + ["ps", *services])
    elif args.action == "logs":
        if args.tail < 0:
            raise DeploymentError("--tail must be non-negative")
        commands.append(base + ["logs", *(["--follow"] if args.follow else []), "--tail", str(args.tail), *services])
    else:
        commands.append(base + (["down"] if args.down else ["stop", *services]))
        if args.remove and not args.down:
            commands.append(base + ["rm", "-f", *services])
    for command in commands:
        run(command, environment, args.dry_run)


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "init":
            initialize(args)
        elif args.action == "render":
            render(args)
        else:
            operate(args)
    except (DeploymentError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        return exc.returncode if exc.returncode > 0 else 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
