# System Discovery

This module is designed for discovering the structure of a system based on historical data and utilizing the discovered models to simulate system behavior. It's based on a third party library SysIdentPy for NAR/NARMAX modeling.

**Key Features:**
- **System Identification:** Automated model identification based on input/output data.
- **System Simulation:** Capability to predict future system states. Including models with external control signals.

## Deployment

Follow the ordered [deployment guide](../../../docs/DEPLOYMENT.md), selecting
`system_discovery` during rendering to run this API independently. It needs no
external infrastructure for standalone training and simulation. The default
Docker publication is port `63800`; open
[the API documentation](http://localhost:63800/docs) after startup.

The container starts through `python -m services.system_discovery` and reads
`services.system_discovery.rest` from the generated runtime JSON. It stores
working files in `/app/storage`; add a volume at that path in the manifest if
they must survive container recreation. Periodic cleanup removes working files
older than 24 hours, including files in a mounted directory.

## API Reference

### 1. Training & Evaluation

#### `POST /api/v1/train`
Starts a background training job followed by automatic evaluation.
- **data**: `.zip` file containing `data_train.csv` (fitting) and `data_test.csv` (evaluation).
- **system_parameters**: Python dictionary string.
  - **Example (MISO)**: `{'nlags-x': [[1,2],[1,2]], 'nlags-y': 1, 'basis': 'Polynomial', 'degree': 1, 'model': 'my_model'}`
  - **nlags-x**: Can be an integer (applied to all inputs) or a nested list for MISO (e.g., `[[1,2], [3,4]]`).
- Returns: `sd_training_id`

#### `GET /api/v1/get_training_status/{sd_training_id}`
Checks the progress of the training and evaluation job.
- **Returns**: 
  ```json
  {
    "job_id": "...",
    "status": "PROCESSING | COMPLETED | FAILED",
    "training_status": "PROCESSING | COMPLETED",
    "evaluation_status": "PENDING | PROCESSING | COMPLETED",
    "error": "Error message if failed"
  }
  ```

#### `GET /api/v1/get_training_results/{sd_training_id}`
Retrieves a `.zip` archive containing:
- Trained model (`*.syspy`)
- Simulation results vs Ground truth for test data (`results.csv`)
- CDF data (`cdf.csv`)
- Metadata (`metadata.json`)

---

### 2. Simulation & Forecasting

#### `POST /api/v1/simulate`
Starts a simulation or forecasting job.
- **data**: `.zip` file containing:
  - Trained model (`*.syspy`)
  - Optional: `data.csv` (Required for models with external control signals - NARMAX).
  - Optional: `initial_conditions.json` (Used only if form parameter is empty).
- **initial_conditions**: (Form parameter) Space-separated values (e.g., `0.7 2.1 3.5`). Overrides JSON file.
- **horizon**: (Optional Form parameter) Number of steps for forecasting (NAR models).
- Returns: `sd_simulation_id`

#### `GET /api/v1/get_simulation_status/{sd_simulation_id}`
Checks the simulation status.
- **Returns**: 
  ```json
  {
    "sd_simulation_id": "...",
    "status": "PROCESSING | COMPLETED | FAILED",
    "error": "Detailed error log if failed"
  }
  ```

#### `GET /api/v1/get_simulation_results/{sd_simulation_id}`
Retrieves a `_final.zip` archive containing `results.csv`.
- **results.csv**: Concatenation of original `data.csv` inputs and the simulation result (`y_sim`). 
- **Format**: Semicolon (`;`) separator.

---

## Model Evaluation

The evaluation methodology is based on the paper:
**Axel Ritter, Rafael Muñoz-Carpena**, *Performance evaluation of hydrological models: Statistical significance for reducing subjectivity in goodness-of-fit assessments*, Journal of Hydrology, Volume 480, 2013, Pages 33-45, ISSN 0022-1694, [https://doi.org/10.1016/j.jhydrol.2012.12.004]

### Statistical Summary (in .json file)

- **NSE & RMSE**: Calculation of Nash-Sutcliffe Efficiency (NSE) and Root Mean Squared Error (RMSE) along with their corresponding 95% confidence intervals (using the BCa bootstrap method).
- **Evaluation Categories**: Qualitative goodness-of-fit interpretation based on "pedigree" classes:
    - **Very good** (NSE ≥ 0.90)
    - **Good** (NSE ≥ 0.80)
    - **Acceptable** (NSE ≥ 0.65)
    - **Unsatisfactory** (NSE < 0.65)
- **p-value**: Probability of wrongly accepting the fit (NSE ≥ threshold=0.65). If the probability of being below the threshold is high, the model may be considered Unsatisfactory.
- **PBIAS (Percent Bias)**: Model bias calculation, indicating overestimation or underestimation.
- **NRMSE**: Normalized Root Mean Squared Error (%) = 100 * RMSE / (Standard Deviation of observations).

---

## Example data

[Example datasets](tests/README.md) cover training, simulation with external
control signals, and forecasting. Submit them through the running API or web
frontend.

## Technical Details
- **Engine**: SysIdentPy (FROLS algorithm).
- **Storage**: All jobs are stored in the `storage/` directory identified by UUIDs.
- **Concurrency**: Handled via FastAPI `BackgroundTasks`.
