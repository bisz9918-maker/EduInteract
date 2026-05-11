# EduIllustrate

[English](README.md) | 简体中文

## 📖 项目简介

**EduIllustrate** 是一个基于大语言模型的教育图文讲解生成系统,能够自动为数学、物理、化学、生物等学科题目生成包含动画图示的详细讲解文档。

系统输入题目描述和图片,通过多阶段规划、代码生成和渲染流程,输出:
- 📝 结构化的 Markdown 讲解文档
- 🎨 使用 Manim 渲染的高质量示意图
- 🌐 支持中英文双语输出

## ✨ 主要特性

- 🤖 **多模型支持**: 支持 OpenAI GPT、Anthropic Claude、Google Gemini、Moonshot Kimi 等主流大模型
- 🎬 **专业图示**: 基于 Manim 生成教学级别的数学/物理/化学动画图示
- 📊 **多维度评估**: 内置8个维度的文档质量评估系统
- 🔄 **自动重试**: 智能错误检测和代码修复机制
- ⚡ **并发处理**: 支持场景级和题目级并发,提高生成效率
- 🌍 **智能翻译**: 支持一键翻译为中文,保留所有 LaTeX 公式和格式

## 🏗️ 系统架构

```
EduIllustrate
├── VisualSolver/                  # HTML 图示生成引擎 (pip 包)
│   ├── pyproject.toml             # 包声明 (pip install -e)
│   ├── visual_solver/             # Python 包
│   │   ├── generate_explanation.py
│   │   ├── src/                   # core, config, rag, utils
│   │   ├── mllm_tools/            # 大模型接口封装
│   │   └── task_generator/        # 任务和提示词生成
│   └── ...
├── teacher_app/                   # 教师备课助手 (Vue 3 + Express)
│   ├── src/
│   │   ├── server/                # Express 后端 (API + 静态文件服务)
│   │   ├── client/                # Vue 3 前端
│   │   └── bridge/                # Python 桥接 (worker.py)
│   └── data/                      # 用户数据 & 题库
├── deploy/                        # Docker 部署配置
├── evaluate.py                    # 评估脚本
├── eval_suite/                    # 评估套件
└── data/                          # 数据集
```

## 🚀 快速开始

### 1. 环境要求

- Python 3.8+
- FFmpeg (用于视频处理)
- LaTeX (用于数学公式渲染)
- Cairo 和 Pango (用于 Manim)

### 2. 安装依赖

#### Ubuntu/Debian

```bash
# 安装系统依赖
sudo apt-get update
sudo apt-get install -y \
    ffmpeg \
    texlive-full \
    libcairo2-dev \
    libpango1.0-dev \
    libsdl-pango-dev \
    portaudio19-dev

# 克隆主仓库
git clone -b EduIllustrate-teacher https://github.com/bisz9918-maker/tutor.git EduIllustrate-teacher
cd EduIllustrate-teacher

# 克隆 VisualSolver 包到项目内（主仓库不包含 VisualSolver 源码，需单独拉取）
git clone -b visual-solver-package https://github.com/bisz9918-maker/tutor.git VisualSolver

# 创建虚拟环境并安装
python3 -m venv .venv
source .venv/bin/activate
pip install -e VisualSolver
```

#### macOS

```bash
# 安装系统依赖
brew install ffmpeg
brew install cairo pango
brew install portaudio

# 安装 LaTeX
brew install --cask mactex

# 克隆主仓库
git clone -b EduIllustrate-teacher https://github.com/bisz9918-maker/tutor.git EduIllustrate-teacher
cd EduIllustrate-teacher

# 克隆 VisualSolver 包到项目内（主仓库不包含 VisualSolver 源码，需单独拉取）
git clone -b visual-solver-package https://github.com/bisz9918-maker/tutor.git VisualSolver

# 创建虚拟环境并安装
python3 -m venv .venv
source .venv/bin/activate
pip install -e VisualSolver
```

### 3. 配置 API 密钥

复制环境变量模板并配置您的 API 密钥:

```bash
cp .env.template .env
```

编辑 `.env` 文件,配置您使用的模型服务:

```bash
# OpenAI
OPENAI_API_KEY=your_openai_api_key

# Anthropic Claude
ANTHROPIC_API_KEY=your_anthropic_api_key

# Google Gemini
GOOGLE_API_KEY=your_google_api_key

# Moonshot Kimi
MOONSHOT_API_KEY=your_moonshot_api_key

# 自定义 API 端点 (可选)
CUSTOM_API_BASE=https://your-custom-endpoint.com
```

### 4. 运行生成

#### 生成单个题目的讲解

```bash
python -m visual_solver.generate_explanation \
  --model "gemini-3.1-pro-preview" \
  --problem_path data/benchmark/benchmark.json \
  --output_dir output/my_experiment \
  --index 215 \
  --max_retries 3 \
  --max_scene_concurrency 5 \
  --translate_to_chinese
```

#### 批量生成多个题目

```bash
python -m visual_solver.generate_explanation \
  --model "claude-opus-4-6" \
  --problem_path data/benchmark/benchmark.json \
  --output_dir output/batch_experiment \
  --max_scene_concurrency 1 \
  --max_topic_concurrency 10 \
  --translate_to_chinese
```

### 5. 查看结果

生成的文档位于:
```
output/my_experiment/<problem_name>/doc/
├── solution.md          # 讲解文档
├── scene1.png          # 场景1图示
├── scene2.png          # 场景2图示
└── ...
```

## 📝 使用说明

### 主要命令行参数

#### 生成参数 (`generate_explanation.py`)

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--model` | 使用的大模型 (如 gpt-5, claude-opus-4-6, Kimi-K25) | 必填 |
| `--problem_path` | 题目数据集 JSON 文件路径 | 必填 |
| `--output_dir` | 输出目录 | 必填 |
| `--index` | 要处理的题目索引 (单个或逗号分隔列表) | - |
| `--max_retries` | 错误重试次数 | 3 |
| `--max_scene_concurrency` | 单个题目内的并发场景数 | 5 |
| `--max_topic_concurrency` | 并发处理的题目数 | 1 |
| `--translate_to_chinese` | 翻译结果为中文 | False |
| `--use_visual_fix_code` | 启用视觉代码修复 | False |
| `--disable_code` | 跳过代码生成(仅生成文本) | False |

#### 评估参数 (`evaluate.py`)

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--eval_type` | 评估类型: doc(文档), explanation(视频), text(文本), image(图片) | 必填 |
| `--file_path` | 要评估的文件或目录路径 | 必填 |
| `--output_folder` | 评估结果输出目录 | 必填 |
| `--model_doc` | 文档评估使用的模型 | gpt-5 |
| `--bulk_evaluate` | 批量评估模式 | False |
| `--combine` | 合并所有评估结果 | False |
| `--problem_data_path` | 原题数据路径(用于参考答案) | - |
| `--max_workers` | 并发评估的进程数 | 4 |

### 工作流程

EduIllustrate 采用多阶段生成流程,支持两种代码生成策略:

#### 1. 讲解规划 (Outline Planning)

系统分析题目后生成结构化大纲,将讲解内容分解为文本块 `<TEXT_k>` 和图示场景 `<SCENE_k>`:

```xml
<SCENE_OUTLINE>
  <TEXT_1>首先,我们来理解题目...</TEXT_1>
  <SCENE_1>绘制题目中的几何图形,标注已知条件</SCENE_1>
  <TEXT_2>根据勾股定理...</TEXT_2>
  <SCENE_2>展示直角三角形,突出显示三边关系</SCENE_2>
  ...
</SCENE_OUTLINE>
```

#### 2. 代码生成策略

**默认策略 (增量式):**
- 仅为场景1生成详细的实现计划
- 场景1的代码基于实现计划生成
- 后续场景(场景2、3、...)直接基于以下内容生成代码:
  - 该场景的大纲描述
  - 场景1的代码作为参考示例
- 这种方法通过使用场景1作为风格模板来保持一致性

**All_Parallel 分支策略:**
- 为**所有场景**独立生成详细的实现计划
- 每个场景的代码基于自己的实现计划生成
- 场景可以并行处理以加快生成速度
- 提供更多灵活性但风格一致性可能较低

#### 3. 渲染 (Rendering)

- 使用 `manim -pql -s` 渲染每个场景(低质量 + 保存最后一帧)
- 导出每个场景的最后一帧为 PNG 图片

#### 4. 文档组装 (Document Assembly)

- 将文本块和场景图片组装成完整的 Markdown 文档
- 可选: 翻译为中文(保留所有 LaTeX 公式和格式)

### 数据格式

#### 输入数据格式 (JSON)

```json
[
  {
    "problem": "题目描述文本...",
    "img": "base64编码的题目图片",
    "img_caption": "图片描述",
    "format_answer": "标准答案",
    "topic": "physics",
    "grade": "9"
  }
]
```

#### 输出目录结构

```
output/
└── my_experiment/
    └── problem_0_physics_g9/
        ├── doc/
        │   ├── solution.md        # 最终讲解文档
        │   ├── scene1.png        # 场景图示
        │   └── scene2.png
        ├── scene1/
        │   ├── code/             # Manim 代码
        │   ├── media/            # 渲染输出
        │   └── prompt.json       # 提示词记录
        ├── scene2/
        │   └── ...
        └── timing.json           # 时间统计
```

## 📊 评估系统

### 文档评估 (--eval_type doc)

评估生成的图文讲解文档质量,包含 8 个维度:

#### 文本维度 (仅评估文字)

1. **解题步骤的正确性和完整性** (0-5分)
2. **讲解的逻辑连贯性** (0-5分)
3. **讲解的易懂性和教学效果** (0-5分)
4. **排版和视觉呈现的清晰度** (0-5分)

#### 图文协同维度

5. **图示与题目的匹配度** (0-5分, 每个场景与原题对比)
6. **图文协同的流畅性** (0-5分, 评估图文配合)

#### 图片维度

7. **图片元素布局质量** (0-5分, 每张图独立评估)
8. **视觉一致性** (0-5分, 所有图与第一张对比)

**综合得分**: 所有维度分数的几何平均值

### 评估命令示例

#### 评估单个文档

```bash
python evaluate.py \
  --eval_type doc \
  --file_path "output/my_experiment/problem_0_physics_g9/doc" \
  --output_folder "output/doc_evaluation" \
  --model_doc "gpt-5" \
  --problem_data_path "data/benchmark/benchmark.json"
```

#### 批量评估

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

#### 查看评估结果

```bash
# 单个问题的评估结果
cat output/doc_evaluation/evaluation_problem_0_physics_g9_*.json

# 合并后的汇总结果
cat output/doc_evaluation/combined_evaluation_*.json
```

评估结果包含:
- 每个维度的详细评分和评语
- 综合得分
- 评估时间戳和模型信息
- 原题参考信息

## 🔧 高级功能

### 1. 视觉代码修复

启用后,系统会使用渲染出的图片作为视觉反馈来修复代码错误:

```bash
python -m visual_solver.generate_explanation \
  --model "gpt-5" \
  --problem_path data/benchmark/benchmark.json \
  --output_dir output/visual_fix_test \
  --index 0 \
  --use_visual_fix_code
```

### 2. RAG 检索增强

系统可以使用向量数据库检索相似示例来改进生成质量。配置示例代码库后,系统会自动检索相关参考。

### 3. 自定义提示词

修改 `task_generator/prompts_raw/` 目录下的提示词文件,然后重新生成:

```bash
cd task_generator
python parse_prompt.py
cd ..
```

### 4. 并发优化

针对大规模批量生成,优化并发参数:

```bash
python -m visual_solver.generate_explanation \
  --model "claude-opus-4-6" \
  --problem_path data/benchmark/benchmark.json \
  --output_dir output/large_batch \
  --max_scene_concurrency 5 \
  --max_topic_concurrency 3
```

- `max_scene_concurrency`: 单个题目内同时处理的场景数
- `max_topic_concurrency`: 同时处理的题目数

## 👩‍🏫 教师备课助手部署

教师备课助手是一个独立的全栈 Web 应用，让教师通过浏览器输入题目，AI 自动生成交互式步骤图示。

### 技术栈

- **前端**: Vue 3 + TypeScript + Vite
- **后端**: Express 5 + TypeScript (tsx)
- **Python 桥接**: Express 通过子进程调用 `worker.py`，驱动 `ExplanationGenerator` 生成图示
- **认证**: JWT（bcryptjs 密码哈希，30 天有效）

### 前置条件

- Node.js 22+
- Python 3.10+（已安装 VisualSolver 包）
- LLM API 密钥（至少配置一个）
- （可选）OAH 服务，用于 HTML 图示生成

### 方式一：本地开发部署

```bash
# 1. 克隆主仓库
git clone -b EduIllustrate-teacher https://github.com/bisz9918-maker/tutor.git EduIllustrate-teacher
cd EduIllustrate-teacher

# 2. 克隆 VisualSolver 包到项目内
git clone -b visual-solver-package https://github.com/bisz9918-maker/tutor.git VisualSolver

# 3. 安装 VisualSolver Python 包
python3 -m venv .venv
source .venv/bin/activate
pip install -e VisualSolver

# 4. 安装教师端前端依赖
cd teacher_app
npm install

# 5. 配置环境变量
cp ../.env.template ../.env
# 编辑 ../.env，至少配置以下项：
#   SERVER_PORT=8765
#   CUSTOM_API_BASE=...
#   CUSTOM_API_KEY=...
#   TEACHER_MODEL=claude-sonnet-4-6
#   OAH_API_URL=http://<oah-host>:8787  （如果使用 OAH）

# 6. 启动开发服务器（Vite 热更新 + Express 后端）
cd /path/to/EduIllustrate-teacher/teacher_app
npm run dev
```

开发模式下：
- 前端 Vite 开发服务器：`http://localhost:5175`（自动代理 `/api` 到后端）
- Express 后端：`http://localhost:8765`

### 方式二：本地生产部署

```bash
# 1. 克隆仓库（同方式一步骤 1-3）
git clone -b EduIllustrate-teacher https://github.com/bisz9918-maker/tutor.git EduIllustrate-teacher
cd EduIllustrate-teacher
git clone -b visual-solver-package https://github.com/bisz9918-maker/tutor.git VisualSolver
python3 -m venv .venv && source .venv/bin/activate && pip install -e VisualSolver

# 2. 确认 .env 已配置（同方式一步骤 5）

# 3. 构建前端
cd /path/to/EduIllustrate-teacher/teacher_app
npm run build    # 生成 dist/client/ 和 dist/server/

# 4. 启动生产服务
npm start        # NODE_ENV=production tsx src/server/index.ts

# 5. 后台部署（可选）
nohup npm start > /tmp/teacher_app.log 2>&1 &

# 停止后台服务
pkill -f "tsx src/server/index.ts"
```

生产模式下 Express 同时服务前端静态文件和 API，访问 `http://<IP>:8765`。

### 方式三：Docker 部署（推荐生产环境）

Docker 方式将 Node.js + Python + VisualSolver 打包为单容器镜像，无需在服务器上手动配置 Python 环境。

```bash
# 1. 在远程服务器克隆代码
ssh user@server
cd /home/user
git clone -b EduIllustrate-teacher https://github.com/bisz9918-maker/tutor.git EduIllustrate-teacher
cd EduIllustrate-teacher
git clone -b visual-solver-package https://github.com/bisz9918-maker/tutor.git VisualSolver

# 2. 配置 .env
cp .env.template .env
vim .env   # 填入实际配置

# 必须配置的变量：
# SERVER_PORT=8765
# CUSTOM_API_BASE=...          # LLM API 端点
# CUSTOM_API_KEY=...           # LLM API 密钥
# TEACHER_MODEL=...            # 使用的模型名称
# OAH_API_URL=http://...       # OAH 服务地址（如果使用）
# OCR_URL=...                  # OCR 服务地址（如果需要图片识别）
# OCR_KEY=...

# 3. 构建镜像并启动
docker compose -f deploy/docker-compose.prod.yml build
docker compose -f deploy/docker-compose.prod.yml up -d

# 4. 验证
docker compose -f deploy/docker-compose.prod.yml ps
docker compose -f deploy/docker-compose.prod.yml logs -f
curl http://localhost:8765
```

浏览器访问 `http://<服务器IP>:8765`，默认测试账号：用户名 `test`，密码 `test`。

#### Docker 镜像架构

镜像采用多阶段构建：
1. **Stage 1** — `node:22-alpine`：构建 Vue 前端（`npm run build`）
2. **Stage 2** — `python:3.11-slim`：安装 VisualSolver Python 包
3. **Stage 3** — `node:22-slim`：运行时镜像，Node.js + apt Python3 + 已安装的 pip 包

最终镜像仅包含运行时必需的文件，Express 通过 `npx tsx` 启动，Python worker 通过子进程调用。

#### 数据持久化

| Volume | 容器路径 | 说明 |
|--------|---------|------|
| `app-data` | `/app/data` | 用户数据、题库数据库 |
| `app-output` | `/app/output` | 生成的图示文件 |

`.env` 通过 bind mount 挂载为只读，修改后重启生效。

#### Docker 常用操作

```bash
# 查看日志
docker compose -f deploy/docker-compose.prod.yml logs -f teacher-app

# 重启
docker compose -f deploy/docker-compose.prod.yml restart

# 更新代码后重新部署
docker compose -f deploy/docker-compose.prod.yml build --no-cache
docker compose -f deploy/docker-compose.prod.yml up -d

# 修改 .env 后重启
docker compose -f deploy/docker-compose.prod.yml restart

# 清理输出数据
docker volume rm eduillustrate-teacher_app-output

# 进入容器排查问题
docker compose -f deploy/docker-compose.prod.yml exec teacher-app bash
python3 -c "from visual_solver import ExplanationGenerator; print('OK')"
```

### 环境变量参考

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SERVER_PORT` | `8765` | 服务监听端口 |
| `TEACHER_MODEL` | `claude-sonnet-4-6` | 生成使用的模型（支持逗号分隔多模型或 `{model:label}` 格式） |
| `TEACHER_MODEL_DEFAULT` | 列表第一个 | 多模型时的默认模型 |
| `CUSTOM_API_BASE` | - | OpenAI 兼容的 LLM API 端点 |
| `CUSTOM_API_KEY` | - | LLM API 密钥 |
| `OAH_API_URL` | - | OAH 服务地址（用于 HTML 图示生成） |
| `JWT_SECRET` | `teacher-app-secret-2024` | JWT 签名密钥（**生产环境务必修改**） |
| `MAX_CONCURRENT_JOBS` | `20` | 最大并发 Python worker 数 |
| `PYTHON` | `.venv/bin/python` | Python 解释器路径（Docker 中为 `/usr/bin/python3`） |
| `OCR_URL` / `OCR_KEY` | - | OCR 服务配置（图片识别） |

### API 路由

| 路由 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/api/auth/login` | POST | 否 | 登录，返回 JWT |
| `/api/auth/register` | POST | 否 | 注册，返回 JWT |
| `/api/auth/me` | GET | 否 | 验证 token |
| `/api/generate` | POST | 否 | 启动图示生成任务，返回 `job_id` |
| `/api/stream/:jobId` | GET | 否 | SSE 实时事件流 |
| `/api/poll/:jobId` | GET | 否 | 轮询生成事件 |
| `/api/modify_scene` | POST | JWT | 修改指定 Scene |
| `/api/bank/save` | POST | JWT | 保存题目到题库 |
| `/api/bank/list` | GET | JWT | 获取题库列表 |
| `/api/bank/:id` | GET/DELETE | JWT | 获取/删除题目 |
| `/api/ocr` | POST | 否 | 图片 OCR 识别 |
| `/doc/*` | GET | 否 | 静态图示 HTML 文件 |

详细的教师端开发文档见 [teacher_app/README.md](teacher_app/README.md)，Docker 部署详细说明见 [deploy/README.md](deploy/README.md)。

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request!

### 开发设置

```bash
# 克隆主仓库
git clone -b EduIllustrate-teacher https://github.com/bisz9918-maker/tutor.git EduIllustrate-teacher
cd EduIllustrate-teacher

# 克隆 VisualSolver 包到项目内
git clone -b visual-solver-package https://github.com/bisz9918-maker/tutor.git VisualSolver

# 安装开发依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -e VisualSolver

# 运行测试
python -m pytest tests/
```

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

## 📚 引用

如果本项目对您的研究有帮助,欢迎引用:

```bibtex
@software{eduillustrate2026,
  title={EduIllustrate: An Agentic Pipeline for Generating Diagram-Rich Explanations of K-12 STEM Problems},
  author={Shuzhen Bi},
  year={2026},
  url={https://github.com/bisz9918-maker/EduIllustrate}
}
```

## 🙏 致谢

本项目基于以下优秀的开源项目:

- [TheoremExplainAgent](https://github.com/TIGER-AI-Lab/TheoremExplainAgent) - 定理视频讲解智能体
- [Manim](https://github.com/ManimCommunity/manim) - 数学动画引擎
- [LiteLLM](https://github.com/BerriAI/litellm) - 统一的大模型 API 接口

## 📧 联系方式

如有问题或建议,请通过以下方式联系:

- 提交 GitHub Issue
- 邮箱: bisz9918@gmail.com

---

**EduIllustrate** - 让 AI 为教育赋能 🚀
