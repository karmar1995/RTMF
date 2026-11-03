import sys
import os
import argparse
import zipfile
from pathlib import Path
class Settings:
    STATUS_FILENAME = "status.txt"
    INPUT_FILENAME = "input.zip"
    RESULT_FILENAME = "result.json"
    ERROR_FILENAME = "error.txt"

settings = Settings()

# Import our new components
from analyzer import ResiliencyAnalyzer
from data_handler import DataHandler
from metrics_service import MetricsService
import config

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=float, required=False, help="Baseline for analysis")
    args = parser.parse_args()

    try:
        # Write initial status
        with open(settings.STATUS_FILENAME, "w") as f:
            f.write("STARTED")
        
        # 1. Unpack the input zip file directly to the task directory
        extract_path = Path(".")
        
        print(f"Unpacking {settings.INPUT_FILENAME} to current directory...")
        with zipfile.ZipFile(settings.INPUT_FILENAME, 'r') as zip_ref:
            zip_ref.extractall(extract_path)

        # 2. Setup Components
        handler = DataHandler(extract_path, settings.RESULT_FILENAME)
        model_path = config.MODEL_PATH
        analyzer = ResiliencyAnalyzer(model_path)
        
        # 3. Load Data
        print("Searching for CSV data...")
        df = handler.load_metric_csv()
        
        # 4. Run Analysis
        print("Running resiliency analysis...")
        phases = analyzer.process(df)
        
        # 5. Calculate Metrics
        print("Calculating metrics...")
        metrics_service = MetricsService()
        metrics = metrics_service.calculate_metrics(df, phases, baseline=args.baseline)
        
        # 6. Save results
        print("Saving results...")
        handler.save_results(phases, metrics)
            
        # Write final status
        with open(settings.STATUS_FILENAME, "w") as f:
            f.write("COMPLETED")
            
    except Exception as e:
        print(f"Error: {e}")
        with open(settings.STATUS_FILENAME, "w") as f:
            f.write("FAILED")
        with open(settings.ERROR_FILENAME, "w") as f:
            f.write(f"Error during analysis: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()

