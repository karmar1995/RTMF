#!/usr/bin/env bash
set -euo pipefail

echo "Deprecated: use python -m services.matrix_generation instead" >&2
exec python -m services.matrix_generation
