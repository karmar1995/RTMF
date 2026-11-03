from pydantic import BaseModel
from typing import Optional

class SimulationResponse(BaseModel):
    sd_simulation_id: str
    status: str

class SimulationStatusResponse(BaseModel):
    sd_simulation_id: str
    status: str
    error: Optional[str] = None
