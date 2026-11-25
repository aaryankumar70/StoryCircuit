#!/usr/bin/env bash
# StoryCircuit Desktop WebApp Launcher
set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"

if [ -f "$DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$DIR/.env" || true
    set +a
fi

PORT="${DASHBOARD_PORT:-8090}"
HOST="${DASHBOARD_HOST:-127.0.0.1}"
URL="http://${HOST}:${PORT}/"
HEALTH_URL="http://${HOST}:${PORT}/api/status"

mkdir -p "$DIR/data"

if ! curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
    echo "Starting StoryCircuit Studio server on ${URL}..."
    nohup "$DIR/start_dashboard.sh" >"$DIR/data/studio.log" 2>&1 &

    for _ in $(seq 1 50); do
        if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
            break
        fi
        sleep 0.2
    done
fi

exec omarchy-launch-webapp "$URL"
