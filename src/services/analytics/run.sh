#!/usr/bin/env bash
set -euo pipefail

echo "Deprecated: use python -m services.analytics instead" >&2
exec python -m services.analytics
