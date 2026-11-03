from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from flask import current_app, render_template, request

from use_case_contracts.messages import GetSimulatorDetails, ListSimulators
from services.front.pagination import (
    build_page_items,
    parse_per_page,
    parse_positive_int,
    total_pages as _compute_total_pages,
)


def simulators_browse():
    page = parse_positive_int(request.args.get("page"), default=1)
    per_page = parse_per_page(request.args.get("per_page"), default=20)
    query = (request.args.get("q") or "").strip()

    simulators, total = _load_simulators(query=query, page=page, per_page=per_page)
    total_pages = _compute_total_pages(total, per_page)

    return render_template(
        "simulators_browse.html",
        active_page="simulators_browse",
        simulators=simulators,
        query=query,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        page_items=build_page_items(total_pages, page),
    )


def simulator_details(simulator_id: str):
    simulator = _load_simulator_details(simulator_id) or {
        "id": simulator_id,
        "name": "Unknown simulator",
        "status": "Unknown",
        "created_at": _now_text(),
        "build_spec": None,
        "input_params": [],
        "output_params": [],
    }

    details = _extract_details(
        simulator.get("build_spec"),
        simulator.get("input_params"),
        simulator.get("output_params"),
    )
    return render_template(
        "simulator_details.html",
        active_page="simulators_browse",
        simulator=simulator,
        technology=details["technology"],
        input_params=details["input_params"],
        output_params=details["output_params"],
    )


def _load_simulators(
    query: str, page: int, per_page: int
) -> tuple[List[Dict[str, str]], int]:
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        simulators = _fake_simulators()
        if query:
            needle = query.lower()
            simulators = [s for s in simulators if needle in s["name"].lower()]
        total = len(simulators)
        start = (page - 1) * per_page
        return simulators[start : start + per_page], total

    result = usecases.handle(
        ListSimulators(query=query or None, page=page, per_page=per_page)
    )
    return [
        {
            "id": item.simulator_id,
            "name": item.model_name,
            "status": "Available",
            "created_at": item.created_at or _now_text(),
            "version": item.version,
        }
        for item in result.simulators
    ], result.total


def _load_simulator_details(simulator_id: str) -> Dict[str, str] | None:
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return _find_simulator(simulator_id)

    result = usecases.handle(GetSimulatorDetails(simulator_id=simulator_id))
    return {
        "id": simulator_id,
        "name": result.model_name,
        "status": "Available" if result.build_spec is not None else "Unknown",
        "created_at": result.created_at or _now_text(),
        "build_spec": result.build_spec.spec if result.build_spec else None,
        "input_params": result.input_params or [],
        "output_params": result.output_params or [],
    }

def _extract_details(build_spec, input_params, output_params) -> Dict[str, object]:
    tech = None
    if isinstance(build_spec, dict):
        tech = build_spec.get("technology")
    return {
        "technology": _format_technology(tech),
        "input_params": input_params or [],
        "output_params": output_params or [],
    }


def _format_technology(technology) -> str:
    if not technology:
        return ""

    def get_field(obj, name, default=None):
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    tech_type = get_field(technology, "type", "")
    lines = []
    if tech_type:
        lines.append(f"type: {tech_type}")

    python_cfg = get_field(technology, "python")
    if python_cfg:
        version = get_field(python_cfg, "version")
        if version:
            lines.append(f"python.version: {version}")
        packages = get_field(python_cfg, "packages")
        if packages:
            names = []
            for pkg in packages:
                name = get_field(pkg, "name")
                if name:
                    names.append(name)
            if names:
                lines.append(f"python.packages: {', '.join(names)}")
        venv = get_field(python_cfg, "venv")
        if venv is not None:
            lines.append(f"python.venv: {venv}")
        req_upload = get_field(python_cfg, "requirements_upload")
        if req_upload:
            lines.append(f"python.requirements_upload: {req_upload}")

    java_cfg = get_field(technology, "java")
    if java_cfg:
        distribution = get_field(java_cfg, "distribution")
        if distribution:
            lines.append(f"java.distribution: {distribution}")
        version = get_field(java_cfg, "version")
        if version:
            lines.append(f"java.version: {version}")
        app_type = get_field(java_cfg, "app_type")
        if app_type:
            lines.append(f"java.app_type: {app_type}")

    dotnet_cfg = get_field(technology, "dotnet")
    if dotnet_cfg:
        version = get_field(dotnet_cfg, "version")
        if version:
            lines.append(f"dotnet.version: {version}")
        flavor = get_field(dotnet_cfg, "flavor")
        if flavor:
            lines.append(f"dotnet.flavor: {flavor}")

    return "\n".join(lines)


def _fake_simulators() -> List[Dict[str, str]]:
    return [
        {
            "id": "sim-traffic",
            "name": "Traffic Simulator",
            "status": "Available",
            "created_at": _now_text(),
            "version": "1.0",
        },
        {
            "id": "sim-warehouse",
            "name": "Warehouse Flow",
            "status": "Available",
            "created_at": _now_text(),
            "version": "2.1",
        },
    ]


def _find_simulator(simulator_id: str):
    for item in _fake_simulators():
        if item["id"] == simulator_id:
            return item
    return None


def _now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
