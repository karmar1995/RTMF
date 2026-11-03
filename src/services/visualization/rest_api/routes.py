from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse

from services.visualization.core.errors import (
    BadAggregation,
    CorruptedZipFile,
    DecodeError,
    FutureNotFoundError,
    NotAZipFile,
    UnknownPlotType,
    VisualizationError,
)
from services.visualization.core.service import VisualizationService
from services.visualization.rest_api.schemas import (
    CreatePlotResponse,
    ErrorResponse,
    GetPlotsInfoResponse,
    PlotStatusResponse,
)


def create_router(visualization: VisualizationService) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["v1 Plots"])

    @router.post(
        "/generate-plot2D",
        status_code=status.HTTP_201_CREATED,
        response_model=CreatePlotResponse,
        responses={
            400: {
                "model": ErrorResponse,
                "description": "CorruptedZip / NotAZip / DecodeError / BadAggregation / UnknownPlotType",
            }
        },
    )
    async def generate_plot2d(
        traits: str | None = Form(None),
        type: str = Form(...),
        data: UploadFile = File(...),
    ) -> CreatePlotResponse:
        parsed_traits: list[dict[str, Any]] | None = None
        if traits is not None:
            try:
                parsed_traits = json.loads(traits)
            except json.JSONDecodeError:
                raise DecodeError("Bad JSON format")

        content = await data.read()

        try:
            plot_id = visualization.render_plot(
                data=content,
                plot_type=type,
                traits=parsed_traits,
            )
        except VisualizationError as error:
            raise _to_http_exception(error)

        return CreatePlotResponse(id=plot_id)

    @router.get(
        "/get-plot-status/{id}",
        response_model=PlotStatusResponse,
        responses={
            404: {"model": ErrorResponse, "description": "Future not found"},
        },
    )
    def get_plot_status(id: UUID) -> PlotStatusResponse:
        try:
            status = visualization.get_plot_status(id)
        except VisualizationError as error:
            raise _to_http_exception(error)
        return PlotStatusResponse(status=status)

    @router.get(
        "/get-plot-html/{id}",
        response_class=HTMLResponse,
        responses={
            404: {"model": ErrorResponse, "description": "Future not found"},
        },
    )
    def get_plot_html(id: UUID) -> str:
        try:
            html = visualization.get_plot_html(id)
        except VisualizationError as error:
            raise _to_http_exception(error)
        if html is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plot {id} not found",
            )
        return html

    @router.get(
        "/get-plots-info",
        response_model=GetPlotsInfoResponse,
    )
    def get_plots_info() -> GetPlotsInfoResponse:
        return GetPlotsInfoResponse(root=visualization.supported_plot_types())

    return router


def _to_http_exception(error: VisualizationError) -> HTTPException:
    if isinstance(error, FutureNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        )

    if isinstance(
        error,
        (CorruptedZipFile, NotAZipFile, DecodeError, BadAggregation, UnknownPlotType),
    ):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        )

    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=str(error),
    )
