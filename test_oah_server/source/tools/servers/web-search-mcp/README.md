# Web Search MCP

This entry registers a remote MCP server exposed at:

```text
http://127.0.0.1:3001/mcp
```

OpenAgentHarness will try to load it from `tools/settings.yaml`.

If this remote MCP server cannot be reached during tool preparation, it should be skipped and not exposed to the LLM.
