#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export SIM_PY="3.13"
export TECHNOLOGY="python-313"

"${SCRIPT_DIR}/build_base.sh" "$@"