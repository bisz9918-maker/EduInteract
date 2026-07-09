# Test MCP Tool

This directory contains a minimal Python MCP stdio server for OpenAgentHarness testing.

Registered server:

- `test-echo`

Exposed tool names after prefixing:

- `mcp.test.echo`
- `mcp.test.add`
- `mcp.test.now`

The server is dependency-free and starts with:

```bash
python3 /Users/wumengsong/Code/test_oah_server/tools/test-echo/test_echo_mcp.py
```
