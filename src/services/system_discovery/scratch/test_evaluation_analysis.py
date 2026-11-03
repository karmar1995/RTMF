import sys
from pathlib import Path

# Add the repository's src directory for standalone execution.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from services.system_discovery.app.services.statistical_evaluation import run_evaluation_pipeline

# Path to the real results.csv
results_path = Path("storage/13b0a7d4-c66e-4619-9c34-4413fcf26d63/results.csv")
temp_dir = Path("scratch/temp_eval")
temp_dir.mkdir(exist_ok=True)

# Copy results.csv to temp dir
import shutil
shutil.copy(results_path, temp_dir / "results.csv")

print("Running evaluation pipeline...")
run_evaluation_pipeline(temp_dir / "results.csv", temp_dir)

# Read and print metadata.json
metadata_path = temp_dir / "metadata.json"
if metadata_path.exists():
    print("\nGenerated metadata.json:")
    print(metadata_path.read_text(encoding="utf-8"))
else:
    print("Failed to generate metadata.json!")
