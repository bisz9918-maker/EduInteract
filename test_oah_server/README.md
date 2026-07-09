# test_oah_server

This directory is now just the external test-data root used by `OAH_TEST_ROOT`.

## Current Layout

- `server.docker.yaml`: config mounted into the OAH container
- `source/`: source-of-truth data that should exist in MinIO
- `source/README.md`: explanation of each source subdirectory and bucket prefix mapping
- `scripts/sync_to_minio.py`: pushes `source/` into the MinIO bucket

Only one file here is read by OAH directly at runtime:

- `server.docker.yaml`

Everything else in this directory exists to prepare test data for MinIO.

## How `pnpm storage:sync` Works

From the OAH repo root, `pnpm storage:sync` runs:

```bash
python3 $OAH_TEST_ROOT/scripts/sync_to_minio.py --root $OAH_TEST_ROOT --delete
```

What the script does:

1. Treats `$OAH_TEST_ROOT/source` as the only local source of truth.
2. Ensures bucket `test-oah-server` exists in MinIO.
3. Syncs each local source directory to its bucket prefix:
   - `source/workspaces` -> `s3://test-oah-server/workspace/`
   - `source/runtimes` -> `s3://test-oah-server/runtime/`
   - `source/models` -> `s3://test-oah-server/model/`
   - `source/tools` -> `s3://test-oah-server/tool/`
   - `source/skills` -> `s3://test-oah-server/skill/`
4. Because it uses `--delete`, remote files missing from `source/` are removed from the bucket too.

Implementation detail:

- The script does not talk to MinIO directly from Python.
- It launches `amazon/aws-cli` in Docker and mounts each local source directory read-only into that container.
- Then it runs `aws s3 sync` against MinIO's S3-compatible endpoint.

## Operational Rule

If you want to change test data, edit files only under `source/`.

Before syncing, make sure the local Docker stack is already up so MinIO is reachable.

Then rerun:

```bash
cd /Users/wumengsong/Code/OpenAgentHarness
export OAH_TEST_ROOT=/Users/wumengsong/Code/test_oah_server
pnpm storage:sync
```

For first startup, `pnpm local:up` already waits for MinIO and runs one sync automatically.

## Mental Model

- `server.docker.yaml` answers: how should the OAH container run?
- `source/` answers: what data should exist in object storage?
- `pnpm storage:sync` answers: copy local source data into MinIO now.
