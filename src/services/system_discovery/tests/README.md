# System Discovery example data

Datasets and configurations for exercising the System Discovery API. Service
startup is described in [Deployment](../../../../docs/DEPLOYMENT.md).

## Subdirectory Structure
- **`test_data/train/`**: Contains datasets and example configurations for model training.
- **`test_data/simulate/`**: Contains models and example configurations for simulation.

*Note: Specific parameter settings are documented in local `README.txt` files inside each sub-folder. In addition, the `degree` parameter is optional (can be None or omitted) if the basis function is other than `Polynomial`.*

## Supported simulation types
- **With external control signal**
- **Without external control signal (forecasting)**


