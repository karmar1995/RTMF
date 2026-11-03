#!/bin/sh
set -e

exec python -m services.parser "$@"
