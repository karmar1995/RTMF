from pydantic import BaseModel

class EvaluationResponse(BaseModel):
    sd_evaluation_id: str
    status: str
