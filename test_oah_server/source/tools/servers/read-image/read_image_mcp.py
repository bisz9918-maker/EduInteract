#!/usr/bin/env python3
"""MCP tool server for reading image files from the workspace.

Returns image content as base64-encoded data so the model can see the image,
bypassing the native Read tool's UTF-8 limitation on binary files.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
from typing import Any

PROTOCOL_VERSION = "2025-11-25"
SERVER_NAME = "read-image-mcp"
SERVER_VERSION = "0.1.0"

WORKSPACE_ROOT = os.environ.get("OPENHARNESS_WORKSPACE_ROOT", "") or os.getcwd()


def write_message(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def reply(message_id: Any, result: dict[str, Any]) -> None:
    write_message({"jsonrpc": "2.0", "id": message_id, "result": result})


def error(message_id: Any, code: int, message: str) -> None:
    write_message(
        {
            "jsonrpc": "2.0",
            "id": message_id,
            "error": {"code": code, "message": message},
        }
    )


def text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": [{"type": "text", "text": text}]
    }
    if is_error:
        payload["isError"] = True
    return payload


def resolve_path(file_path: str) -> str | None:
    """Resolve file_path against workspace root, preventing path traversal."""
    if not WORKSPACE_ROOT:
        return None
    abs_path = os.path.realpath(os.path.join(WORKSPACE_ROOT, file_path))
    ws_root = os.path.realpath(WORKSPACE_ROOT)
    if not abs_path.startswith(ws_root + os.sep) and abs_path != ws_root:
        return None
    return abs_path


SUPPORTED_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}


def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name != "read_image":
        return text_result(f"unknown tool: {name}", is_error=True)

    file_path = arguments.get("file_path", "")
    if not file_path:
        return text_result("file_path is required", is_error=True)

    abs_path = resolve_path(file_path)
    if abs_path is None:
        return text_result(
            f"Cannot resolve path (workspace root not set or path traversal detected)",
            is_error=True,
        )

    if not os.path.isfile(abs_path):
        return text_result(f"File not found: {file_path}", is_error=True)

    ext = os.path.splitext(abs_path)[1].lower()
    media_type = SUPPORTED_EXTENSIONS.get(ext)
    if not media_type:
        media_type = mimetypes.guess_type(abs_path)[0] or "application/octet-stream"

    if media_type == "image/svg+xml":
        with open(abs_path, "r", encoding="utf-8") as f:
            svg_text = f.read()
        return text_result(f"SVG file: {file_path}\n\n{svg_text}")

    try:
        with open(abs_path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return text_result(f"Failed to read file: {e}", is_error=True)

    size_kb = len(raw) / 1024
    data_b64 = base64.b64encode(raw).decode("ascii")

    return {
        "content": [
            {"type": "text", "text": f"Image file: {file_path} ({media_type}, {size_kb:.1f} KB)"},
            {"type": "image", "data": data_b64, "mimeType": media_type},
        ]
    }


def tools_definition() -> list[dict[str, Any]]:
    return [
        {
            "name": "read_image",
            "description": (
                "Read an image file from the workspace and return it as a visual content block. "
                "Supports PNG, JPEG, GIF, WebP, BMP, and SVG formats. "
                "Use this instead of the Read tool for image files, since Read cannot handle binary data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the image file relative to the workspace root.",
                    }
                },
                "required": ["file_path"],
                "additionalProperties": False,
            },
        }
    ]


def handle_message(message: dict[str, Any]) -> None:
    method = message.get("method")
    message_id = message.get("id")

    if method == "initialize":
        reply(
            message_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "capabilities": {"tools": {"listChanged": False}},
            },
        )
        return

    if method == "ping":
        reply(message_id, {})
        return

    if method == "notifications/initialized":
        # Acknowledge initialized notification (no reply needed for notifications)
        return

    if method == "tools/list":
        reply(message_id, {"tools": tools_definition()})
        return

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str):
            reply(message_id, text_result("missing tool name", is_error=True))
            return
        if not isinstance(arguments, dict):
            reply(message_id, text_result("tool arguments must be an object", is_error=True))
            return
        reply(message_id, handle_tool_call(name, arguments))
        return

    if message_id is not None:
        error(message_id, -32601, f"Method not found: {method}")


def main() -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            error(None, -32700, f"Parse error: {exc}")
            continue

        if not isinstance(message, dict):
            error(
                message.get("id") if isinstance(message, dict) else None,
                -32600,
                "Invalid Request",
            )
            continue

        try:
            handle_message(message)
        except Exception as exc:
            error(message.get("id"), -32000, f"Server error: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
