#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

MANAGED_PATH_DIR_NAMES: dict[str, str] = {
    "workspace_dir": "workspaces",
    "runtime_dir": "runtimes",
    "model_dir": "models",
    "tool_dir": "tools",
    "skill_dir": "skills",
}

REMOTE_PREFIX_BY_PATH_KEY: dict[str, str] = {
    "workspace_dir": "workspace",
    "runtime_dir": "runtime",
    "model_dir": "model",
    "tool_dir": "tool",
    "skill_dir": "skill",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync OAH source directories into the local MinIO bucket via dockerized aws-cli."
    )
    parser.add_argument(
        "--root",
        default=os.environ.get("OAH_TEST_ROOT"),
        help=(
            "Root directory of the test environment. Defaults to $OAH_TEST_ROOT. "
            "Expected layout: <root>/source, <root>/scripts, <root>/server.docker.yaml."
        ),
    )
    parser.add_argument(
        "--bucket",
        default="test-oah-server",
        help="Target bucket name. Defaults to test-oah-server.",
    )
    parser.add_argument(
        "--aws-endpoint-url",
        default=os.environ.get("MINIO_AWS_ENDPOINT_URL", "http://host.docker.internal:9000"),
        help="MinIO endpoint reachable from the aws-cli Docker container.",
    )
    parser.add_argument(
        "--access-key",
        default=os.environ.get("MINIO_ROOT_USER", "oahadmin"),
        help="MinIO access key. Defaults to oahadmin.",
    )
    parser.add_argument(
        "--secret-key",
        default=os.environ.get("MINIO_ROOT_PASSWORD", "oahadmin123"),
        help="MinIO secret key. Defaults to oahadmin123.",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", "us-east-1"),
        help="AWS region passed to aws-cli. Defaults to us-east-1.",
    )
    parser.add_argument(
        "--source-root",
        default=None,
        help=(
            "Root directory containing source folders such as workspaces/, runtimes/, tools/, "
            "skills/, and models/. Defaults to <config-dir>/source."
        ),
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete remote objects that no longer exist locally for each synced prefix.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the sync plan without executing aws-cli commands.",
    )
    return parser.parse_args()


def aws_docker_command(
    aws_args: list[str],
    *,
    endpoint_url: str,
    access_key: str,
    secret_key: str,
    region: str,
    mount_dir: Path | None = None,
) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "-e",
        f"AWS_ACCESS_KEY_ID={access_key}",
        "-e",
        f"AWS_SECRET_ACCESS_KEY={secret_key}",
        "-e",
        f"AWS_DEFAULT_REGION={region}",
    ]

    if mount_dir is not None:
        command.extend(["-v", f"{mount_dir}:/sync-source:ro"])

    command.extend(
        [
            "amazon/aws-cli:latest",
            "--endpoint-url",
            endpoint_url,
            *aws_args,
        ]
    )
    return command


def run_command(command: list[str], *, dry_run: bool) -> None:
    printable = " ".join(subprocess.list2cmdline([part]) for part in command)
    print(f"$ {printable}")
    if dry_run:
        return

    subprocess.run(command, check=True)


def ensure_bucket(args: argparse.Namespace) -> None:
    head_cmd = aws_docker_command(
        ["s3api", "head-bucket", "--bucket", args.bucket],
        endpoint_url=args.aws_endpoint_url,
        access_key=args.access_key,
        secret_key=args.secret_key,
        region=args.region,
    )

    if args.dry_run:
        print(f"Would ensure bucket exists: {args.bucket}")
        return

    result = subprocess.run(head_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
        print(f"Bucket already exists: {args.bucket}")
        return

    create_cmd = aws_docker_command(
        ["s3api", "create-bucket", "--bucket", args.bucket],
        endpoint_url=args.aws_endpoint_url,
        access_key=args.access_key,
        secret_key=args.secret_key,
        region=args.region,
    )
    run_command(create_cmd, dry_run=False)


def load_publish_paths(test_root: Path, source_root: Path | None) -> dict[str, Path]:
    resolved_source_root = source_root or (test_root / "source").resolve()
    return {
        path_key: (resolved_source_root / directory_name).resolve()
        for path_key, directory_name in MANAGED_PATH_DIR_NAMES.items()
    }


def sync_directory(args: argparse.Namespace, path_key: str, directory: Path) -> None:
    if not directory.exists():
        print(f"Skipping missing path for {path_key}: {directory}", file=sys.stderr)
        return
    if not directory.is_dir():
        print(f"Skipping non-directory path for {path_key}: {directory}", file=sys.stderr)
        return

    remote_prefix = REMOTE_PREFIX_BY_PATH_KEY[path_key]
    remote_uri = f"s3://{args.bucket}/{remote_prefix}/"
    sync_args = [
        "s3",
        "sync",
        "/sync-source",
        remote_uri,
        "--exclude",
        ".DS_Store",
        "--exclude",
        "*/.DS_Store",
        "--exclude",
        "__pycache__/*",
        "--exclude",
        "*/__pycache__/*",
        "--exclude",
        "*.pyc",
        "--exclude",
        "*.db-shm",
        "--exclude",
        "*.db-wal",
    ]
    if args.delete:
        sync_args.append("--delete")

    sync_cmd = aws_docker_command(
        sync_args,
        endpoint_url=args.aws_endpoint_url,
        access_key=args.access_key,
        secret_key=args.secret_key,
        region=args.region,
        mount_dir=directory,
    )
    run_command(sync_cmd, dry_run=args.dry_run)


def main() -> int:
    args = parse_args()
    if not args.root:
        raise SystemExit("Test root not provided. Pass --root or set OAH_TEST_ROOT.")

    test_root = Path(args.root).expanduser().resolve()
    if not test_root.exists():
        raise SystemExit(f"Test root not found: {test_root}")

    source_root = Path(args.source_root).expanduser().resolve() if args.source_root else None
    path_map = load_publish_paths(test_root, source_root)

    print(f"Test root: {test_root}")
    print(f"Docker aws-cli endpoint: {args.aws_endpoint_url}")
    print(f"Target bucket: {args.bucket}")
    print(f"Source root: {(source_root or (test_root / 'source').resolve())}")

    ensure_bucket(args)
    for path_key, directory in path_map.items():
        sync_directory(args, path_key, directory)

    print("Sync complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
