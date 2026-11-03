import uuid
import shutil
import json
import zipfile
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, Tuple
from fastapi import UploadFile, BackgroundTasks

from sysidentpy.utils.save_load import load_model
from services.system_discovery.app.services.statistical_evaluation import run_evaluation_pipeline

# Constants
STORAGE_DIR = Path("storage")
STORAGE_DIR.mkdir(exist_ok=True)


def _load_test_data(job_dir: Path) -> Tuple[Optional[np.ndarray], np.ndarray, pd.DataFrame]:
    """Load test data from CSV. Strictly requires data_test.csv."""
    test_csvs = list(job_dir.rglob("data_test.csv"))
    if not test_csvs:
        raise FileNotFoundError("Missing required file: data_test.csv")
        
    test_csv = test_csvs[0]
    df = pd.read_csv(test_csv)
    if len(df.columns) == 1 and ';' in df.columns[0]:
        df = pd.read_csv(test_csv, sep=';')
        
    data = df.values
    if data.shape[1] > 1:
        return data[:, :-1], data[:, -1:], df
    return None, data[:, :], df


def _generate_predictions(model, X: Optional[np.ndarray], y: np.ndarray, original_df: pd.DataFrame, job_dir: Path) -> Path:
    """Generate predictions using the model in free-run simulation mode.
    Explicitly prepares initial conditions based on the model's max_lag.
    Saves the original test data with appended y_sim column to a CSV file.
    """
    max_lag = getattr(model, 'max_lag', 1) 
    initial_conditions = y[:max_lag]
    
    if model.model_type == "NARMAX":
        y_pred = model.predict(X=X, y=initial_conditions)
    else:
        forecast_steps = len(y) - max_lag
        y_pred = model.predict(X=None, y=initial_conditions, forecast_horizon=forecast_steps)
        
    results_path = job_dir / "results.csv"
    
    # Create a copy to avoid SettingWithCopyWarning
    out_df = original_df.copy()
    out_df["y_sim"] = y_pred.flatten()
    
    out_df.to_csv(results_path, index=False, sep=";")
    
    return results_path


def _create_error_results(job_dir: Path, sd_id: str, model_name: str, error: str):
    """Create dummy result files in case of failure."""
    (job_dir / "results.csv").write_text(f"metric;value\nerror;{error}")
    (job_dir / "cdf.csv").write_text("nash_bootstrap\n0")
    (job_dir / "metadata.json").write_text(json.dumps({
        "model": model_name, 
        "sd_id": sd_id, 
        "status": "failed",
        "error": error
    }))


async def process_evaluation_internal(sd_id: str, job_dir: Path, model_name: str):
    """Main evaluation logic used by training service."""
    model_file = f"{model_name}.syspy"
    model_path = job_dir / model_file
    
    if not model_path.exists():
        _create_error_results(job_dir, sd_id, model_name, "missing_model_file")
        return

    try:
        model = load_model(file_name=model_file, path=str(job_dir))
        X_test, y_test, df = _load_test_data(job_dir)
        
        # 1. Predict (Free-run simulation saving to results.csv)
        results_path = _generate_predictions(model, X_test, y_test, df, job_dir)
        
        # 2. Evaluate (Statistical Pipeline including Bootstrap)
        run_evaluation_pipeline(results_path, job_dir)
        
    except Exception as e:
        _create_error_results(job_dir, sd_id, model_name, str(e))


async def _process_evaluation_task(sd_id: str, job_dir: Path, model: str):
    """Legacy background task logic."""
    await process_evaluation_internal(sd_id, job_dir, model)
    
    result_zip = job_dir / f"{sd_id}.zip"
    with zipfile.ZipFile(result_zip, "w") as zf:
        for f in ["results.csv", "cdf.csv", "metadata.json"]:
            if (job_dir / f).exists():
                zf.write(job_dir / f, arcname=f)


async def start_evaluation(file: UploadFile, background_tasks: BackgroundTasks, model: str) -> str:
    """Legacy entry point."""
    sd_id = str(uuid.uuid4())
    job_dir = STORAGE_DIR / sd_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    with open(job_dir / "input_data.zip", "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    background_tasks.add_task(_process_evaluation_task, sd_id, job_dir, model)
    return sd_id


async def get_evaluation_result_path(sd_id: str) -> Optional[str]:
    """Legacy results retrieval."""
    path = STORAGE_DIR / sd_id / f"{sd_id}.zip"
    return str(path) if path.exists() else None


async def get_status(sd_id: str) -> str:
    """Legacy status check."""
    job_dir = STORAGE_DIR / sd_id
    if not job_dir.exists():
        return "NOT_FOUND"
    return "COMPLETED" if (job_dir / f"{sd_id}.zip").exists() else "PROCESSING"
