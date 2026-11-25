#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PORT="${DASHBOARD_PORT:-8090}"
HOST="${DASHBOARD_HOST:-127.0.0.1}"
exec .venv/bin/python -m reelforge web --host "$HOST" --port "$PORT" "$@"
