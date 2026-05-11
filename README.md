# EduIllustrate

English | [简体中文](README_CN.md)

## 📖 Overview

**EduIllustrate** is an AI-powered educational diagram generation system that automatically creates detailed illustrated explanations for problems in mathematics, physics, chemistry, biology, and other subjects.

The system takes problem descriptions and images as input, and through a multi-stage planning, code generation, and rendering pipeline, produces:
- 📝 Structured Markdown explanation documents
- 🎨 High-quality diagrams rendered with Manim
- 🌐 Support for bilingual output (English and Chinese)

## ✨ Key Features

- 🤖 **Multi-Model Support**: Compatible with OpenAI GPT, Anthropic Claude, Google Gemini, Moonshot Kimi, and other mainstream LLMs
- 🎬 **Professional Diagrams**: Generates educational-grade mathematical/physical/chemical animation diagrams using Manim
- 📊 **Multi-Dimensional Evaluation**: Built-in 8-dimensional document quality assessment system
- 🔄 **Auto-Retry**: Intelligent error detection and code fixing mechanism
- ⚡ **Concurrent Processing**: Supports both scene-level and problem-level concurrency for improved efficiency
- 🌍 **Smart Translation**: One-click translation to Chinese while preserving all LaTeX formulas and formatting

## 🏗️ Architecture

```
EduIllustrate
├── VisualSolver/                  # HTML diagram generation engine (pip package)
│   ├── pyproject.toml             # Package declaration (pip install -e)
│   ├── visual_solver/             # Python package
│   │   ├── generate_explanation.py
│   │   ├── src/                   # core, config, rag, utils
│   │   ├── mllm_tools/            # LLM interface wrappers
│   │   └── task_generator/        # Task and prompt generation
│   └── ...
├── teacher_app/                   # Teacher preparation assistant (Vue 3 + Express)
│   ├── src/
│   │   ├── server/                # Express backend (API + static file serving)
│   │   ├── client/                # Vue 3 frontend
│   │   └── bridge/                # Python bridge (worker.py)
│   └── data/                      # User data & question bank
├── deploy/                        # Docker deployment configuration
├── evaluate.py                    # Evaluation script
├── eval_suite/                    # Evaluation suite
└── data/                          # Datasets
```

## 🚀 Quick Start

### 1. Requirements

- Python 3.8+
- FFmpeg (for video processing)
- LaTeX (for math formula rendering)
- Cairo and Pango (for Manim)

### 2. Installation

#### Ubuntu/Debian

```bash
# Install system dependencies
sudo apt-get update
sudo apt-get install -y \
    ffmpeg \
    texlive-full \
    libcairo2-dev \
    libpango1.0-dev \
    libsdl-pango-dev \
    portaudio19-dev

# Clone the main repository
git clone -b EduIllustrate-teacher https://github.com/bisz9918-maker/tutor.git EduIllustrate-teacher
cd EduIllustrate-teacher

# Clone VisualSolver package into the project (not included in main repo, must clone separately)
git clone -b visual-solver-package https://github.com/bisz9918-maker/tutor.git VisualSolver

# Create virtual environment and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e VisualSolver
```

#### macOS

```bash
# Install system dependencies
brew install ffmpeg
brew install cairo pango
brew install portaudio

# Install LaTeX
brew install --cask mactex

# Clone the main repository
git clone -b EduIllustrate-teacher https://github.com/bisz9918-maker/tutor.git EduIllustrate-teacher
cd EduIllustrate-teacher

# Clone VisualSolver package into the project (not included in main repo, must clone separately)
git clone -b visual-solver-package https://github.com/bisz9918-maker/tutor.git VisualSolver

# Create virtual environment and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e VisualSolver
```

### 3. Configure API Keys

Copy the environment template and configure your API keys:

```bash
cp .env.template .env
```

Edit the `.env` file with your model service credentials:

```bash
# OpenAI
OPENAI_API_KEY=your_openai_api_key

# Anthropic Claude
ANTHROPIC_API_KEY=your_anthropic_api_key

# Google Gemini
GOOGLE_API_KEY=your_google_api_key

# Moonshot Kimi
MOONSHOT_API_KEY=your_moonshot_api_key

# Custom API endpoint (optional)
CUSTOM_API_BASE=https://your-custom-endpoint.com
```

### 4. Run Generation

#### Generate explanation for a single problem

```bash
python -m visual_solver.generate_explanation \
  --model "gpt-5" \
  --problem_path data/benchmark/benchmark.json \
  --output_dir output/my_experiment \
  --index 0 \
  --max_retries 3 \
  --translate_to_chinese
```

#### Batch generation for multiple problems

```bash
python -m visual_solver.generate_explanation \
  --model "claude-opus-4-6" \
  --problem_path data/benchmark/benchmark.json \
  --output_dir output/batch_experiment \
  --index 0,1,2,3,4 \
  --max_scene_concurrency 3 \
  --max_topic_concurrency 2 \
  --translate_to_chinese
```

### 5. View Results

Generated documents are located at:
```
output/my_experiment/<problem_name>/doc/
├── solution.md          # Explanation document
├── scene1.png          # Scene 1 diagram
├── scene2.png          # Scene 2 diagram
└── ...
```

## 📝 Usage Guide

### Command Line Arguments

#### Generation Parameters (`generate_explanation.py`)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--model` | LLM to use (e.g., gpt-5, claude-opus-4-6, Kimi-K25) | Required |
| `--problem_path` | Path to problem dataset JSON file | Required |
| `--output_dir` | Output directory | Required |
| `--index` | Problem index to process (single or comma-separated list) | - |
| `--max_retries` | Maximum retry attempts on errors | 3 |
| `--max_scene_concurrency` | Concurrent scenes within a single problem | 5 |
| `--max_topic_concurrency` | Concurrent problems to process | 1 |
| `--translate_to_chinese` | Translate output to Chinese | False |
| `--use_visual_fix_code` | Enable visual code fixing | False |
| `--disable_code` | Skip code generation (text only) | False |

#### Evaluation Parameters (`evaluate.py`)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--eval_type` | Evaluation type: doc, explanation, text, image | Required |
| `--file_path` | Path to file or directory to evaluate | Required |
| `--output_folder` | Evaluation result output directory | Required |
| `--model_doc` | Model to use for document evaluation | gpt-5 |
| `--bulk_evaluate` | Batch evaluation mode | False |
| `--combine` | Combine all evaluation results | False |
| `--problem_data_path` | Original problem data path (for reference answers) | - |
| `--max_workers` | Number of concurrent evaluation processes | 4 |

### Workflow

EduIllustrate uses a multi-stage generation pipeline with two code generation strategies:

#### 1. Outline Planning

The system analyzes the problem and generates a structured outline, decomposing the explanation into text blocks `<TEXT_k>` and diagram scenes `<SCENE_k>`:

```xml
<SCENE_OUTLINE>
  <TEXT_1>First, let's understand the problem...</TEXT_1>
  <SCENE_1>Draw the geometric figure from the problem, annotate known conditions</SCENE_1>
  <TEXT_2>According to the Pythagorean theorem...</TEXT_2>
  <SCENE_2>Show the right triangle, highlight the relationship between three sides</SCENE_2>
  ...
</SCENE_OUTLINE>
```

#### 2. Code Generation Strategies

**Default Strategy (Incremental):**
- Generates a detailed implementation plan for Scene 1 only
- Scene 1 code is generated based on the implementation plan
- Subsequent scenes (Scene 2, 3, ...) are generated directly from:
  - The outline description for that scene
  - Scene 1's code as a reference example
- This approach maintains consistency by using Scene 1 as a style template

**All_Parallel Branch Strategy:**
- Generates detailed implementation plans for **all scenes** independently
- Each scene's code is generated based on its own implementation plan
- Scenes can be processed in parallel for faster generation
- Provides more flexibility but may have less style consistency

#### 3. Rendering

- Renders each scene using `manim -pql -s` (low quality + save last frame)
- Exports the last frame of each scene as a PNG image

#### 4. Document Assembly

- Assembles text blocks and scene images into a complete Markdown document
- Optional: Translates to Chinese (preserving all LaTeX formulas and formatting)

### Data Format

#### Input Data Format (JSON)

```json
[
  {
    "problem": "Problem description text...",
    "img": "base64-encoded problem image",
    "img_caption": "Image caption",
    "format_answer": "Standard answer",
    "topic": "physics",
    "grade": "9"
  }
]
```

#### Output Directory Structure

```
output/
└── my_experiment/
    └── problem_0_physics_g9/
        ├── doc/
        │   ├── solution.md        # Final explanation document
        │   ├── scene1.png        # Scene diagram
        │   └── scene2.png
        ├── scene1/
        │   ├── code/             # Manim code
        │   ├── media/            # Rendering output
        │   └── prompt.json       # Prompt records
        ├── scene2/
        │   └── ...
        └── timing.json           # Timing statistics
```

## 📊 Evaluation System

### Document Evaluation (--eval_type doc)

Evaluates the quality of generated illustrated explanation documents across 8 dimensions:

#### Text Dimensions (text only)

1. **Correctness and Completeness of Solution Steps** (0-5 points)
2. **Logical Coherence of Explanation** (0-5 points)
3. **Understandability and Teaching Effect** (0-5 points)
4. **Layout and Visual Clarity** (0-5 points)

#### Text-Diagram Synergy Dimensions

5. **Diagram Match with Problem** (0-5 points, each scene compared with original)
6. **Text-Diagram Synergy** (0-5 points, evaluates text-diagram coordination)

#### Diagram Dimensions

7. **Element Layout Quality** (0-5 points, each image evaluated independently)
8. **Visual Consistency** (0-5 points, all images compared with the first)

**Overall Score**: Geometric mean of all dimension scores

### Evaluation Examples

#### Evaluate a single document

```bash
python evaluate.py \
  --eval_type doc \
  --file_path "output/my_experiment/problem_0_physics_g9/doc" \
  --output_folder "output/doc_evaluation" \
  --model_doc "gpt-5" \
  --problem_data_path "data/benchmark/benchmark.json"
```

#### Batch evaluation

```bash
python evaluate.py \
  --eval_type doc \
  --file_path "output/my_experiment" \
  --output_folder "output/doc_evaluation" \
  --model_doc "claude-opus-4-6" \
  --bulk_evaluate \
  --combine \
  --max_workers 4
```

#### View evaluation results

```bash
# Individual problem evaluation result
cat output/doc_evaluation/evaluation_problem_0_physics_g9_*.json

# Combined summary results
cat output/doc_evaluation/combined_evaluation_*.json
```

Evaluation results include:
- Detailed scores and comments for each dimension
- Overall score
- Evaluation timestamp and model information
- Original problem reference information

## 🔧 Advanced Features

### 1. Visual Code Fixing

When enabled, the system uses rendered images as visual feedback to fix code errors:

```bash
python -m visual_solver.generate_explanation \
  --model "gpt-5" \
  --problem_path data/benchmark/benchmark.json \
  --output_dir output/visual_fix_test \
  --index 0 \
  --use_visual_fix_code
```

### 2. RAG Retrieval Augmentation

The system can use a vector database to retrieve similar examples to improve generation quality. After configuring an example codebase, the system automatically retrieves relevant references.

### 3. Custom Prompts

Modify prompt files in the `task_generator/prompts_raw/` directory, then regenerate:

```bash
cd task_generator
python parse_prompt.py
cd ..
```

### 4. Concurrency Optimization

For large-scale batch generation, optimize concurrency parameters:

```bash
python -m visual_solver.generate_explanation \
  --model "claude-opus-4-6" \
  --problem_path data/benchmark/benchmark.json \
  --output_dir output/large_batch \
  --max_scene_concurrency 5 \
  --max_topic_concurrency 3
```

- `max_scene_concurrency`: Number of scenes processed simultaneously within a single problem
- `max_topic_concurrency`: Number of problems processed simultaneously

## 👩‍🏫 Teacher App Deployment

The Teacher Preparation Assistant is a standalone full-stack web application that lets teachers input problems through a browser and have AI automatically generate interactive step-by-step diagrams.

### Tech Stack

- **Frontend**: Vue 3 + TypeScript + Vite
- **Backend**: Express 5 + TypeScript (tsx)
- **Python Bridge**: Express spawns `worker.py` as a subprocess to drive `ExplanationGenerator`
- **Auth**: JWT (bcryptjs password hashing, 30-day validity)

### Prerequisites

- Node.js 22+
- Python 3.10+ (with VisualSolver package installed)
- LLM API key (at least one configured)
- (Optional) OAH service for HTML diagram generation

### Option 1: Local Development

```bash
# 1. Clone the main repository
git clone -b EduIllustrate-teacher https://github.com/bisz9918-maker/tutor.git EduIllustrate-teacher
cd EduIllustrate-teacher

# 2. Clone VisualSolver package into the project
git clone -b visual-solver-package https://github.com/bisz9918-maker/tutor.git VisualSolver

# 3. Install VisualSolver Python package
python3 -m venv .venv
source .venv/bin/activate
pip install -e VisualSolver

# 4. Install teacher app frontend dependencies
cd teacher_app
npm install

# 3. Configure environment variables
cp ../.env.template ../.env
# Edit ../.env, at minimum configure:
#   SERVER_PORT=8765
#   CUSTOM_API_BASE=...
#   CUSTOM_API_KEY=...
#   TEACHER_MODEL=claude-sonnet-4-6
#   OAH_API_URL=http://<oah-host>:8787  (if using OAH)

# 4. Start dev servers (Vite HMR + Express backend)
cd /path/to/EduIllustrate-teacher/teacher_app
npm run dev
```

In development mode:
- Frontend Vite dev server: `http://localhost:5175` (auto-proxies `/api` to backend)
- Express backend: `http://localhost:8765`

### Option 2: Local Production

```bash
# 1. Ensure VisualSolver is installed and .env is configured (same as Option 1)

# 2. Build frontend
cd /path/to/EduIllustrate-teacher/teacher_app
npm run build    # Generates dist/client/ and dist/server/

# 3. Start production server
npm start        # NODE_ENV=production tsx src/server/index.ts

# 4. Background deployment (optional)
nohup npm start > /tmp/teacher_app.log 2>&1 &

# Stop background service
pkill -f "tsx src/server/index.ts"
```

In production, Express serves both the frontend static files and the API. Visit `http://<IP>:8765`.

### Option 3: Docker Deployment (Recommended for Production)

Docker packages Node.js + Python + VisualSolver into a single container image — no need to manually configure the Python environment on the server.

```bash
# 1. Transfer code to remote server
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
  /path/to/EduIllustrate-teacher/ \
  user@server:/home/user/EduIllustrate-teacher/

# 2. Configure .env on the remote server
ssh user@server
cd /home/user/EduIllustrate-teacher
cp .env.template .env
vim .env   # Fill in actual configuration

# Required variables:
# SERVER_PORT=8765
# CUSTOM_API_BASE=...          # LLM API endpoint
# CUSTOM_API_KEY=...           # LLM API key
# TEACHER_MODEL=...            # Model name to use
# OAH_API_URL=http://...       # OAH service address (if using)
# OCR_URL=...                  # OCR service address (if image recognition needed)
# OCR_KEY=...

# 3. Build image and start
docker compose -f deploy/docker-compose.prod.yml build
docker compose -f deploy/docker-compose.prod.yml up -d

# 4. Verify
docker compose -f deploy/docker-compose.prod.yml ps
docker compose -f deploy/docker-compose.prod.yml logs -f
curl http://localhost:8765
```

Visit `http://<server-ip>:8765` in your browser. Default test account: username `test`, password `test`.

#### Docker Image Architecture

The image uses a multi-stage build:
1. **Stage 1** — `node:22-alpine`: Builds the Vue frontend (`npm run build`)
2. **Stage 2** — `python:3.11-slim`: Installs the VisualSolver Python package
3. **Stage 3** — `node:22-slim`: Runtime image with Node.js + apt Python3 + installed pip packages

The final image contains only runtime-essential files. Express starts via `npx tsx`, and the Python worker is invoked as a subprocess.

#### Data Persistence

| Volume | Container Path | Description |
|--------|---------------|-------------|
| `app-data` | `/app/data` | User data, question bank database |
| `app-output` | `/app/output` | Generated diagram files |

`.env` is bind-mounted as read-only; restart to apply changes.

#### Docker Operations

```bash
# View logs
docker compose -f deploy/docker-compose.prod.yml logs -f teacher-app

# Restart
docker compose -f deploy/docker-compose.prod.yml restart

# Redeploy after code update
docker compose -f deploy/docker-compose.prod.yml build --no-cache
docker compose -f deploy/docker-compose.prod.yml up -d

# Restart after .env change
docker compose -f deploy/docker-compose.prod.yml restart

# Clean output data
docker volume rm eduillustrate-teacher_app-output

# Debug inside container
docker compose -f deploy/docker-compose.prod.yml exec teacher-app bash
python3 -c "from visual_solver import ExplanationGenerator; print('OK')"
```

### Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_PORT` | `8765` | Server listening port |
| `TEACHER_MODEL` | `claude-sonnet-4-6` | Model for generation (comma-separated for multiple, or `{model:label}` format) |
| `TEACHER_MODEL_DEFAULT` | First in list | Default model when multiple are configured |
| `CUSTOM_API_BASE` | - | OpenAI-compatible LLM API endpoint |
| `CUSTOM_API_KEY` | - | LLM API key |
| `OAH_API_URL` | - | OAH service address (for HTML diagram generation) |
| `JWT_SECRET` | `teacher-app-secret-2024` | JWT signing secret (**must change in production**) |
| `MAX_CONCURRENT_JOBS` | `20` | Maximum concurrent Python workers |
| `PYTHON` | `.venv/bin/python` | Python interpreter path (`/usr/bin/python3` in Docker) |
| `OCR_URL` / `OCR_KEY` | - | OCR service config (image recognition) |

### API Routes

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/api/auth/login` | POST | No | Login, returns JWT |
| `/api/auth/register` | POST | No | Register, returns JWT |
| `/api/auth/me` | GET | No | Verify token |
| `/api/generate` | POST | No | Start diagram generation task, returns `job_id` |
| `/api/stream/:jobId` | GET | No | SSE real-time event stream |
| `/api/poll/:jobId` | GET | No | Poll generation events |
| `/api/modify_scene` | POST | JWT | Modify a specific Scene |
| `/api/bank/save` | POST | JWT | Save problem to question bank |
| `/api/bank/list` | GET | JWT | Get question bank list |
| `/api/bank/:id` | GET/DELETE | JWT | Get/delete a problem |
| `/api/ocr` | POST | No | Image OCR recognition |
| `/doc/*` | GET | No | Static diagram HTML files |

For detailed teacher app development docs, see [teacher_app/README.md](teacher_app/README.md). For Docker deployment details, see [deploy/README.md](deploy/README.md).

---

## 🤝 Contributing

Issues and Pull Requests are welcome!

### Development Setup

```bash
# Clone the repository
git clone <repository-url>
cd EduIllustrate

# Install development dependencies
git clone -b visual-solver-package https://github.com/bisz9918-maker/tutor.git VisualSolver
pip install -e VisualSolver

# Run tests
python -m pytest tests/
```

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## 📚 Citation

If this project helps your research, please cite:

```bibtex
@software{eduillustrate2026,
  title={EduIllustrate: An Agentic Pipeline for Generating Diagram-Rich Explanations of K-12 STEM Problems},
  author={Shuzhen Bi},
  year={2026},
  url={https://github.com/bisz9918-maker/EduIllustrate}
}
```

## 🙏 Acknowledgments

This project is built upon these excellent open-source projects:

- [TheoremExplainAgent](https://github.com/TIGER-AI-Lab/TheoremExplainAgent) - Agent for theorem explanation video generation
- [Manim](https://github.com/ManimCommunity/manim) - Mathematical animation engine
- [LiteLLM](https://github.com/BerriAI/litellm) - Unified LLM API interface

## 📧 Contact

For questions or suggestions, please:

- Submit a GitHub Issue
- Email: bisz9918@gmail.com

---

**EduIllustrate** - Empowering Education with AI 🚀
