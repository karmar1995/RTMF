from pydantic import BaseModel
from typing import Optional

class StatusResponse(BaseModel):
    job_id: str
    status: str  # Overall status (e.g. "PROCESSING", "COMPLETED", "FAILED")
    training_status: str
    evaluation_status: str
    error: Optional[str] = None
