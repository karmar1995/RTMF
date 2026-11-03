from pathlib import Path

# Data Processing Parameters
WINDOW_SIZE = 20
MEDIAN_FILTER_WINDOW = 5
STANDARDIZATION_MODE = 'global'

# Model Configuration
MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "RF_model_v1.pkl"

# File and Column Names
METRIC_COLUMN = "metric"
