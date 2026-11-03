from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from flask import current_app, render_template, request

from use_case_contracts.messages import GetRegistrationDetails, ListRecentRegistrations
from services.front.pagination import (
    build_page_items,
    parse_per_page,
    parse_positive_int,
    total_pages as _compute_total_pages,
)


def recent_registrations():
    page = parse_positive_int(request.args.get("page"), default=1)
    per_page = parse_per_page(request.args.get("per_page"), default=20)
    status_filter = (request.args.get("status") or "").strip().lower()
    query = (request.args.get("q") or "").strip()

    registrations, total = _load_registrations(
        query=query, status_filter=status_filter, page=page, per_page=per_page
    )
    view_rows = [_with_row_class(item) for item in registrations]
    total_pages = _compute_total_pages(total, per_page)

    return render_template(
        "recent_registrations.html",
        active_page="recent_registrations",
        registrations=view_rows,
        status_filter=status_filter,
        query=query,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        page_items=build_page_items(total_pages, page),
    )


def registration_details(registration_id: str):
    status = (request.args.get("status") or "Running").strip().capitalize()
    note = (request.args.get("note") or "").strip()

    registration = _load_registration_details(registration_id) or {
        "id": registration_id,
        "name": "Unknown simulator",
        "status": status if status else "Unknown",
        "created_at": _now_text(),
        "note": note,
    }

    view_model = {
        **registration,
        "status": _normalize_status(registration.get("status")),
        "badge_class": _badge_class(registration.get("status")),
    }

    if note:
        view_model["note"] = note

    return render_template(
        "registration_details.html",
        active_page="recent_registrations",
        registration=view_model,
    )

def _load_registrations(
    query: str, status_filter: str, page: int, per_page: int
) -> tuple[List[Dict[str, str]], int]:
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        rows = _fake_recent_registrations()
        return rows, len(rows)

    result = usecases.handle(
        ListRecentRegistrations(
            query=query or None,
            status=status_filter or None,
            page=page,
            per_page=per_page,
        )
    )
    return [
        {
            "id": item.registration_id,
            "name": item.model_name,
            "status": item.status,
            "created_at": item.created_at or _now_text(),
        }
        for item in result.registrations
    ], result.total


def _load_registration_details(registration_id: str) -> Dict[str, str] | None:
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return _find_registration(registration_id)

    result = usecases.handle(GetRegistrationDetails(registration_id=registration_id))
    return {
        "id": result.registration_id,
        "name": result.model_name,
        "status": result.status,
        "created_at": result.created_at or _now_text(),
    }


def _fake_recent_registrations() -> List[Dict[str, str]]:
    return [
        {
            "id": "reg-101",
            "name": "Traffic Simulator",
            "status": "Running",
            "created_at": _now_text(),
        },
        {
            "id": "reg-100",
            "name": "Warehouse Flow",
            "status": "Succeeded",
            "created_at": _now_text(),
        },
        {
            "id": "reg-099",
            "name": "Fleet Optimizer",
            "status": "Failed",
            "created_at": _now_text(),
        },
    ]


def _find_registration(registration_id: str):
    for item in _fake_recent_registrations():
        if item["id"] == registration_id:
            return item
    return None


def _with_row_class(item: Dict[str, str]) -> Dict[str, str]:
    return {
        **item,
        "status": _normalize_status(item.get("status")),
        "row_class": _row_class(item.get("status")),
    }


def _row_class(status: str | None) -> str:
    normalized = _normalize_status(status).lower()
    if normalized == "running":
        return "list-group-item-warning"
    if normalized == "succeeded":
        return "list-group-item-success"
    if normalized == "failed":
        return "list-group-item-danger"
    return "list-group-item-secondary"


def _badge_class(status: str | None) -> str:
    normalized = _normalize_status(status).lower()
    if normalized == "running":
        return "bg-warning text-dark"
    if normalized == "succeeded":
        return "bg-success"
    if normalized == "failed":
        return "bg-danger"
    return "bg-secondary"


def _normalize_status(status: str | None) -> str:
    if not status:
        return "Unknown"
    return status.strip().capitalize()


def _now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
