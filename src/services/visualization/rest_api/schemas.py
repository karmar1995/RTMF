from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, RootModel

from services.visualization.enums.plot_status import PlotStatus
from services.visualization.enums.plot_type import Plot2DType


class CreatePlotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID


class PlotStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PlotStatus


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: str


class PlotTypeInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Plot2DType
    description: str


class GetPlotsInfoResponse(RootModel):
    root: list[PlotTypeInfo]
