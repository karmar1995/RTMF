#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

TECHNOLOGY="executor"
DOCKERFILE="docker/base/Dockerfile"

export VERSION="$(python3 - <<PY
import tomllib
from pathlib import Path

p = Path(r"${ROOT}") / "pyproject.toml"
with p.open("rb") as f:
    data = tomllib.load(f)

print(data["project"]["version"])
PY
)"

echo "VERSION=${VERSION} TECHNOLOGY=${TECHNOLOGY} DOCKERFILE=${DOCKERFILE}"

"${ROOT}/docker/build.sh" \
  --dockerfile "${DOCKERFILE}" \
  --technology "${TECHNOLOGY}" \
  "$@"