from pydantic import BaseModel, Field
from typing import List, Tuple, Optional

class RecognizeResponse(BaseModel):
    recognition_id: str

class Metrics(BaseModel):
    recovery_time_in_steps: Optional[int] = Field(None, description="Duration (number of steps) of the longest identified 'Recovery' phase.")
    shock_time_in_steps: Optional[int] = Field(None, description="Duration (number of steps) of the longest identified 'Shock' phase.")
    shock_drop_pct_ref_normal: Optional[float] = Field(None, description="Percentage drop during the longest 'Shock' phase relative to the average value of the immediately preceding 'Normal' phase.")
    shock_drop_pct_ref_baseline: Optional[float] = Field(None, description="Percentage drop during the longest 'Shock' phase relative to the user-provided baseline parameter.")
    shock_stage_avg: Optional[float] = Field(None, description="Average metric value during the longest 'Shock' phase.")
    shock_stage_std: Optional[float] = Field(None, description="Standard deviation of the metric value during the longest 'Shock' phase.")

class PhasesResponse(BaseModel):
    phases: List[Tuple[int, int, str]] = Field(..., description="List of identified phases [start_step, end_step, phase_name]")
    metrics: Metrics = Field(default_factory=Metrics, description="Calculated metrics for the identified phases")

class StatusResponse(BaseModel):
    recognition_id: str
    status: str
