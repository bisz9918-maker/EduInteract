#!/usr/bin/env bash
# Clean up OAH instance state directories before starting.
# This removes accumulated SQLite history.db files that can grow to
# tens of GB and cause V8 OOM crashes when the server reads them back.
# Usage: bash scripts/cleanup_state.sh [INSTANCE_RANGE]
# Example: bash scripts/cleanup_state.sh 1-11
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

INSTANCE_RANGE="${1:-1-6}"
RANGE_START="${INSTANCE_RANGE%-*}"
RANGE_END="${INSTANCE_RANGE#*-}"

for i in $(seq "$RANGE_START" "$RANGE_END"); do
    state_dir="$BASE_DIR/oah_instance_$i/state"
    if [ -d "$state_dir" ]; then
        size=$(du -sh "$state_dir" 2>/dev/null | cut -f1)
        echo "Cleaning instance $i state ($size): $state_dir"
        rm -rf "$state_dir"/*
    else
        echo "Instance $i state dir not found: $state_dir"
    fi
done

echo "Done. All instance state directories cleaned."
