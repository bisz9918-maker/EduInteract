# EduInteract

[English](README.md) | 简体中文

从考试题目生成交互式教育图示（HTML）并用 LLM judge 评估的流程。生成由 OAH（Open Agent Harness）驱动，经过三个 agent（outline → planner → solver），评估对每道题打五个维度的分数。

> benchmark 已在 `benchmark.json` 中包含题目文本和图片。

---

## 整体流程

```
benchmark.json ──▶ 场景大纲 ──▶ 实现计划 ──▶ HTML 代码 ──▶ 交互式图示
                   (OAH Agent)  (OAH Agent)  (OAH Agent)
                                                      │
                                                      ▼
                                          evaluate.py ──▶ 5 维分数 + 总分（几何平均）
                                                          (OAH Agent)
```

---

## 1. 环境要求

| 依赖 | 版本 |
|------|------|
| Python | 3.12+ |
| Node.js | 24+ |
| pnpm | 10.30.2 |
| Git | 2.x |

## 2. 拉取仓库

本项目包含 3 个仓库，放在同一父目录下：

```bash
WORKSPACE=/inspire/qb-ilm/project/ai4education/bishuzhen-CZXS24220022/edu_interact

# 主仓库（生成 + 评估脚本、VisualSolver）
cd $WORKSPACE
git clone -b EduInteract https://github.com/bisz9918-maker/EduInteract.git EduInteract

# OAH 源码
git clone -b oah https://github.com/bisz9918-maker/EduInteract.git oah

# OAH 部署配置（runtime、模型配置、多实例管理）
git clone -b test_oah_server https://github.com/bisz9918-maker/EduInteract.git test_oah_server2
```

拉取后的目录结构：

```
edu_interact/
├── EduInteract/          # 主项目（Python 虚拟环境 + 生成/评估脚本）
├── oah/                  # OAH 源码（TypeScript，需 pnpm build）
└── test_oah_server2/     # OAH 部署配置（daemon.yaml、模型配置、Agent 定义）
```

## 3. 配置 Python 环境

```bash
cd $WORKSPACE/EduInteract

# 创建虚拟环境
python3.12 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install litellm openai pillow python-dotenv aiohttp
```

## 4. 配置 .env 文件

在 `EduInteract/` 根目录下创建 `.env`，只需 OAH 和 LiteLLM 配置（无需 OCR）：

```bash
cd $WORKSPACE/EduInteract
cat > .env << 'EOF'
# OAH (Open Agent Harness) — VisualSolver 在 use_oah=True 时使用
OAH_API_URL=http://localhost:8787
OAH_LOCAL_API_TOKEN=YOUR_TOKEN_HERE

# LiteLLM
LITELLM_SKIP_MODEL_VALIDATION=True
EOF
```

> `OAH_LOCAL_API_TOKEN` 在 OAH 启动后从 `test_oah_server2/run/token` 读取（见第 8 节）。

## 5. 构建 OAH

```bash
cd $WORKSPACE/oah

# 安装 Node.js 依赖
pnpm install

# 构建（编译 TypeScript + 打包 Web UI）
pnpm build
```

构建产物：
- Server: `apps/server/dist/`
- Web UI: `apps/web/dist/`

## 6. 配置模型 API

OAH 通过 OpenAI 兼容接口调用模型。编辑模型配置文件：

```bash
vi $WORKSPACE/test_oah_server2/source/models/kimi-k26.yaml
```

内容格式：

```yaml
kimi-k26:
  provider: openai-compatible
  key: YOUR_API_KEY
  url: YOUR_API_BASE_URL/v1
  name: Kimi-K2.6
```

> 如果使用本地部署的模型（如 vLLM），`url` 填本地地址（如 `http://127.0.0.1:8008/v1`），`key` 可填任意值。

## 7. 安装 Chromium + Playwright

OAH Agent 在生成代码后会用 Playwright 做布局检测和截图验证：

```bash
# 安装 Chromium
apt-get update
apt-get install -y google-chrome-stable

# 安装中文字体
apt-get install -y fonts-wqy-zenhei fonts-wqy-microhei fonts-noto-cjk

# 安装 Playwright（独立目录，避免与 OAH 冲突）
mkdir -p /app/playwright_modules
cd /app/playwright_modules
npm init -y
npm install playwright-core
```

## 8. 启动 OAH 服务

### 单实例启动

```bash
cd $WORKSPACE/test_oah_server2

# 启动 instance_1（端口 8787）
NODE_OPTIONS="--max-old-space-size=131072" nohup pnpm --dir "$WORKSPACE/oah" exec tsx \
  --tsconfig "$WORKSPACE/oah/apps/server/tsconfig.json" \
  "$WORKSPACE/oah/apps/server/src/index.ts" \
  -- --config $WORKSPACE/test_oah_server2/oah_instance_1/daemon.yaml \
  > logs/instance_1.log 2>&1 &

# 等待启动
sleep 5

# 验证
curl -s http://127.0.0.1:8787/healthz | python3 -m json.tool
```

### 多实例启动（批量任务推荐）

每个实例独立端口（8787, 8788, ...），可并行处理不同题目：

```bash
cd $WORKSPACE/test_oah_server2

# 启动实例 1-6
bash scripts/start_instances.sh start 1-6

# 验证所有实例
for port in 8787 8788 8789 8790 8791 8792; do
  status=$(curl -s http://127.0.0.1:$port/healthz 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "FAILED")
  echo "Instance $port: $status"
done
```

### 获取 Token

```bash
cat $WORKSPACE/test_oah_server2/run/token
```

将输出值填入 EduInteract 的 `.env` 中 `OAH_LOCAL_API_TOKEN`。

### 启动 Web UI（可选）

```bash
cd $WORKSPACE/test_oah_server2
TOKEN=$(cat run/token)
OAH_LOCAL_API_TOKEN="$TOKEN" nohup node serve-web.mjs > /tmp/oah-webui.log 2>&1 &
```

浏览器访问 `http://<服务器IP>:5173` 查看 Agent 运行状态。

## 9. Benchmark 数据

benchmark 是一个 JSON 题目列表，每道题包含 `question`、`img`（base64）、`format_answer`、`difficulty`、`subject` 等字段：

```
EduInteract/VisualSolver/data/benchmark/benchmark.json   # 230 道题
```

无需图片 OCR——题目文本已内嵌在 `benchmark.json` 中。

## 10. 生成图示

```bash
cd $WORKSPACE/EduInteract
source .venv/bin/activate

nohup python -m visual_solver.generate_explanation \
    --use_oah \
    --oah_model kimi-k26 \
    --oah_url http://127.0.0.1:8787 \
    --problem_path VisualSolver/data/benchmark/benchmark.json \
    --output_dir output/exp_kimik26 \
    > logs/exp_kimik26.log 2>&1 &
```

### 关键参数说明

| 参数 | 说明 |
|------|------|
| `--use_oah` | 通过 OAH Agent 驱动生成 |
| `--oah_model` | OAH 中配置的模型名称（对应 `source/models/` 下的 YAML 文件名） |
| `--oah_url` | OAH 服务地址 |
| `--problem_path` | benchmark JSON 路径 |
| `--output_dir` | 输出目录，生成的 HTML 和 trace 文件保存在此 |
| `--index` | 按 0 基索引处理单道题 |
| `--start_index` | 只处理 `index` 字段 ≥ 此值的题目 |
| `--max_topic_concurrency` | 并发处理的题目数（默认 3） |
| `--max_scene_concurrency` | 每道题并发处理的 scene 数（默认 1） |
| `--translate_to_chinese` | 翻译输出为中文 |
| `--mark_failed` | 标记模型导致的失败，后续不再重试 |
| `--oah_timeout` | 单个 Agent 运行超时秒数（默认 7200） |

### 多实例并行

启动多个 OAH 实例后，可启动多个进程分别指向不同端口：

```bash
# 终端 1：前半部分题目，使用 instance_1
python -m visual_solver.generate_explanation --use_oah \
    --oah_model kimi-k26 --oah_url http://127.0.0.1:8787 \
    --problem_path VisualSolver/data/benchmark/benchmark.json \
    --output_dir output/exp_kimik26 --start_index 0

# 终端 2：后半部分题目，使用 instance_2
python -m visual_solver.generate_explanation --use_oah \
    --oah_model kimi-k26 --oah_url http://127.0.0.1:8788 \
    --problem_path VisualSolver/data/benchmark/benchmark.json \
    --output_dir output/exp_kimik26 --start_index 115
```

## 11. 评估图示

对生成的图示打五个维度的分数。总分为五个维度分数的**几何平均**（任一维度为 0 则总分直接为 0；渲染失败也置总分 0）。

```bash
cd $WORKSPACE/EduInteract
source .venv/bin/activate

nohup python evaluate.py \
    --input_dir output/exp_kimik26 \
    --output_dir output/evaluate_kimi26 \
    --oah_url http://127.0.0.1:8790 \
    --workers 4 \
    > logs/evaluate_kimi.log 2>&1 &
```

### 关键参数说明

| 参数 | 说明 |
|------|------|
| `--input_dir` | 待评估的生成输出目录 |
| `--output_dir` | 评估输出目录 |
| `--oah_url` | judge Agent 使用的 OAH 服务地址 |
| `--workers` | 并行评估 worker 数（默认 1） |
| `--problem` | 按名称评估单道题 |
| `--force` | 即使已有报告也重新评估 |
| `--trace_dir` | 评估 trace 目录 |

### 五个维度

| 维度 | Key | 说明 |
|------|-----|------|
| 1 | `dim1_accuracy` | 题图匹配——图示是否与题意对齐 |
| 2 | `dim2_interaction` | 交互功能——交互是否正常有效 |
| 3 | `dim3_visual` | 视觉质量——元素质量、布局、风格一致性 |
| 4 | `dim4_pedagogy` | 教学效果——认知引导、步骤节奏 |
| 5 | `dim5_logic_coherence` | 逻辑连贯——scene 递进、状态一致性 |

## 12. 查看结果

```bash
# 生成输出目录结构
ls output/exp_kimik26/
# problem_0_physics_g9/        ← 每道题一个目录
#   ├── scene1/
#   │   └── scene1.html        ← 生成的交互式图示
#   ├── doc/
#   │   └── solution.html
#   └── traces/                ← Agent 运行轨迹（用于 SFT 数据提取）

# 评估输出目录结构
ls output/evaluate_kimi26/
# problem_0_physics_g9/
#   ├── evaluation_report.xml  ← 5 维分数 + 评分理由
#   └── dim{1-5}_result.txt    ← 各维度分数
# evaluation_summary.json      ← 汇总报告，含 total_score
```

```bash
# 查看生成进度
grep -c "completed" logs/exp_kimik26.log
grep -c "FAILED\|ERROR" logs/exp_kimik26.log

# 查看评估分数汇总
python3 -c "import json; d=json.load(open('output/evaluate_kimi26/evaluation_summary.json')); print('avg_score:', d.get('avg_score'))"
```

## 13. 常用运维

```bash
# 停止 OAH 实例
cd $WORKSPACE/test_oah_server2
bash scripts/start_instances.sh stop

# 清理 Workspace（释放 SQLite 空间）
curl -s http://127.0.0.1:8787/api/v1/workspaces | \
  python3 -c "import sys,json; [print(w['id']) for w in json.load(sys.stdin).get('items',[])]" | \
  xargs -I{} curl -s -X DELETE "http://127.0.0.1:8787/api/v1/workspaces/{}"

# 查看 OAH 日志
tail -f $WORKSPACE/test_oah_server2/logs/instance_1.log

# 检查实例状态
for port in 8787 8788 8789; do
  echo "Port $port: $(curl -s http://127.0.0.1:$port/healthz 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("status","?"))' 2>/dev/null || echo 'STOPPED')"
done
```
