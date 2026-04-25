# ---- Stage 1: 前端构建 ----
FROM node:22-alpine AS frontend-build

WORKDIR /app/teacher_app
COPY teacher_app/package.json teacher_app/package-lock.json ./
RUN npm ci
COPY teacher_app/ ./
RUN npm run build

# ---- Stage 2: Python 依赖构建 ----
FROM python:3.11-slim AS python-deps

WORKDIR /app/VisualSolver
COPY VisualSolver/ ./
RUN pip install --no-cache-dir .

# ---- Stage 3: 运行时 (Debian bookworm + Python from apt) ----
FROM node:22-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

# 从 python-deps 复制已安装的 pip 包到 dist-packages 让 apt python3 能找到
COPY --from=python-deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/dist-packages
COPY --from=python-deps /usr/local/bin /usr/local/pip-bin/
# 复制 pip 安装的可执行文件，但排除 python3 自身（避免覆盖 apt 的 python3）
RUN for f in /usr/local/pip-bin/*; do \
      base=$(basename "$f"); \
      case "$base" in python3|python3.11|2to3-3.11|idle3.11|pydoc3.11) continue;; esac; \
      if [ -f "$f" ] && head -1 "$f" | grep -q '/usr/local/bin/python3'; then \
        sed -i '1s|/usr/local/bin/python3|/usr/bin/python3|' "$f"; \
      fi; \
      cp "$f" /usr/local/bin/; \
    done && \
    rm -rf /usr/local/pip-bin

WORKDIR /app

# 复制 VisualSolver
COPY VisualSolver/ /app/VisualSolver/

# 复制 teacher_app 构建产物
COPY --from=frontend-build /app/teacher_app/dist /app/teacher_app/dist
COPY --from=frontend-build /app/teacher_app/src /app/teacher_app/src
COPY --from=frontend-build /app/teacher_app/node_modules /app/teacher_app/node_modules
COPY --from=frontend-build /app/teacher_app/package.json /app/teacher_app/
COPY --from=frontend-build /app/teacher_app/tsconfig.node.json /app/teacher_app/

# 创建输出和数据目录
RUN mkdir -p /app/output/teacher /app/data

ENV NODE_ENV=production
ENV PYTHON=/usr/bin/python3
EXPOSE 8765

WORKDIR /app/teacher_app
CMD ["npx", "tsx", "src/server/index.ts"]
