# VisualSolver MCP Server

通过 HTTP/SSE 方式将教育图示生成功能封装为 MCP (Model Context Protocol) 工具。

## 快速开始

### 1. 安装依赖

```bash
pip install fastmcp
```

### 2. 启动服务器

```bash
cd /path/to/VisualSolver
python mcp_server.py
```

默认监听 `http://0.0.0.0:8000`。

```bash
# 自定义地址和端口
MCP_HOST=127.0.0.1 MCP_PORT=8088 python mcp_server.py
```

---

## 可用工具

### `generate_diagram_and_text`

对给定题目生成图文解析（HTML 图示 + Markdown 文字）。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `problem` | str | ✅ | — | 题目文本 |
| `output_dir` | str | ✅ | — | 输出根目录（绝对路径） |
| `topic` | str | — | 自动生成 | 输出子目录名（如 `problem_1_math`）。不传则自动生成唯一 ID，并发安全 |
| `image_path` | str | — | `null` | 题目配图的绝对路径（PNG/JPG） |
| `model` | str | — | `gemini-3-pro-preview` | 使用的 AI 模型 |
| `max_retries` | int | — | `3` | 每个场景代码生成的最大重试次数 |
| `max_scene_concurrency` | int | — | `5` | 场景并发生成数 |
| `translate_to_chinese` | bool | — | `true` | 是否将文字解析翻译为中文 |

**返回：**

```json
{
  "success": true,
  "topic": "problem_1_math",
  "output_dir": "/path/to/output/problem_1_math",
  "solution_html": "/path/to/output/problem_1_math/doc/solution.html",
  "solution_md": "/path/to/output/problem_1_math/doc/solution.md",
  "time_seconds": 42.3
}
```

**输出目录结构：**

```
{output_dir}/{topic}/
├── doc/
│   ├── solution.html        # 主文件：图示与文字穿插的完整解析页面
│   ├── solution.md          # 纯文字解析（Markdown）
│   ├── scene1.html          # 各场景独立 HTML
│   └── scene2.html
├── scene1/
│   └── code/
│       └── *_scene1_v0.html
├── scene2/
│   └── ...
├── problem_diagram.png      # 题目原图（若提供 image_path）
└── *_scene_outline.txt      # 生成的场景大纲
```

**示例调用（Python MCP 客户端）：**

```python
result = await session.call_tool(
    "generate_diagram_and_text",
    arguments={
        "problem": "如图，Rt△ABC 中，AC=6，BC=8，以 AC 为直径的圆与 AB 交于点 D，求 BD。",
        "output_dir": "/path/to/output",
        "topic": "problem_65_math_g12",
        "model": "claude-sonnet-4-6",
        "translate_to_chinese": True
    }
)
```

---

### `list_available_models`

列出所有可用的 AI 模型。

**参数：** 无

**返回：**

```json
{
  "success": true,
  "models": ["gemini-3-pro-preview", "claude-sonnet-4-6", "Kimi-K25", "..."],
  "count": 10
}
```

---

### `png_to_base64`

将 PNG 图片转换为 base64 字符串（可选缩放）。

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `image_path` | str | ✅ | 图片文件绝对路径 |
| `resize_width` | int | — | 目标宽度（保持宽高比，仅指定宽时）|
| `resize_height` | int | — | 目标高度（保持宽高比，仅指定高时）|

**返回：**

```json
{
  "success": true,
  "base64": "/9j/4AAQSkZJRg...",
  "format": "PNG",
  "original_size": [1920, 1080],
  "encoded_size": [800, 450],
  "file_size_bytes": 45678
}
```

---

## 并发请求

服务器基于 asyncio 单进程事件循环，天然支持并发：

- 每个请求在独立的 asyncio Task 中运行，不会相互阻塞
- **输出目录隔离**：若不传 `topic`，服务器自动生成唯一 ID（`uuid4` 短串），确保并发请求写入不同目录，不会互相覆盖
- 若传入相同 `topic` 的两个请求同时运行，会写到同一目录，存在竞争——调用方需自行保证 `topic` 唯一

---

## 配置 MCP 客户端

### Claude Desktop

编辑配置文件：
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "visualsolver": {
      "url": "http://localhost:8000/sse",
      "transport": "sse"
    }
  }
}
```

### Python 客户端

```python
import asyncio
from mcp.client.sse import sse_client
from mcp import ClientSession

async def main():
    async with sse_client("http://localhost:8000/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                "generate_diagram_and_text",
                arguments={
                    "problem": "题目文本",
                    "output_dir": "/absolute/path/to/output",
                    "model": "claude-sonnet-4-6"
                }
            )
            print(result)

asyncio.run(main())
```

---

## 环境变量

```bash
MCP_HOST=0.0.0.0      # 监听地址，默认 0.0.0.0
MCP_PORT=8000          # 监听端口，默认 8000

# 模型 API Keys（根据使用的模型配置）
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...
OPENAI_API_KEY=...
```

---

## 故障排查

**`fastmcp` 未找到：**
```bash
pip install fastmcp
```

**端口占用：**
```bash
lsof -i :8000
MCP_PORT=8001 python mcp_server.py
```

**生成失败，返回 traceback：**
- 检查模型对应的 API Key 是否已设置
- 检查 `output_dir` 是否有写权限
- 查看返回 JSON 中的 `traceback` 字段定位具体错误

**防火墙（Linux）：**
```bash
sudo ufw allow 8000/tcp
```
