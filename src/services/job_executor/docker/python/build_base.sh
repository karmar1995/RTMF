#!/usr/bin/env bash
set -euo pipefail

: "${SIM_PY:?SIM_PY is not set}"
: "${TECHNOLOGY:?TECHNOLOGY is not set}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

export VERSION="$(python3 - <<PY
import tomllib
from pathlib import Path

p = Path(r"${ROOT}") / "pyproject.toml"
with p.open("rb") as f:
    data = tomllib.load(f)

print(data["project"]["version"])
PY
)"

if [[ -n "${BASE_IMAGE:-}" ]]; then
  BASE_IMAGE_REF="${BASE_IMAGE}"
else
  if [[ -z "${HARBOR_BASE:-}" ]]; then
    echo "Error: HARBOR_BASE must be set or BASE_IMAGE provided." >&2
    exit 2
  fi
  BASE_IMAGE_REF="${HARBOR_BASE}/worker-${VERSION}-base-executor"
fi

echo "SIM_PY=${SIM_PY} TECHNOLOGY=${TECHNOLOGY} BASE_IMAGE=${BASE_IMAGE_REF}"

cd "${ROOT}"
"${ROOT}/docker/build.sh" \
  --dockerfile docker/python/Dockerfile \
  --technology "${TECHNOLOGY}" \
  --build-arg "SIM_PY=${SIM_PY}" \
  --build-arg "BASE_IMAGE=${BASE_IMAGE_REF}" \
  "$@"