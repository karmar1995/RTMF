import uuid
import shutil
import zipfile
import json
import inspect
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import numpy as np
from fastapi import UploadFile, BackgroundTasks

import sysidentpy.basis_function as bf_mod
from sysidentpy.model_structure_selection import FROLS
from sysidentpy.parameter_estimation import LeastSquares
from sysidentpy.utils.save_load import save_model

from services.system_discovery.app.services import evaluation_service

# Constants
STORAGE_DIR = Path("storage")
STORAGE_DIR.mkdir(exist_ok=True)


def _extract_zip(zip_path: Path, extract_to: Path):
    """Extract input zip to the task directory."""
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)


def _load_training_data(job_dir: Path) -> Tuple[Optional[np.ndarray], np.ndarray]:
    """Load training data from CSV. Strictly requires data_train.csv."""
    # Try to find data_train.csv recursively
    train_csvs = list(job_dir.rglob("data_train.csv"))
    
    if not train_csvs:
        raise FileNotFoundError("Missing required file: data_train.csv")
    
    train_csv = train_csvs[0]
    
    df = pd.read_csv(train_csv)
    if len(df.columns) == 1 and ';' in df.columns[0]:
        df = pd.read_csv(train_csv, sep=';')
        
    data = df.values
    
    if data.shape[1] > 1:
        return data[:, :-1], data[:, -1:]
    return None, data[:, :]


def _get_basis_function(basis_name: str, degree: int):
    """Initialize the appropriate basis function class."""
    basis_class = getattr(bf_mod, basis_name, bf_mod.Polynomial)
    sig = inspect.signature(basis_class)
    
    if 'degree' in sig.parameters:
        return basis_class(degree=degree)
    return basis_class()


def _validate_and_determine_type(X: Optional[np.ndarray], y: np.ndarray, params: dict) -> str:
    """
    Validate parameters against data and determine model type (NAR or NARMAX).
    Returns 'NAR' or 'NARMAX'. Raises ValueError if invalid.
    """
    nlags_x = params.get('nlags_x')
    nlags_y = params.get('nlags_y')
    n_samples = len(y)
    
    def get_max_val(val):
        if isinstance(val, int):
            return val
        if isinstance(val, list):
            return max((get_max_val(v) for v in val), default=0)
        return 0

    # 1. Check if lags exceed sample size (Fundamental constraint)
    max_lag_y = get_max_val(nlags_y)
    if max_lag_y >= n_samples:
        raise ValueError(
            f"Wrong Parametrization: 'nlags-y' ({max_lag_y}) must be smaller than the number of training samples ({n_samples})."
        )
    
    if nlags_x is not None:
        max_lag_x = get_max_val(nlags_x)
        if max_lag_x >= n_samples:
            raise ValueError(
                f"Wrong Parametrization: 'nlags-x' ({max_lag_x}) must be smaller than the number of training samples ({n_samples})."
            )

    # 2. Determine and validate mode
    if X is None:
        if nlags_x is not None:
            raise ValueError(
                "Wrong Parametrization: Model type NARMAX requested (nlags-x provided), but training data contains only one column (target y). "
                "For NARMAX, at least one input column (X) is required."
            )
        
        if not isinstance(nlags_y, int):
            raise ValueError(
                f"Wrong Parametrization: For Forecasting (NAR) mode, 'nlags-y' must be a single integer, but got {type(nlags_y).__name__}."
            )
        
        return "NAR"
    
    if nlags_x is not None:
        return "NARMAX"
    
    return "NAR"


async def _process_training_task(sd_id: str, job_dir: Path, params: dict):
    """Main background task for model training and evaluation."""
    import warnings
    
    warnings_file = job_dir / "warnings.log"
    caught_warnings = []
    
    try:
        with warnings.catch_warnings(record=True) as local_warnings:
            warnings.simplefilter("always")
            
            # 1. Prepare data
            _extract_zip(job_dir / "input_data.zip", job_dir)
            X, y = _load_training_data(job_dir)
            
            # 2. Validate and determine model mode
            model_type = _validate_and_determine_type(X, y, params)
            
            # 3. Train
            basis_fn = _get_basis_function(params.get('basis', 'Polynomial'), params.get('degree', 2))
            
            try:
                model = _train_model(X, y, params, basis_fn, model_type)
            except Exception as train_err:
                # Handle numerical failures (like SVD did not converge)
                err_msg = str(train_err)
                if "SVD" in err_msg or "converge" in err_msg or "linear" in err_msg:
                    raise ValueError(f"Wrong Parametrization: The model could not be solved (Numerical Error: {err_msg}). Try reducing lags or polynomial degree.")
                raise train_err
            
            # 4. Save
            model_name = params.get('model', 'model')
            model_path = _save_model_native(model, job_dir, model_name)
            (job_dir / "training_completed.marker").touch()
            
            # 5. Evaluate
            await evaluation_service.process_evaluation_internal(sd_id, job_dir, model_name)
            (job_dir / "evaluation_completed.marker").touch()
            
            # Copy captured warnings to outer list before exiting with-block
            caught_warnings = list(local_warnings)
            
        # 6. Final Package
        _create_final_package(sd_id, job_dir, model_path)
        
    except Exception as e:
        if 'local_warnings' in locals():
            caught_warnings = list(local_warnings)
        # Log all errors in English
        (job_dir / "error.log").write_text(f"Task failed: {str(e)}")
        
    finally:
        # Save warnings to log file inside the job directory
        if caught_warnings:
            warnings_text = "".join(f"{w.category.__name__}: {w.message}\n" for w in caught_warnings)
            warnings_file.write_text(warnings_text, encoding="utf-8")


def _train_model(X: Optional[np.ndarray], y: np.ndarray, params: dict, basis_fn, model_type: str) -> FROLS:
    """Initialize and fit the FROLS model based on the determined model type."""
    nlags_y = params.get('nlags_y')
    
    # Base kwargs
    kwargs = {
        'basis_function': basis_fn,
        'ylag': nlags_y,
        'estimator': LeastSquares(),
        'info_criteria': 'aic'
    }
    
    if 'n_info_values' in params and params['n_info_values'] is not None:
        kwargs['n_info_values'] = params['n_info_values']
    
    if model_type == "NARMAX":
        nlags_x = params.get('nlags_x')
        # If user provides a single int (e.g. 2) for MISO, expand to [2, 2, ...]
        if isinstance(nlags_x, int):
            n_inputs = X.shape[1]
            if n_inputs > 1:
                nlags_x = [nlags_x] * n_inputs

        kwargs['xlag'] = nlags_x
        
        model = FROLS(**kwargs)
        model.fit(X=X, y=y)
    else:
        # NAR mode
        kwargs['order_selection'] = True
        kwargs['model_type'] = "NAR"
        
        model = FROLS(**kwargs)
        model.fit(X=None, y=y)
    return model


def _save_model_native(model: FROLS, job_dir: Path, model_name: str) -> Path:
    """Save the model to disk using sysidentpy native format."""
    model_file_name = f"{model_name}.syspy"
    save_model(model=model, file_name=model_file_name, path=str(job_dir))
    return job_dir / model_file_name


def _create_final_package(sd_id: str, job_dir: Path, model_path: Path):
    """Combine model (.syspy) and evaluation results into a single final zip."""
    final_zip_path = job_dir / f"{sd_id}_final.zip"
    with zipfile.ZipFile(final_zip_path, "w") as zf:
        # Include model directly
        zf.write(model_path, arcname=model_path.name)
        # Include evaluation results and warnings
        for f in ["results.csv", "cdf.csv", "metadata.json", "warnings.log"]:
            if (job_dir / f).exists():
                zf.write(job_dir / f, arcname=f)
    return final_zip_path


async def start_training(
    file: UploadFile, 
    background_tasks: BackgroundTasks,
    system_parameters: dict
) -> str:
    """Entry point to start a training job."""
    sd_training_id = str(uuid.uuid4())
    job_dir = STORAGE_DIR / sd_training_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = job_dir / "input_data.zip"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    background_tasks.add_task(_process_training_task, sd_training_id, job_dir, system_parameters)
    return sd_training_id


async def get_model_path(sd_training_id: str) -> Optional[str]:
    """Get path to the final results zip."""
    result_path = STORAGE_DIR / sd_training_id / f"{sd_training_id}_final.zip"
    return str(result_path) if result_path.exists() else None


async def get_status(sd_id: str) -> Optional[dict]:
    """Check progress of a training job based on file presence and error logs."""
    job_dir = STORAGE_DIR / sd_id
    if not job_dir.exists():
        return None
    
    # Check for errors first
    error_log = job_dir / "error.log"
    if error_log.exists():
        return {
            "job_id": sd_id,
            "status": "FAILED",
            "training_status": "FAILED",
            "evaluation_status": "FAILED",
            "error": error_log.read_text()
        }
    
    # Training is COMPLETED if a .syspy model file exists
    syspy_files = list(job_dir.glob("*.syspy"))
    t_done = len(syspy_files) > 0
    
    # Evaluation is COMPLETED if results.csv exists
    e_done = (job_dir / "results.csv").exists()
    
    t_status = "COMPLETED" if t_done else "PROCESSING"
    e_status = "COMPLETED" if e_done else ("PENDING" if not t_done else "PROCESSING")
    
    # Define overall status
    if e_done:
        overall = "COMPLETED"
    elif t_done:
        overall = "EVALUATING"
    else:
        overall = "TRAINING"
    
    return {
        "job_id": sd_id,
        "status": overall,
        "training_status": t_status,
        "evaluation_status": e_status,
        "error": None
    }
