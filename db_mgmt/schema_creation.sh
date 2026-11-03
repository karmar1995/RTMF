#!/usr/bin/env bash
set -euo pipefail

# Fail-fast if required env vars are missing/empty
if [[ -z "${RTMF_DB_NAME:-}" ]]; then
  echo "ERROR: RTMF_DB_NAME is not set."
  echo "Please export it in the current shell, e.g.:"
  echo "  export RTMF_DB_NAME=rtmf"
  exit 1
fi

if [[ -z "${RTMF_DB_USER:-}" ]]; then
  echo "ERROR: RTMF_DB_USER is not set."
  echo "Please export it in the current shell, e.g.:"
  echo "  export RTMF_DB_USER=rtmf"
  exit 1
fi

# Run the schema creation script
psql -h localhost \
  -U "$RTMF_DB_USER" \
  -d "$RTMF_DB_NAME" \
  -W \
  -v ON_ERROR_STOP=1 \
  -v db_name="$RTMF_DB_NAME" \
  -v owner_role="$RTMF_DB_USER" \
  -f 01_schema.sql
