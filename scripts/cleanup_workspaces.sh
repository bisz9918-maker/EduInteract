#!/usr/bin/env bash
# Delete all OAH workspaces (MinIO object data + PostgreSQL records)
set -euo pipefail

OAH_API="${OAH_API_URL:-http://localhost:8787}"
MINIO_HOST="${MINIO_HOST:-localhost:9000}"
MINIO_USER="${MINIO_ROOT_USER:-oahadmin}"
MINIO_PASS="${MINIO_ROOT_PASSWORD:-oahadmin123}"
MINIO_BUCKET="${MINIO_BUCKET:-test-oah-server}"
PG_CONTAINER="${PG_CONTAINER:-openagentharness-postgres-1}"
MINIO_CONTAINER="${MINIO_CONTAINER:-openagentharness-minio-1}"
DB_NAME="${DB_NAME:-open_agent_harness}"
DB_USER="${DB_USER:-oah}"

# 1. Delete workspace objects from MinIO
echo "Cleaning MinIO workspace objects..."
docker exec "$MINIO_CONTAINER" mc alias set local "http://$MINIO_HOST" "$MINIO_USER" "$MINIO_PASS" 2>/dev/null || true
docker exec "$MINIO_CONTAINER" mc rm --recursive --force "local/$MINIO_BUCKET/workspace/" 2>/dev/null || true

# 2. Delete workspace records from PostgreSQL
echo "Cleaning PostgreSQL workspace records..."
docker exec "$PG_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "DELETE FROM workspaces;" 2>/dev/null || true

# 3. Verify
count=$(curl -s "$OAH_API/api/v1/workspaces" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['items']))" 2>/dev/null || echo "?")
echo "Done. Remaining workspaces: $count"
