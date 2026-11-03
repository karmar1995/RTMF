import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[2]


def test_source_distribution_produces_a_wheel_with_working_runtime_assets(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(ROOT / name, source / name)
    shutil.copytree(
        ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info")
    )
    distributions = tmp_path / "dist"
    result = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--sdist", "--outdir", str(distributions), str(source)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    unpacked = tmp_path / "unpacked"
    with tarfile.open(next(distributions.glob("*.tar.gz"))) as archive:
        archive.extractall(unpacked, filter="data")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--wheel", "--outdir", str(distributions), str(next(unpacked.iterdir()))],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    installed = tmp_path / "installed"
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--no-index", "--no-compile", "--target", str(installed), str(next(distributions.glob("*.whl")))],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    # Import only from the installed wheel, with a working directory outside
    # the checkout, so source files cannot conceal missing distribution data.
    result = subprocess.run(
        [sys.executable, "-c", """
from importlib.resources import files
import joblib
from services.front.main import app as front_app

front = files('services.front')
front_app.jinja_env.get_template('index.html')
front_app.jinja_env.get_template('base.html')
assert (front / 'static/js/plotly.min.js').is_file()
assert (front / 'static/js/visualization_polling.js').is_file()

from services.parser.core.resiliency_recognition.src.config import MODEL_PATH
assert callable(joblib.load(MODEL_PATH).predict)

visualization = files('services.visualization') / 'frontend'
assert '<html' in (visualization / 'index.html').read_text().lower()
assert (visualization / 'vs-frontend-testing.html').is_file()
assert (visualization / 'files/plotly.min.js').is_file()
assert (visualization / 'files/line.zip').is_file()

from services.system_discovery.app.main import app
assert '/api/v1/train' in app.openapi()['paths']
assert '/api/v1/simulate' in app.openapi()['paths']
"""],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(installed)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
