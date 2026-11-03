from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException, Depends, Form
from fastapi.responses import FileResponse
from services.system_discovery.app.schemas.training_schema import TrainingResponse, SystemParameters
from services.system_discovery.app.schemas.status_schema import StatusResponse
from services.system_discovery.app.services import training_service
import json
import ast

router = APIRouter(tags=["training"])

@router.post("/train", response_model=TrainingResponse, summary="Start system discovery")
async def train(
    background_tasks: BackgroundTasks, 
    data: UploadFile = File(..., description="zip with .csv files including training data (data_train.csv) to built a model and (data_test.csv) for model evaluation"),
    system_parameters: str = Form(
        ..., 
        description="System model parameters. Example: {'nlags-x': [[1,2],[1,2]], 'nlags-y': 1, 'basis': 'Polynomial', 'degree': 1, 'model': 'my_model_name'}"
    )
):
    """
    Upload training data as a .zip file along with system parameters (Python dict format) to start the training process.
    Returns tracking ID <sd_training_id>.
    """
    if not data.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Only .zip files are supported for training data.")
        
    try:
        # Use literal_eval to support single quotes (Python style)
        system_parameters_dict = ast.literal_eval(system_parameters)
        if not isinstance(system_parameters_dict, dict):
            raise ValueError("Parsed content is not a dictionary")
    except Exception:
        raise HTTPException(
            status_code=400, 
            detail="Invalid format in system_parameters. Use Python dictionary format with single quotes (')."
        )
            
    try:
        parsed_system_parameters = SystemParameters(**system_parameters_dict).dict(by_alias=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid system_parameters values: {e}")
    
    # Process the file and start training in the background
    sd_training_id = await training_service.start_training(data, background_tasks, parsed_system_parameters)
    return TrainingResponse(sd_training_id=sd_training_id, status="Training started")

@router.get(
    "/get_training_results/{sd_training_id}",
    response_class=FileResponse,
    summary="Get training and evaluation results",
    responses={
        200: {
            "description": "ZIP archive containing the trained model and evaluation results",
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}
        }
    }
)
async def get_training_results(sd_training_id: str):
    """
    Retrieve the combined training and evaluation results as a .zip file using the provided <sd_training_id>.
    """
    results_path = await training_service.get_model_path(sd_training_id)
    if not results_path:
        raise HTTPException(status_code=404, detail="Results not found or still processing.")
    
    return FileResponse(
        path=results_path,
        media_type='application/zip',
        filename=f"{sd_training_id}_results.zip"
    )


@router.get("/get_training_status/{sd_training_id}", response_model=StatusResponse, summary="Get training status")
async def get_status(sd_training_id: str):
    """
    Check the status of a training job using the provided <sd_training_id>.
    """
    status_data = await training_service.get_status(sd_training_id)
    if status_data is None:
        raise HTTPException(status_code=404, detail="Training job not found.")
    
    return StatusResponse(**status_data)
