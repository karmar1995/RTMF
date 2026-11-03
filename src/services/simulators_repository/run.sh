#!/usr/bin/env bash
set -euo pipefail

echo "Deprecated: use python -m services.simulators_repository instead" >&2
exec python -m services.simulators_repository
