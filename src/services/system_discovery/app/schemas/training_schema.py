from pydantic import BaseModel, Field, validator
from typing import List, Union, Optional

class SystemParameters(BaseModel):
    nlags_x: Optional[Union[int, List[int], List[List[int]], str]] = Field(None, alias="nlags-x", description="lag of the X variables (single int or comma-separated ints). If missing, NAR mode is used.")
    nlags_y: Union[int, List[int], str] = Field(..., alias="nlags-y", description="lag of the Y variable (single int or comma-separated ints)")
    basis: str = Field(..., description="basic function")
    degree: Optional[int] = Field(None, description="basis function degree. Required if basis is 'Polynomial', otherwise can be None or empty.")
    model: str = Field(..., description="name of the model for saving")
    n_info_values: Optional[int] = Field(None, alias="n-info-values", description="number of regressors to consider for information criteria")
    mode: str = Field("simulation", description="training mode: 'simulation' (with external input) or 'forecasting'")

    @validator("degree", always=True)
    def validate_degree(cls, v, values):
        basis = values.get("basis")
        if basis == "Polynomial" and v is None:
            raise ValueError("degree is required when basis is 'Polynomial'")
        return v

    @validator("nlags_x", "nlags_y", pre=True)
    def parse_lags(cls, v):
        if isinstance(v, str):
            v = v.strip()
            # Safely evaluate list or nested list string representations
            if v.startswith("[") and v.endswith("]"):
                import ast
                try:
                    return ast.literal_eval(v)
                except Exception:
                    pass
            
            # Handle simple comma-separated string
            if "," in v:
                try:
                    return [int(x.strip()) for x in v.split(",") if x.strip()]
                except ValueError:
                    raise ValueError("All values in comma-separated lags must be integers")
            # Try to convert single string to int
            try:
                return int(v)
            except ValueError:
                return v # Let pydantic handle type validation
        return v

class TrainingResponse(BaseModel):
    sd_training_id: str
    status: str
