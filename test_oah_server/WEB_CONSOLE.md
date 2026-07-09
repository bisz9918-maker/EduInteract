# OAH Web 控制台启动指南

## 前提条件

1. OAH 后端服务已启动（至少一个实例），例如端口 8790
2. 前端已构建（`oah/apps/web/dist` 目录存在）

## 1. 构建前端

```bash
cd /inspire/qb-ilm/project/ai4education/bishuzhen-CZXS24220022/edu_interact/oah
pnpm --dir apps/web build
```

## 2. 启动 Web 服务

使用 `serve-web.mjs`，通过环境变量指定后端 API 地址：

```bash
# 代理到 8790 端口的 OAH 实例
OAH_WEB_PROXY_TARGET=http://127.0.0.1:8790 \
nohup node /inspire/qb-ilm/project/ai4education/bishuzhen-CZXS24220022/edu_interact/oah/scripts/serve-web.mjs \
  > logs/web_frontend.log 2>&1 &
```

可选环境变量：
- `OAH_WEB_PROXY_TARGET`：后端 API 地址，默认 `http://127.0.0.1:8787`
- `OAH_WEB_PORT`：前端监听端口，默认 `5173`

## 3. 访问 Web 控制台

### 方式一：通过 VS Code 端口转发（推荐）

1. 在 VS Code 的 **Ports** 面板中，确认 5173 端口已被自动转发
2. 在 Ports 面板中点击 5173 对应的链接即可打开

### 方式二：直接 URL

通过 VS Code 代理路径访问：

```
https://<host>/ws-<id>/project-<id>/user-<id>/vscode/<id>/<id>/proxy/5173/
```

`serve-web.mjs` 会自动检测 `/proxy/<port>/` 前缀，并：
- 将带前缀的 API 请求（如 `/ws-xxx/proxy/5173/api/v1/...`）strip 前缀后代理到后端
- 在 HTML 中注入正确的 `baseUrl`，使前端 API 请求走代理路径

### 方式三：本地直接访问

如果在本机有浏览器：

```
http://localhost:5173/
```

## 4. 验证服务

```bash
# 检查服务是否运行
curl http://127.0.0.1:5173/healthz

# 检查日志
tail -f logs/web_frontend.log
```

## 5. 停止服务

```bash
lsof -ti :5173 | xargs kill
```

## 常见问题

### 打开页面显示 404 Not Found (nginx)

- 确认 5173 端口的服务正在运行：`lsof -i :5173`
- 确认 OAH 后端正在运行：`curl http://127.0.0.1:8790/healthz`
- 如果通过 VS Code 代理访问，尝试清空浏览器 localStorage 后刷新（F12 → Application → Local Storage → 删除 `oah.web.connection`）
- 使用 Ctrl+Shift+R 强制刷新，避免缓存

### 页面加载但无法连接后端

- 检查 `OAH_WEB_PROXY_TARGET` 是否指向正确的后端端口
- 检查前端左下角显示的连接状态，如显示 "not configured"，手动在 Settings 中填写 baseUrl
