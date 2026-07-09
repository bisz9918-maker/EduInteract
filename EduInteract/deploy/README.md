# EduIllustrate-teacher 生产部署

## 架构

单 Docker 容器，包含 Node.js 22 + Python 3.11：

- Express 服务端 + Vue 前端静态文件（Node.js）
- VisualSolver Python worker（由 Express spawn 子进程）
- `.env` 外挂（密钥不入镜像）

## 前置条件

- 目标服务器已安装 Docker + Docker Compose
- 网络：服务器可访问 OAH API、LLM API 等外部服务
- 本地可 scp 到远程

## 部署步骤

### 1. 传输代码到远程

```bash
# 从本机执行（排除不需要的文件）
rsync -avz --delete \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.egg-info' \
  --exclude='output' \
  --exclude='.env' \
  --exclude='baseline_videos' \
  --exclude='models' \
  --exclude='*.onnx' \
  --exclude='*.bin' \
  --exclude='data' \
  --exclude='annotation_app' \
  --exclude='eval_suite' \
  --exclude='test*' \
  --exclude='logs' \
  --exclude='*.log' \
  /Users/bisz/Documents/EduIllustrate-teacher/ \
  wms@10.11.20.89:/home/wms/EduIllustrate-teacher/
```

### 2. 在远程配置 .env

```bash
ssh wms@10.11.20.89

cd /home/wms/EduIllustrate-teacher
cp .env.template .env
vim .env   # 填入实际配置
```

必须配置的变量：

```env
# 端口
SERVER_PORT=8765

# LLM API（至少配一个）
CUSTOM_API_BASE=...
CUSTOM_API_KEY=...
TEACHER_MODEL=...

# OAH（如果使用 OAH 生成图示）
OAH_API_URL=http://<oah-host>:8787

# OCR（如果需要图片识别）
OCR_URL=...
OCR_KEY=...
```

### 3. 构建镜像并启动

```bash
cd /home/wms/EduIllustrate-teacher
docker compose -f deploy/docker-compose.prod.yml build
docker compose -f deploy/docker-compose.prod.yml up -d
```

### 4. 验证

```bash
# 检查容器状态
docker compose -f deploy/docker-compose.prod.yml ps

# 查看日志
docker compose -f deploy/docker-compose.prod.yml logs -f

# 测试访问
curl http://localhost:8765
```

浏览器访问 `http://10.11.20.89:8765`

## 常用操作

### 查看日志
```bash
docker compose -f deploy/docker-compose.prod.yml logs -f teacher-app
```

### 重启
```bash
docker compose -f deploy/docker-compose.prod.yml restart
```

### 更新代码后重新部署
```bash
# 本地重新 rsync（同步骤1）
# 远程重新构建
docker compose -f deploy/docker-compose.prod.yml build --no-cache
docker compose -f deploy/docker-compose.prod.yml up -d
```

### 修改 .env 后重启
```bash
docker compose -f deploy/docker-compose.prod.yml restart
```

### 清理输出数据
```bash
docker volume rm eduillustrate-teacher_app-output
```

## 数据持久化

| Volume | 容器路径 | 说明 |
|--------|---------|------|
| `app-data` | `/app/data` | 用户数据、题库数据库 |
| `app-output` | `/app/output` | 生成的图示文件 |

`.env` 通过 bind mount 挂载为只读，修改后重启生效。

## 故障排查

### Python worker 启动失败
```bash
# 进入容器检查 Python 环境
docker compose -f deploy/docker-compose.prod.yml exec teacher-app bash
python3 -c "from visual_solver import ExplanationGenerator; print('OK')"
python3 -c "from oah_client import OAHClient; print('OK')"
```

### 前端白屏
```bash
# 检查 dist/client/ 是否存在
docker compose -f deploy/docker-compose.prod.yml exec teacher-app ls /app/teacher_app/dist/client/
```

### OAH 连接失败
```bash
# 从容器内测试 OAH 连通性
docker compose -f deploy/docker-compose.prod.yml exec teacher-app curl -s http://<oah-host>:8787/api/v1/workspaces
```
