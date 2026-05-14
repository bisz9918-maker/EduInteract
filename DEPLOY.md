# OAH 服务部署指南（OAP Daemon 模式）

本文档描述如何在单节点上以 OAP（Open Agent Harness Personal）Daemon 模式部署 OAH 服务，适用于开发、测试和轻量生产环境。

## 目录结构

```
test_oah_server2/
├── config/                  # 配置文件
│   ├── daemon.yaml          # OAP daemon 模式配置（本指南使用）
│   ├── server.docker.yaml   # Docker Compose 模式配置
│   └── kubernetes.server.yaml
├── source/                  # 数据源（source of truth）
│   ├── models/              # 模型配置 YAML
│   ├── runtimes/            # Runtime（Agent）定义
│   ├── skills/              # 技能包
│   ├── tools/               # 工具服务器定义
│   └── workspaces/          # Workspace 模板
├── scripts/                 # 运维脚本
│   ├── sync_to_minio.py     # 同步 source/ 到 MinIO
│   └── cleanup_workspaces.sh
├── serve-web.mjs            # Web UI 静态文件服务 + API 反向代理
├── docker-compose.local.yml # Docker Compose 全栈部署
└── server.docker.yaml       # Docker 模式入口配置
```

运行时生成的目录（已在 `.gitignore` 中排除）：

```
test_oah_server2/
├── run/                     # daemon PID 和 token
├── logs/                    # 运行日志
├── state/                   # workspace 状态数据库
├── workspaces/              # workspace 文件（运行时填充）
├── runtimes/                # 运行时 runtime 副本
├── models/                  # 运行时 model 副本
├── skills/                  # 运行时 skill 副本
└── tools/                   # 运行时 tool 副本
```

---

## 1. 环境要求

| 依赖 | 版本要求 |
|------|----------|
| Node.js | >= 24 |
| pnpm | 10.30.2 |
| Python 3 | 用于同步脚本（Docker 模式需要） |

安装 Node.js 和 pnpm：

```bash
# 安装 nvm（如果尚未安装）
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
source ~/.bashrc

# 安装 Node.js 24
nvm install 24
nvm use 24

# 安装 pnpm
corepack enable
corepack prepare pnpm@10.30.2 --activate
```

---

## 2. 构建 OAH

```bash
# 进入 OAH 源码目录
cd /path/to/oah

# 安装依赖
pnpm install

# 构建（编译 TypeScript + 打包 Web UI）
pnpm build
```

构建产物：
- Server: `apps/server/dist/`
- Web UI: `apps/web/dist/`

---

## 3. 安装 Chromium + 中文字体

OAH Agent 在使用浏览器截图、网页渲染等能力时需要 Chromium 和中文字体支持。

```bash
# 安装 Chromium
apt-get update
apt-get install -y chromium-browser || apt-get install -y google-chrome-stable

# 安装中文字体
apt-get install -y fonts-wqy-zenhei fonts-wqy-microhei fonts-noto-cjk

# 验证
chromium-browser --version || google-chrome-stable --version
fc-list :lang=zh | head -5
```

---

## 4. 安装 Playwright

Playwright 不随 OAH 一起安装，需要单独部署。

```bash
# 创建独立目录（避免与 OAH 的 node_modules 冲突）
mkdir -p /app/playwright_modules
cd /app/playwright_modules

# 初始化并安装 playwright-core
npm init -y
npm install playwright-core
```

安装后的关键路径：

| 项目 | 路径 |
|------|------|
| Playwright 模块 | `/app/playwright_modules/node_modules/playwright-core` |
| Chromium 可执行文件 | `/usr/bin/google-chrome-stable` |

在 Agent 代码中使用 Playwright 时，需要指定正确的路径和启动参数：

```javascript
import { chromium } from "/app/playwright_modules/node_modules/playwright-core";

const browser = await chromium.launch({
  executablePath: "/usr/bin/google-chrome-stable",
  args: ["--no-sandbox", "--disable-gpu"],
});

const page = await browser.newPage();
await page.goto("https://example.com");
// ...
await browser.close();
```

> **注意**：`--no-sandbox` 在容器环境中必须添加；`--disable-gpu` 避免无 GPU 环境下的渲染错误。

---

## 5. 配置 OAH 服务

配置文件位于 `config/daemon.yaml`：

```yaml
server:
  host: 127.0.0.1
  port: 8787

deployment:
  kind: oap
  runtime_mode: daemon
  display_name: OAP local daemon

storage:
  sqlite:
    project_db_location: shadow

sandbox:
  provider: embedded

paths:
  workspace_dir: ../workspaces
  runtime_state_dir: ../state
  runtime_dir: ../source/runtimes
  model_dir: ../source/models
  tool_dir: ../source/tools
  skill_dir: ../source/skills

workers:
  embedded:
    min_count: 1
    max_count: 2
    scale_interval_ms: 1000
    idle_ttl_ms: 30000
    scale_up_window: 1
    scale_down_window: 2
    cooldown_ms: 1000
    reserved_capacity_for_subagent: 1

llm:
  default_model: kimi-k26
```

### 关键配置说明

| 字段 | 说明 |
|------|------|
| `deployment.kind: oap` | OAP 个人版模式，使用 SQLite + 本地文件系统 |
| `deployment.runtime_mode: daemon` | Daemon 模式，API + Worker 同进程运行 |
| `sandbox.provider: embedded` | 嵌入式沙箱，Agent 直接在当前进程执行 |
| `paths.*` | 相对于 `config/daemon.yaml` 所在目录解析 |
| `llm.default_model` | 默认模型名称，须在 `source/models/` 中有对应 YAML |

### 模型配置

在 `source/models/` 下添加模型 YAML 文件，例如 `source/models/kimi-k26.yaml`：

```yaml
kimi-k26:
  provider: openai-compatible
  key: <YOUR_API_KEY>
  url: <YOUR_API_BASE_URL>/v1
  name: <MODEL_PATH_OR_NAME>
```

### Runtime（Agent）配置

在 `source/runtimes/` 下添加 Agent 定义，每个 Agent 是一个目录，包含 `.openharness/` 子目录：

```
source/runtimes/question-grader/
└── .openharness/
    ├── settings.yaml    # Agent 设置（默认 agent、system prompt 等）
    └── agents/
        └── grader.md    # Agent prompt
```

---

## 6. 启动 OAH Server

```bash
# 进入 OAH 源码目录
cd /path/to/oah

# 以 daemon 模式启动（后台运行）
pnpm exec tsx --tsconfig ./apps/server/tsconfig.json \
  ./apps/server/src/index.ts \
  -- --config /path/to/test_oah_server2/config/daemon.yaml \
  &>/tmp/oah-server.log &

echo "PID: $!"
```

### 验证服务

```bash
# 健康检查
curl -s http://127.0.0.1:8787/healthz | python3 -m json.tool

# 查看可用 runtimes
curl -s http://127.0.0.1:8787/api/v1/runtimes | python3 -m json.tool

# 查看 workspaces
curl -s http://127.0.0.1:8787/api/v1/workspaces | python3 -m json.tool
```

---

## 7. 启动 Web UI

Web UI 通过 `serve-web.mjs` 提供服务，它同时承担静态文件服务和 API 反向代理，支持直接访问和反向代理（如 Notebook 环境）两种模式。

```bash
cd /path/to/test_oah_server2

# 读取 daemon token（如果有）
TOKEN=$(cat run/token 2>/dev/null || echo "")

# 启动 Web UI
OAH_LOCAL_API_TOKEN="$TOKEN" node serve-web.mjs &>/tmp/oah-webui.log &
echo "PID: $!"
```

### 服务地址

| 访问方式 | 地址 |
|----------|------|
| 直接访问 | `http://<host>:5173` |
| Notebook 反向代理 | `https://<notebook-host>/ws-xxx/proxy/5173/` |

### 反向代理支持

`serve-web.mjs` 自动检测 URL 中的 `/ws-xxx/proxy/<port>/` 前缀模式，将带前缀的 API 请求正确代理到后端，并在前端注入正确的 `baseUrl`，确保 Notebook 等反向代理环境下正常工作。

代理规则：
- `/api/`、`/internal/`、`/healthz`、`/readyz`、`/metrics` 路径代理到 `http://127.0.0.1:8787`
- 其他路径返回 Web UI 静态文件（SPA 模式）

---

## 8. 常用 API

```bash
# 查看可用 runtimes
curl -s http://127.0.0.1:8787/api/v1/runtimes | python3 -m json.tool

# 创建 workspace
curl -s http://127.0.0.1:8787/api/v1/workspaces \
  -X POST -H "Content-Type: application/json" \
  -d '{"name":"my-workspace","runtime":"question-grader"}'

# 创建 session
curl -s http://127.0.0.1:8787/api/v1/workspaces/<ws-id>/sessions \
  -X POST -H "Content-Type: application/json" \
  -d '{"title":"my-session"}'

# 发送文本消息
curl -s http://127.0.0.1:8787/api/v1/sessions/<session-id>/messages \
  -X POST -H "Content-Type: application/json" \
  -d '{"content":"你好，请帮我批改这道题。"}'

# 发送图片消息（base64）
curl -s http://127.0.0.1:8787/api/v1/sessions/<session-id>/messages \
  -X POST -H "Content-Type: application/json" \
  -d '{
    "content": [
      {"type": "text", "text": "请查看这道题目图片。"},
      {"type": "image", "image": "<base64编码数据>", "mediaType": "image/png"}
    ]
  }'

# 监听 SSE 事件
curl -s "http://127.0.0.1:8787/api/v1/sessions/<session-id>/events?runId=<run-id>" --max-time 120

# 上传文件到 workspace
curl -s "http://127.0.0.1:8787/api/v1/workspaces/<ws-id>/files/<file-path>" \
  -X PUT -H "Content-Type: application/octet-stream" \
  --data-binary @localfile.txt
```

---

## 9. 运维操作

### 停止服务

```bash
# 停止 Web UI
pkill -f "serve-web.mjs"

# 停止 OAH Server
pkill -f "tsx.*index.ts.*daemon.yaml"
```

### 清理 Workspace

```bash
# 通过 API 逐个删除
curl -s http://127.0.0.1:8787/api/v1/workspaces | \
  python3 -c "import sys,json; [print(w['id']) for w in json.load(sys.stdin)['items']]" | \
  xargs -I{} curl -s -X DELETE "http://127.0.0.1:8787/api/v1/workspaces/{}"
```

### 查看日志

```bash
# OAH Server 日志
tail -f /tmp/oah-server.log

# Web UI 日志
tail -f /tmp/oah-webui.log
```

---

## 10. 已知问题

### Native Read 工具无法读取二进制文件

OAH 内置的 Read 工具使用 `.toString("utf8")` 读取文件，无法处理 PNG 等二进制文件。**解决方案**：不要将图片上传到 workspace 让 Agent 读取，而是在消息中直接发送图片（见上方 API 示例）。

### `maybeToUrl()` data URI bug

OAH `packages/model-gateway/src/gateway-helpers.ts` 中的 `maybeToUrl()` 函数会把 `data:image/png;base64,...` 格式的 URI 转成 URL 对象，导致模型 provider 报错。修复方式：在函数开头添加 `if (value.startsWith("data:")) return value;`。
