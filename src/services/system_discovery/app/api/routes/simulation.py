from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException, Form
from typing import Optional
from fastapi.responses import FileResponse
from services.system_discovery.app.schemas.simulation_schema import SimulationResponse, SimulationStatusResponse
from services.system_discovery.app.services import simulation_service

router = APIRouter(tags=["simulation"])

@router.post("/simulate", response_model=SimulationResponse, summary="Start model simulation")
async def simulate(
    background_tasks: BackgroundTasks,
    data: UploadFile = File(..., description=".zip file containing the trained model (*.syspy), initial_conditions.json (with initial_values). It may also contain data.csv in the case of a simulator with an external control signal."),
    horizon: Optional[int] = Form(None, description="Time horizon for forecasting mode (number of steps). Default is 30 for forecasting mode."),
    initial_conditions: Optional[str] = Form(None, description="Initial conditions separated by spaces. Example: 0.7 2.1 3.5")
):
    """
    1. Simulation with external control signal: Requires model, .csv with inputs of external control signal, and initial conditions.
    2. Forecasting (no external control signal): Requires model, horizon parameter, and initial conditions.

    Initial Conditions:
    - Priority: Form parameter initial_conditions.
    - Fallback: initial_conditions.json inside ZIP (used only if form parameter is empty).

    Returns tracking ID <sd_simulation_id>.
    """
    if not data.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Only .zip files are supported.")

    sd_simulation_id = await simulation_service.start_simulation(data, background_tasks, horizon, initial_conditions)
    return SimulationResponse(sd_simulation_id=sd_simulation_id, status="Simulation started")


@router.get(
    "/get_simulation_results/{sd_simulation_id}",
    response_class=FileResponse,
    summary="Get simulation results",
    responses={
        200: {
            "description": ".zip archive containing results.csv",
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}
        }
    }
)
async def get_simulation_results(sd_simulation_id: str):
    """
    Retrieve simulation results as a .zip file using the provided <sd_simulation_id> in the URL path.
    """
    result_path = await simulation_service.get_simulation_result_path(sd_simulation_id)
    if not result_path:
        raise HTTPException(status_code=404, detail="Simulation results not found or still processing.")

    return FileResponse(
        path=result_path,
        media_type='application/zip',
        filename=f"{sd_simulation_id}.zip"
    )


@router.get("/get_simulation_status/{sd_simulation_id}", response_model=SimulationStatusResponse, summary="Get simulation status")
async def get_status(sd_simulation_id: str):
    """
    Check the status of a simulation job using the provided <sd_simulation_id>.
    """
    status_data = await simulation_service.get_status(sd_simulation_id)
    if status_data["status"] == "NOT_FOUND":
        raise HTTPException(status_code=404, detail="Simulation job not found.")
    
    return SimulationStatusResponse(
        sd_simulation_id=sd_simulation_id,
        status=status_data["status"],
        error=status_data.get("error")
    )
