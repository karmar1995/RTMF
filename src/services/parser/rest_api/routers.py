from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from typing import Optional
from pathlib import Path
import tempfile
import shutil

from services.parser.rest_api.schemas import RecognizeResponse, PhasesResponse, StatusResponse
from services.parser.core.service import ParserService

def create_router(parser_service: ParserService) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.post(
        "/resiliency_stages_recognition", 
        response_model=RecognizeResponse,
        status_code=202
    )
    async def run_resiliency_stages_recognition(
        file: UploadFile = File(...),
        baseline: Optional[float] = Form(None)
    ):
        if not file.filename.endswith('.zip'):
            raise HTTPException(status_code=400, detail="Only .zip files are allowed.")
            
        temp_dir = Path(tempfile.mkdtemp())
        temp_file = temp_dir / "temp.zip"
        with open(temp_file, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        try:
            recognition_id = parser_service.run_recognition(temp_file, baseline)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
            
        return RecognizeResponse(recognition_id=recognition_id)

    @router.get(
        "/resiliency_stages_recognition/{recognition_id}/status",
        response_model=StatusResponse
    )
    async def get_status(recognition_id: str):
        status = parser_service.get_status(recognition_id)
        return StatusResponse(recognition_id=recognition_id, status=status)

    @router.get(
        "/resiliency_stages_recognition/{recognition_id}", 
        response_model=PhasesResponse
    )
    async def get_result(recognition_id: str):
        try:
            phases, metrics = parser_service.get_result(recognition_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
            
        return PhasesResponse(phases=phases, metrics=metrics)

    return router
