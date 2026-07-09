# EduInteract

English | [简体中文](README_CN.md)

A pipeline for generating interactive educational diagrams (HTML) from exam problems and evaluating them with LLM judges. Driven by OAH (Open Agent Harness), the generation runs through three agents (outline → planner → solver) and the evaluation scores each problem across five dimensions.

> The benchmark already contains the problem text and image in `benchmark.json`.

---

## Pipeline

```
benchmark.json ──▶ Scene Outline ──▶ Implementation Plan ──▶ HTML Code ──▶ Interactive Diagram
                   (OAH Agent)        (OAH Agent)            (OAH Agent)
                                                                          │
                                                                          ▼
                                                          evaluate.py ──▶ 5-dim scores + total (geometric mean)
                                                                          (OAH Agent)
```

---

## 1. Requirements

| Dependency | Version |
|------------|---------|
| Python | 3.12+ |
| Node.js | 24+ |
| pnpm | 10.30.2 |
| Git | 2.x |

## 2. Clone the repositories

Three repos live under the same parent directory:

```bash
WORKSPACE=/inspire/qb-ilm/project/ai4education/bishuzhen-CZXS24220022/edu_interact

# Main repo (generation + evaluation scripts, VisualSolver)
cd $WORKSPACE
git clone -b EduInteract https://github.com/bisz9918-maker/EduInteract.git EduInteract

# OAH source
git clone -b oah https://github.com/bisz9918-maker/EduInteract.git oah

# OAH deployment config (runtime, model configs, multi-instance management)
git clone -b test_oah_server https://github.com/bisz9918-maker/EduInteract.git test_oah_server2
```

Resulting layout:

```
edu_interact/
├── EduInteract/          # Main project (Python venv + generation/eval scripts)
├── oah/                  # OAH source (TypeScript, needs pnpm build)
└── test_oah_server2/     # OAH deployment config (daemon.yaml, model configs, agent defs)
```

## 3. Configure the Python environment

```bash
cd $WORKSPACE/EduInteract

# Create venv
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install litellm openai pillow python-dotenv aiohttp
```

## 4. Configure `.env`

Create `.env` in the `EduInteract/` root. Only OAH and LiteLLM are needed (no OCR):

```bash
cd $WORKSPACE/EduInteract
cat > .env << 'EOF'
# OAH (Open Agent Harness) — used by VisualSolver when use_oah=True
OAH_API_URL=http://localhost:8787
OAH_LOCAL_API_TOKEN=YOUR_TOKEN_HERE

# LiteLLM
LITELLM_SKIP_MODEL_VALIDATION=True
EOF
```

> `OAH_LOCAL_API_TOKEN` is read from `test_oah_server2/run/token` after OAH starts (see §8).

## 5. Build OAH

```bash
cd $WORKSPACE/oah

# Install Node.js dependencies
pnpm install

# Build (compile TypeScript + bundle Web UI)
pnpm build
```

Build artifacts:
- Server: `apps/server/dist/`
- Web UI: `apps/web/dist/`

## 6. Configure the model API

OAH calls models via an OpenAI-compatible interface. Edit the model config:

```bash
vi $WORKSPACE/test_oah_server2/source/models/kimi-k26.yaml
```

Format:

```yaml
kimi-k26:
  provider: openai-compatible
  key: YOUR_API_KEY
  url: YOUR_API_BASE_URL/v1
  name: Kimi-K2.6
```

> For a locally deployed model (e.g. vLLM), set `url` to the local address (e.g. `http://127.0.0.1:8008/v1`); `key` can be any value.

## 7. Install Chromium + Playwright

OAH agents use Playwright for layout detection and screenshot verification after generating code:

```bash
# Install Chromium
apt-get update
apt-get install -y google-chrome-stable

# Install Chinese fonts
apt-get install -y fonts-wqy-zenhei fonts-wqy-microhei fonts-noto-cjk

# Install Playwright (separate directory to avoid conflicts with OAH)
mkdir -p /app/playwright_modules
cd /app/playwright_modules
npm init -y
npm install playwright-core
```

## 8. Start the OAH service

### Single instance

```bash
cd $WORKSPACE/test_oah_server2

# Start instance_1 (port 8787)
NODE_OPTIONS="--max-old-space-size=131072" nohup pnpm --dir "$WORKSPACE/oah" exec tsx \
  --tsconfig "$WORKSPACE/oah/apps/server/tsconfig.json" \
  "$WORKSPACE/oah/apps/server/src/index.ts" \
  -- --config $WORKSPACE/test_oah_server2/oah_instance_1/daemon.yaml \
  > logs/instance_1.log 2>&1 &

# Wait for startup
sleep 5

# Verify
curl -s http://127.0.0.1:8787/healthz | python3 -m json.tool
```

### Multiple instances (recommended for batch jobs)

Each instance gets its own port (8787, 8788, ...) and can process different problems in parallel:

```bash
cd $WORKSPACE/test_oah_server2

# Start instances 1-6
bash scripts/start_instances.sh start 1-6

# Verify all instances
for port in 8787 8788 8789 8790 8791 8792; do
  status=$(curl -s http://127.0.0.1:$port/healthz 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "FAILED")
  echo "Instance $port: $status"
done
```

### Get the token

```bash
cat $WORKSPACE/test_oah_server2/run/token
```

Fill the output into `OAH_LOCAL_API_TOKEN` in `EduInteract/.env`.

### Start the Web UI (optional)

```bash
cd $WORKSPACE/test_oah_server2
TOKEN=$(cat run/token)
OAH_LOCAL_API_TOKEN="$TOKEN" nohup node serve-web.mjs > /tmp/oah-webui.log 2>&1 &
```

Open `http://<server-ip>:5173` in a browser to view agent run status.

## 9. Benchmark data

The benchmark is a JSON list of problems, each containing `question`, `img` (base64), `format_answer`, `difficulty`, `subject`, etc.:

```
EduInteract/VisualSolver/data/benchmark/benchmark.json   # 230 problems
```

No image OCR is needed — the problem text is already embedded in `benchmark.json`.

## 10. Generate diagrams

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

### Key parameters

| Parameter | Description |
|-----------|-------------|
| `--use_oah` | Drive generation through OAH agents |
| `--oah_model` | Model name configured in OAH (the YAML filename under `source/models/`) |
| `--oah_url` | OAH service address |
| `--problem_path` | Path to the benchmark JSON |
| `--output_dir` | Output directory for generated HTML and traces |
| `--index` | Process a single problem by 0-based index |
| `--start_index` | Process only problems whose `index` field ≥ this value |
| `--max_topic_concurrency` | Number of problems to process concurrently (default 3) |
| `--max_scene_concurrency` | Number of scenes to process concurrently per problem (default 1) |
| `--translate_to_chinese` | Translate the output to Chinese |
| `--mark_failed` | Mark model-caused failures so they are not retried |
| `--oah_timeout` | Per-agent run timeout in seconds (default 7200) |

### Multi-instance parallelism

With multiple OAH instances, run several processes pointing at different ports:

```bash
# Terminal 1: first half, instance_1
python -m visual_solver.generate_explanation --use_oah \
    --oah_model kimi-k26 --oah_url http://127.0.0.1:8787 \
    --problem_path VisualSolver/data/benchmark/benchmark.json \
    --output_dir output/exp_kimik26 --start_index 0

# Terminal 2: second half, instance_2
python -m visual_solver.generate_explanation --use_oah \
    --oah_model kimi-k26 --oah_url http://127.0.0.1:8788 \
    --problem_path VisualSolver/data/benchmark/benchmark.json \
    --output_dir output/exp_kimik26 --start_index 115
```

## 11. Evaluate diagrams

Score the generated diagrams across five dimensions. The total score is the **geometric mean** of the five dimension scores (a score of 0 in any dimension zeroes the total; render failures also zero the total).

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

### Key parameters

| Parameter | Description |
|-----------|-------------|
| `--input_dir` | Generation output directory to evaluate |
| `--output_dir` | Evaluation output directory |
| `--oah_url` | OAH service address for the judge agents |
| `--workers` | Number of parallel evaluation workers (default 1) |
| `--problem` | Evaluate a single problem by name |
| `--force` | Re-evaluate even if a report already exists |
| `--trace_dir` | Directory for evaluation traces |

### Five dimensions

| Dim | Key | Description |
|-----|-----|-------------|
| 1 | `dim1_accuracy` | Problem alignment — does the diagram match the problem? |
| 2 | `dim2_interaction` | Interactive functionality — do interactions work? |
| 3 | `dim3_visual` | Visual quality — element quality, layout, style consistency |
| 4 | `dim4_pedagogy` | Pedagogical effectiveness — cognitive guidance, step pacing |
| 5 | `dim5_logic_coherence` | Logical coherence — scene progression, state consistency |

## 12. View results

```bash
# Generation output structure
ls output/exp_kimik26/
# problem_0_physics_g9/        ← one directory per problem
#   ├── scene1/
#   │   └── scene1.html        ← generated interactive diagram
#   ├── doc/
#   │   └── solution.html
#   └── traces/                ← agent traces (for SFT data extraction)

# Evaluation output structure
ls output/evaluate_kimi26/
# problem_0_physics_g9/
#   ├── evaluation_report.xml  ← 5-dim scores + reasoning
#   └── dim{1-5}_result.txt    ← per-dimension score
# evaluation_summary.json      ← aggregate summary with total_score
```

```bash
# Check generation progress
grep -c "completed" logs/exp_kimik26.log
grep -c "FAILED\|ERROR" logs/exp_kimik26.log

# View a summary of evaluation scores
python3 -c "import json; d=json.load(open('output/evaluate_kimi26/evaluation_summary.json')); print('avg_score:', d.get('avg_score'))"
```

## 13. Operations

```bash
# Stop OAH instances
cd $WORKSPACE/test_oah_server2
bash scripts/start_instances.sh stop

# Clean workspaces (free SQLite space)
curl -s http://127.0.0.1:8787/api/v1/workspaces | \
  python3 -c "import sys,json; [print(w['id']) for w in json.load(sys.stdin).get('items',[])]" | \
  xargs -I{} curl -s -X DELETE "http://127.0.0.1:8787/api/v1/workspaces/{}"

# View OAH logs
tail -f $WORKSPACE/test_oah_server2/logs/instance_1.log

# Check instance status
for port in 8787 8788 8789; do
  echo "Port $port: $(curl -s http://127.0.0.1:$port/healthz 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("status","?"))' 2>/dev/null || echo 'STOPPED')"
done
```
