# source

This directory is the local source of truth for test data published to MinIO.

After editing anything here, run:

```bash
cd /Users/wumengsong/Code/OpenAgentHarness
export OAH_TEST_ROOT=/Users/wumengsong/Code/test_oah_server
pnpm storage:sync
```

## Mapping

| Local directory | Bucket prefix | Purpose |
| --- | --- | --- |
| `workspaces/` | `workspace/` | Workspace runtime data |
| `runtimes/` | `runtime/` | Workspace runtimes |
| `models/` | `model/` | Model config YAML files |
| `tools/` | `tool/` | Tool config and tool server definitions |
| `skills/` | `skill/` | Reusable skill packages |

## Editing Rules

- Only treat this directory as editable source data.
- Do not recreate `local/` mirrors here. That old host-mode layout is retired.
- Do not store MinIO runtime data here. Docker volumes hold actual MinIO state now.
- `pnpm storage:sync` uses `--delete`, so remote files missing here will be deleted from the bucket.

## Notes

- `runtimes/`, `tools/`, and `skills/` are mounted directly into the OAH container through the Docker `rclone` volume plugin.
- `workspaces/` are still synced through OAH object storage logic and live on Docker local volumes at runtime.
- Bucket prefix `runtime/` matches the current server-side runtime config and mounted directory layout.
