#!/usr/bin/env python3
"""A tiny MCP stdio server for OpenAgentHarness testing.

This server intentionally uses only Python's standard library so it can run
with `python3` out of the box.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from typing import Any


PROTOCOL_VERSION = "2025-11-25"
SERVER_NAME = "test-echo-mcp"
SERVER_VERSION = "0.1.0"


def write_message(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
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
        "content": [
            {
                "type": "text",
                "text": text,
            }
        ]
    }
    if is_error:
        payload["isError"] = True
    return payload


def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "echo":
        text = str(arguments.get("text", ""))
        uppercase = bool(arguments.get("uppercase", False))
        result = text.upper() if uppercase else text
        return text_result(f"echo: {result}")

    if name == "add":
        a = arguments.get("a")
        b = arguments.get("b")
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return text_result("add requires numeric arguments: a, b", is_error=True)
        return text_result(f"sum: {a + b}")

    if name == "now":
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        return text_result(f"utc_now: {now}")

    return text_result(f"unknown tool: {name}", is_error=True)


def tools_definition() -> list[dict[str, Any]]:
    return [
        {
            "name": "echo",
            "description": "Echo back the provided text. Useful for MCP wiring tests.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to echo back."},
                    "uppercase": {
                        "type": "boolean",
                        "description": "Whether to convert the text to uppercase before returning.",
                        "default": False,
                    },
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
        {
            "name": "add",
            "description": "Add two numbers and return the sum.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
                "additionalProperties": False,
            },
        },
        {
            "name": "now",
            "description": "Return the current UTC timestamp.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
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
                "capabilities": {"tools": {}},
            },
        )
        return

    if method == "ping":
        reply(message_id, {})
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
            error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request")
            continue

        try:
            handle_message(message)
        except Exception as exc:  # pragma: no cover - defensive test utility
            error(message.get("id"), -32000, f"Server error: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
