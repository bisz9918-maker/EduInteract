#!/usr/bin/env python3
"""HTTP MCP server for reading image files.

Returns image content as MCP image blocks so the model can see the image,
bypassing the native Read tool's UTF-8 limitation on binary files.

Uses HTTP transport so OAH's compatibility client correctly converts
MCP image content to image-data for the model (stdio MCP tools lose
image data through normalizeToolResultOutput).

File access: reads from READ_IMAGE_ROOT env var, or falls back to cwd.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlparse

PROTOCOL_VERSION = "2025-11-25"
SERVER_NAME = "read-image-mcp"
SERVER_VERSION = "0.1.0"

READ_IMAGE_ROOT = os.environ.get("READ_IMAGE_ROOT", "") or os.getcwd()
PORT = int(os.environ.get("READ_IMAGE_PORT", "3002"))

SUPPORTED_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}


def resolve_path(file_path: str) -> str | None:
    """Resolve file_path against READ_IMAGE_ROOT, preventing path traversal."""
    if not READ_IMAGE_ROOT:
        return None
    abs_path = os.path.realpath(os.path.join(READ_IMAGE_ROOT, file_path))
    ws_root = os.path.realpath(READ_IMAGE_ROOT)
    if not abs_path.startswith(ws_root + os.sep) and abs_path != ws_root:
        return None
    return abs_path


def read_image(file_path: str) -> dict[str, Any]:
    if not file_path:
        return {"content": [{"type": "text", "text": "file_path is required"}], "isError": True}

    abs_path = resolve_path(file_path)
    if abs_path is None:
        return {
            "content": [{"type": "text", "text": "Cannot resolve path (root not set or path traversal detected)"}],
            "isError": True,
        }

    if not os.path.isfile(abs_path):
        return {"content": [{"type": "text", "text": f"File not found: {file_path}"}], "isError": True}

    ext = os.path.splitext(abs_path)[1].lower()
    media_type = SUPPORTED_EXTENSIONS.get(ext)
    if not media_type:
        media_type = mimetypes.guess_type(abs_path)[0] or "application/octet-stream"

    if media_type == "image/svg+xml":
        with open(abs_path, "r", encoding="utf-8") as f:
            svg_text = f.read()
        return {"content": [{"type": "text", "text": f"SVG file: {file_path}\n\n{svg_text}"}]}

    try:
        with open(abs_path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return {"content": [{"type": "text", "text": f"Failed to read file: {e}"}], "isError": True}

    size_kb = len(raw) / 1024
    data_b64 = base64.b64encode(raw).decode("ascii")

    return {
        "content": [
            {"type": "text", "text": f"Image file: {file_path} ({media_type}, {size_kb:.1f} KB)"},
            {"type": "image", "data": data_b64, "mimeType": media_type},
        ]
    }


TOOLS_DEFINITION = [
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


class McpHttpHandler(BaseHTTPRequestHandler):
    sessions: dict[str, dict] = {}

    def log_message(self, format, *args):
        print(f"[read-image-mcp] {args[0]}")

    def _send_json(self, status: int, body: Any, session_id: str | None = None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if session_id:
            self.send_header("Mcp-Session-Id", session_id)
        self.end_headers()
        self.wfile.write(json.dumps(body, ensure_ascii=False).encode("utf-8"))

    def _send_accepted(self):
        self.send_response(202)
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            message = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}})
            return

        session_id = self.headers.get("Mcp-Session-Id")
        method = message.get("method", "")
        msg_id = message.get("id")
        params = message.get("params", {})

        if method == "initialize":
            sid = session_id or str(uuid.uuid4())
            self.sessions[sid] = {"initialized": False}
            self._send_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                        "capabilities": {"tools": {"listChanged": False}},
                    },
                },
                sid,
            )
            return

        if method == "notifications/initialized":
            if session_id and session_id in self.sessions:
                self.sessions[session_id]["initialized"] = True
            self._send_accepted()
            return

        if method == "ping":
            self._send_json(200, {"jsonrpc": "2.0", "id": msg_id, "result": {}}, session_id)
            return

        if method == "tools/list":
            self._send_json(
                200,
                {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS_DEFINITION}},
                session_id,
            )
            return

        if method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments", {})
            if name == "read_image":
                result = read_image(arguments.get("file_path", ""))
            else:
                result = {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
            self._send_json(
                200,
                {"jsonrpc": "2.0", "id": msg_id, "result": result},
                session_id,
            )
            return

        if msg_id is not None:
            self._send_json(
                200,
                {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}},
                session_id,
            )
            return

        self._send_accepted()

    def do_DELETE(self):
        session_id = self.headers.get("Mcp-Session-Id")
        if session_id and session_id in self.sessions:
            del self.sessions[session_id]
        self.send_response(204)
        self.end_headers()


def main():
    print(f"[read-image-mcp] Starting HTTP MCP server on port {PORT}")
    print(f"[read-image-mcp] READ_IMAGE_ROOT={READ_IMAGE_ROOT}")
    server = HTTPServer(("0.0.0.0", PORT), McpHttpHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[read-image-mcp] Shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
