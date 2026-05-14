# OAH (Open Agent Harness) 使用说明

## 服务地址

| 服务 | 地址 |
|------|------|
| OAH API | http://localhost:8787 |
| OAH Web 控制台 | http://localhost:5176 |

## 向 Agent 发送图片消息

OAH 消息 API 支持多模态内容，可以在消息中同时发送文本和图片。

### API 端点

```
POST /api/v1/sessions/{sessionId}/messages
```

### 图片消息格式

`image` 字段直接传 base64 编码的图片数据（不带 `data:image/...;base64,` 前缀），`mediaType` 指定图片类型：

```json
{
  "content": [
    { "type": "text", "text": "请查看这道题目图片，描述你看到的内容。" },
    { "type": "image", "image": "<base64编码的图片数据>", "mediaType": "image/png" }
  ]
}
```

**注意**：`image` 字段只传纯 base64 字符串，不要加 `data:image/png;base64,` 前缀。OAH 内部的 `maybeToUrl()` 函数会处理 data URI，但直接传 base64 更可靠。

### 纯文本消息格式（对比）

```json
{
  "content": "请读取 workspace 中的文件并批改。"
}
```

### 完整示例：curl 发送图片消息

```bash
# 1. 创建 workspace
WS_RESP=$(curl -s http://localhost:8787/api/v1/workspaces \
  -X POST -H "Content-Type: application/json" \
  -d '{"name":"test-image","runtime":"question-grader"}')
WS_ID=$(echo "$WS_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "WS_ID=$WS_ID"

# 2. 创建 session
SES_RESP=$(curl -s http://localhost:8787/api/v1/workspaces/$WS_ID/sessions \
  -X POST -H "Content-Type: application/json" \
  -d '{"title":"test-image"}')
SES_ID=$(echo "$SES_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "SES_ID=$SES_ID"

# 3. 编码图片为 base64
B64=$(base64 -i /path/to/image.png | tr -d '\n')

# 4. 发送包含图片的消息
MSG_BODY=$(python3 -c "
import json,sys
b64=sys.argv[1]
print(json.dumps({
  'content': [
    {'type': 'text', 'text': '请查看这道题目图片，描述你看到的内容。'},
    {'type': 'image', 'image': b64, 'mediaType': 'image/png'}
  ]
}))
" "$B64")

MSG_RESP=$(curl -s http://localhost:8787/api/v1/sessions/$SES_ID/messages \
  -X POST -H "Content-Type: application/json" \
  -d "$MSG_BODY")
echo "$MSG_RESP"
RUN_ID=$(echo "$MSG_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['runId'])")

# 5. 监听 SSE 事件
curl -s "http://localhost:8787/api/v1/sessions/$SES_ID/events?runId=$RUN_ID" --max-time 120
```

### 支持的 mediaType

| 格式 | mediaType |
|------|-----------|
| PNG | image/png |
| JPEG | image/jpeg |
| GIF | image/gif |
| WebP | image/webp |

## 常用 API

### 查看可用 runtimes

```bash
curl -s http://localhost:8787/api/v1/runtimes | python3 -m json.tool
```

### 查看 session 消息

```bash
curl -s "http://localhost:8787/api/v1/sessions/{sessionId}/messages" | python3 -m json.tool
```

### 上传文件到 workspace

```bash
curl -s "http://localhost:8787/api/v1/workspaces/{workspaceId}/files/{filePath}" \
  -X PUT \
  -H "Content-Type: application/octet-stream" \
  --data-binary @localfile.txt
```

## 同步 Runtime 配置到 MinIO

修改 `source/runtimes/` 下的 agent 配置后，运行同步脚本：

```bash
python3 /Users/bisz/Documents/test_oah_server2/scripts/sync_to_minio.py --root /Users/bisz/Documents/test_oah_server2
```

## 已知问题

### `maybeToUrl()` data URI bug（已修复）

OAH `packages/model-gateway/src/gateway-helpers.ts` 中的 `maybeToUrl()` 函数会把 `data:image/png;base64,...` 格式的 URI 转成 URL 对象，导致模型 provider 报错 `URL scheme must be http or https, got data:`。

修复方式：在函数开头添加 `if (value.startsWith("data:")) return value;`。此修复已在本地 OAH Docker 镜像中生效，但尚未合并到上游仓库。

### Native Read 工具无法读取二进制文件

OAH 内置的 Read 工具使用 `.toString("utf8")` 读取文件，无法处理二进制 PNG 等图片文件。如果 agent 尝试 Read 二进制文件，会得到乱码或挂起。**解决方案**：不要将图片上传到 workspace 让 agent 读取，而是在消息中直接发送图片（见上方说明）。
