import uuid
import shutil
import zipfile
from pathlib import Path
from fastapi import UploadFile, BackgroundTasks

# Dedicated directory to store all jobs
STORAGE_DIR = Path("storage")
STORAGE_DIR.mkdir(exist_ok=True)


async def _process_simulation_task(sd_simulation_id: str, job_dir: Path):
    """
    Mock simulation logic.
    Creates a results.csv and zips it into the result archive.
    """
    try:
        # 1. Unzip input_data.zip directly into job_dir
        input_zip = job_dir / "input_data.zip"
        with zipfile.ZipFile(input_zip, 'r') as zip_ref:
            zip_ref.extractall(job_dir)

        # 2. Resolve initial conditions
        ic_file_txt = job_dir / "initial_conditions.txt"
        initial_conditions = None

        if ic_file_txt.exists():
            import re
            ic_str = ic_file_txt.read_text().strip()
            # Split by space or comma
            parts = re.split(r'[,\s]+', ic_str)
            initial_conditions = [float(p) for p in parts if p]
        else:
            ic_json_files = list(job_dir.glob("initial_conditions.json"))
            if ic_json_files:
                import json
                ic_data = json.loads(ic_json_files[0].read_text())
                if isinstance(ic_data, dict) and "initial_values" in ic_data:
                    initial_conditions = ic_data["initial_values"]
                elif isinstance(ic_data, list):
                    initial_conditions = ic_data
                else:
                    raise ValueError("initial_conditions.json must contain a list or a dict with 'initial_values'.")
            else:
                raise ValueError("Initial conditions not provided via form and initial_conditions.json not found in ZIP.")
        
        # Log resolved conditions for tracking
        (job_dir / "resolved_ic.log").write_text(str(initial_conditions))

        # 3. Load model (*.syspy) and run simulation
        import numpy as np
        import pandas as pd
        from sysidentpy.utils.save_load import load_model

        model_files = list(job_dir.rglob("*.syspy"))
        if not model_files:
            raise ValueError("No trained model (*.syspy) found in the provided ZIP file.")
        model_file_path = model_files[0]
        
        model = load_model(file_name=model_file_path.name, path=str(model_file_path.parent))
        
        # Prepare initial conditions (truncate to max_lag)
        max_lag = getattr(model, 'max_lag', 1)
        truncated_ic = initial_conditions[:max_lag]
        y_init = np.array(truncated_ic).reshape(-1, 1)
        
        # Check for data.csv if NARMAX
        X_data = None
        if model.model_type == "NARMAX":
            csv_files = list(job_dir.rglob("*.csv"))
            if not csv_files:
                raise ValueError("Model is NARMAX, but no CSV data file was found in the ZIP archive for external control signals.")
            
            df = pd.read_csv(csv_files[0], sep=None, engine='python')
            if "y" in df.columns:
                X_data = df.drop(columns=["y"]).values
            elif "y_truth" in df.columns:
                X_data = df.drop(columns=["y_truth"]).values
            else:
                X_data = df.values
                
        # Determine horizon
        horizon_file = job_dir / "horizon.txt"
        forecast_horizon = None
        if horizon_file.exists():
            forecast_horizon = int(horizon_file.read_text().strip())
        
        # Run prediction
        if model.model_type == "NARMAX":
            y_pred = model.predict(X=X_data, y=y_init)
        else:
            if forecast_horizon is None:
                forecast_horizon = 30 # Default if not provided
            y_pred = model.predict(X=None, y=y_init, forecast_horizon=forecast_horizon)
            
        # 4. Save results.csv
        results_csv = job_dir / "results.csv"
        
        if 'df' in locals() and df is not None:
            out_df = df.copy()
            out_df["y_sim"] = y_pred.flatten()
        else:
            out_df = pd.DataFrame({"y_sim": y_pred.flatten()})
            
        out_df.to_csv(results_csv, index=False, sep=';')
    except Exception as e:
        (job_dir / "error.log").write_text(f"Simulation failed: {str(e)}")
        results_csv = job_dir / "results.csv"
        results_csv.write_text(f"error\n{str(e)}")

    # Zip all result files into result archive
    result_zip_path = job_dir / f"{sd_simulation_id}_final.zip"
    with zipfile.ZipFile(result_zip_path, "w") as zf:
        zf.write(results_csv, arcname="results.csv")


async def start_simulation(file: UploadFile, background_tasks: BackgroundTasks, horizon: int = None, initial_conditions: str = None) -> str:
    """
    Accept .zip archive for simulation, run simulation in background,
    return the simulation job ID.
    """
    sd_simulation_id = str(uuid.uuid4())

    # Create dedicated subdirectory for this simulation
    job_dir = STORAGE_DIR / sd_simulation_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Save input zip
    input_path = job_dir / "input_data.zip"
    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Save horizon if provided (optional)
    if horizon is not None:
        (job_dir / "horizon.txt").write_text(str(horizon))
        
    # Save initial conditions if provided
    if initial_conditions is not None:
        (job_dir / "initial_conditions.txt").write_text(initial_conditions)

    # Run mock simulation in background
    background_tasks.add_task(_process_simulation_task, sd_simulation_id, job_dir)

    return sd_simulation_id


async def get_simulation_result_path(sd_simulation_id: str):
    """
    Return the path to the simulation result zip file if it exists.
    """
    result_path = STORAGE_DIR / sd_simulation_id / f"{sd_simulation_id}_final.zip"
    if result_path.exists():
        return str(result_path)
    return None


async def get_status(sd_simulation_id: str) -> dict:
    """
    Return the status of the simulation job.
    """
    job_dir = STORAGE_DIR / sd_simulation_id
    if not job_dir.exists():
        return {"status": "NOT_FOUND"}
    
    error_log = job_dir / "error.log"
    if error_log.exists():
        return {
            "status": "FAILED",
            "error": error_log.read_text().strip()
        }
        
    result_path = job_dir / f"{sd_simulation_id}_final.zip"
    if result_path.exists():
        return {"status": "COMPLETED"}
    
    return {"status": "PROCESSING"}
