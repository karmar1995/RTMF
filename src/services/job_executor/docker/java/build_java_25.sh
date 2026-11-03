#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Pick the simulator Java runtime you want baked into the addon image
export SIM_JAVA="25"
export TECHNOLOGY="java-25"

# Calls the Codex-generated wrapper (the one that expects SIM_JAVA + TECHNOLOGY)
"${SCRIPT_DIR}/build_java_addon.sh" "$@"