# 教师备课助手 — TypeScript 全栈重构计划

## Context

当前 `teacher_app/` 使用 Flask (Python) 后端 + 原始 HTML 前端。前端存在浏览器兼容性问题（如粘贴截图失败），且原始 HTML 难以维护。改为 TypeScript 全栈 + Vue 3 前端。

核心挑战：后端依赖 Python 模块 `ExplanationGenerator`，通过 Python 桥接脚本调用。

## 文件结构

```
teacher_app/
  package.json
  tsconfig.json
  tsconfig.node.json
  vite.config.ts
  index.html               ← Vite 入口 HTML
  src/
    server/
      index.ts              ← Express 后端入口
      routes/
        generate.ts         ← /api/generate + /api/stream/:jobId (SSE)
        proxy.ts            ← /api/ocr, /api/tts, /api/asr (转发)
        chat.ts             ← /api/chat (SSE 流式)
        doc.ts              ← /doc/* 静态文件
    bridge/
      worker.py             ← Python 桥接脚本
    client/
      main.ts               ← Vue app 入口
      App.vue               ← 根组件（布局）
      style.css             ← 全局样式
      components/
        TopBar.vue          ← 顶栏 + 状态
        ProblemInput.vue    ← 题目输入 + OCR + 粘贴
        AnalysisPanel.vue   ← 解析区 (marked + MathJax + TTS)
        SceneViewer.vue     ← 右侧 Scene 标签 + iframe
        ChatPanel.vue       ← 对话浮层
        BottomBar.vue       ← 底部输入 + 麦克风
      composables/
        useGenerate.ts      ← 生成任务 SSE 状态管理
        useChat.ts          ← 对话 SSE 流式
        useRecorder.ts      ← 麦克风录音 + ASR
        useTTS.ts           ← TTS 朗读
```

## Python 桥接 (`bridge/worker.py`)

- 从 stdin 读取 JSON 命令: `{"action":"generate", "description":"...", "topic":"..."}`
- 调用 `ExplanationGenerator.generate_html_diagrams()`
- 通过 stdout 逐行输出 JSON 事件 (`progress` / `scene_ready` / `done` / `error`)
- TypeScript 后端用 `child_process.spawn` 启动，逐行读取 stdout，转发为 SSE

## 后端 API（与原 Flask 一致）

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/generate` | POST | 启动生成任务，返回 `{job_id}` |
| `/api/stream/:jobId` | GET | SSE 推送进度 |
| `/api/ocr` | POST | 转发 OCR 服务 |
| `/api/tts` | POST | 转发 TTS 服务 |
| `/api/asr` | POST | 转发 ASR 服务 |
| `/api/chat` | POST | 流式对话 (SSE) |
| `/doc/*` | GET | 生成文件静态服务 |

## 技术栈

- **后端**: Express + TypeScript + tsx (运行)
- **前端**: Vue 3 + TypeScript + Vite
- **桥接**: child_process.spawn → Python worker

## 实现步骤

1. 初始化项目: package.json, tsconfig, vite.config.ts
2. 实现 bridge/worker.py
3. 实现 Express 后端 (server/index.ts + routes)
4. 实现 Vue 前端组件
5. 集成测试

## 运行

```bash
cd teacher_app
npm install
npm run dev      # 开发模式 (Vite + Express 并行)
```
