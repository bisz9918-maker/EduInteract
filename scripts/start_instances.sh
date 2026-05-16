#!/usr/bin/env bash
# Start 6 OAH daemon instances with increased V8 heap size.
# Usage: bash scripts/start_instances.sh [start|stop|restart]
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OAH_DIR="${OAH_DIR:-$BASE_DIR/../oah}"
NODE_OPTIONS="--max-old-space-size=131072"
export NODE_OPTIONS

start_instance() {
    local i=$1
    local config="$BASE_DIR/oah_instance_$i/daemon.yaml"
    if [ ! -f "$config" ]; then
        echo "Instance $i config not found: $config"
        return 1
    fi
    echo "Starting instance $i (port $(grep 'port:' "$config" | head -1 | awk '{print $2}'))..."
    nohup pnpm --dir "$OAH_DIR" exec tsx \
        --tsconfig "$OAH_DIR/apps/server/tsconfig.json" \
        "$OAH_DIR/apps/server/src/index.ts" \
        -- --config "$config" \
        > "$BASE_DIR/logs/instance_$i.log" 2>&1 &
    echo "  PID=$!"
}

stop_instance() {
    local i=$1
    local pidfile="$BASE_DIR/oah_instance_$i/state/data/daemon.pid"
    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            echo "Stopping instance $i (PID $pid)..."
            kill "$pid" 2>/dev/null || true
        else
            echo "Instance $i (PID $pid) already stopped"
        fi
    else
        echo "Instance $i: no PID file found"
    fi
}

case "${1:-start}" in
    start)
        # Clean up state before starting
        echo "Cleaning instance state directories..."
        bash "$BASE_DIR/scripts/cleanup_state.sh"
        echo ""
        mkdir -p "$BASE_DIR/logs"
        echo "Starting OAH instances with NODE_OPTIONS=$NODE_OPTIONS"
        for i in 1 2 3 4 5 6; do
            start_instance "$i"
        done
        echo ""
        echo "All instances started. Use 'bash $0 stop' to stop them."
        ;;
    stop)
        for i in 1 2 3 4 5 6; do
            stop_instance "$i"
        done
        echo "All instances stopped."
        ;;
    restart)
        bash "$0" stop
        sleep 2
        bash "$0" start
        ;;
    *)
        echo "Usage: bash $0 [start|stop|restart]"
        exit 1
        ;;
esac
