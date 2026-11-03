#!/usr/bin/env bash
set -euo pipefail

echo "Deprecated: use python -m services.jobs_scheduler instead" >&2
exec python -m services.jobs_scheduler
