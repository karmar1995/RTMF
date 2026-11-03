import pandas as pd
import json
from pathlib import Path
import config

class DataHandler:
    def __init__(self, extract_path: Path, result_filename: str):
        self.extract_path = extract_path
        self.result_filename = result_filename

    def load_metric_csv(self) -> pd.DataFrame:
        """
        Loads the first CSV file found in the extracted directory.
        Strictly follows the requirement:
        - Separator is ';'
        - Columns: 'time' (always) and a dynamic parameter name.
        """
        # Search for any CSV file recursively
        csv_files = list(self.extract_path.rglob("*.csv"))
        
        if not csv_files:
            raise FileNotFoundError(f"Could not find any CSV file in {self.extract_path}")
        
        filepath = csv_files[0]
        print(f"Loading data from: {filepath}")
        
        # Load with semicolon separator
        # Using low_memory=False to avoid DtypeWarning on large files
        df = pd.read_csv(filepath, sep=';', low_memory=False)
        
        # Identify the metric column (the one that is NOT 'time')
        # We assume 'time' is always present as stated in requirements
        other_cols = [c for c in df.columns if c.lower() != 'time']
        
        if not other_cols:
            raise ValueError(f"CSV file at {filepath} must contain at least one column other than 'time'.")
        
        # Rename the parameter column to a standard internal name for the analyzer
        metric_col_name = other_cols[0]
        df = df.rename(columns={metric_col_name: config.METRIC_COLUMN})
        
        print(f"Identified parameter column: '{metric_col_name}' -> mapped to '{config.METRIC_COLUMN}'")
        
        return df

    def save_results(self, phases: list, metrics: dict):
        """Saves the final results in JSON format."""
        result = {
            "phases": phases,
            "metrics": metrics
        }
        with open(self.result_filename, "w") as f:
            json.dump(result, f, indent=4)
