# 教师备课助手

输入题目，AI 生成交互式步骤图示，教师可在线预览、修改图示、保存题库。支持多用户登录注册。

## 技术栈

- **前端**: Vue 3 + TypeScript + Vite
- **后端**: Express + TypeScript (tsx)
- **认证**: JWT（bcryptjs 密码哈希，30天有效）
- **Python 桥接**: 通过子进程调用 `ExplanationGenerator` 生成图示

## 快速开始

```bash
cd teacher_app
npm install

# 开发模式 (Vite 5173 + Express 8765)
npm run dev

# 生产模式（构建 + 启动）
npm run build
npm start

# 后台部署（日志写入 /tmp/teacher_app.log）
nohup npm start > /tmp/teacher_app.log 2>&1 &

# 停止后台服务
pkill -f "tsx src/server/index.ts"
```

浏览器打开 `http://<IP>:8001`（端口由项目根目录 `.env` 中的 `PORT` 变量指定，默认 `8001`）。

默认测试账号：用户名 `test`，密码 `test`。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `8001` | 服务监听端口（在项目根 `.env` 中设置） |
| `TEACHER_MODEL` | `qwen3.5-397b` | 生成使用的模型 |
| `JWT_SECRET` | `teacher-app-secret-2024` | JWT 签名密钥（生产环境请修改） |
| `MAX_CONCURRENT_JOBS` | `20` | 最大并发 worker 数 |

## 功能

- **用户系统**：登录/注册，每用户独立题库，JWT 认证
- **生成图示**：输入题目文字或粘贴/拍照识别题目图片，AI 规划大纲并逐步生成交互式 HTML 场景
- **进度显示**：Header 进度条实时反映生成阶段，每个 Scene 完成即刻展示；超过并发上限时显示排队位置
- **修改图示**：右下角输入框输入修改需求，点击"🎨 修改 Scene N"重新生成当前场景
- **下载图示**：Scene 右上角下载按钮，保存当前 HTML 到本地
- **题库管理**：保存题目到题库（生成中也可保存），题库列表显示完成状态（✓已完成/未完成），支持恢复、继续生成、删除

## 目录结构

```
src/
  server/
    index.ts              Express 入口，监听端口，启动时迁移旧数据库
    middleware/
      auth.ts             JWT requireAuth 中间件
    routes/
      auth.ts             POST /api/auth/login, /register; GET /api/auth/me
      generate.ts         生成任务队列（并发控制 + Job 30分钟自动清理）
      bank.ts             题库 CRUD，按用户隔离
      doc.ts              静态 HTML 图示文件服务
      ocr.ts              图片 OCR
      chat.ts             流式对话
      proxy.ts            模型反向代理
  bridge/
    worker.py             Python 桥接，读取 stdin JSON 命令，
                          调用 ExplanationGenerator，输出 JSON 事件流
  client/
    App.vue               主布局，登录守卫，Header 用户名+退出
    components/
      LoginPage.vue       登录/注册页（Logo左上角，JWT存localStorage）
      ProblemInput.vue    题目输入区（文字/图片/OCR，支持继续生成按钮）
      SceneViewer.vue     Scene 展示 iframe + 下载按钮
      AnalysisPanel.vue   解析文字面板（Markdown + MathJax）
      BottomBar.vue       右下角修改图示输入框
      QuestionBank.vue    题库弹窗（完成状态/恢复/继续生成/删除）
    composables/
      useAuth.ts          login/register/logout/initAuth + currentUser
      useGenerate.ts      生成状态管理（startGenerate/continueGenerate/modifyScene）
      useRecorder.ts      语音录入
      useTTS.ts           文字朗读
    utils/
      api.ts              apiUrl() + apiFetch()（自动注入 Authorization header）
data/
  users.json              用户列表（bcrypt 密码哈希）
  users/{username}/
    database.json         每用户独立题库
```

## API

| 路由 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/api/auth/login` | POST | 否 | 登录，返回 JWT |
| `/api/auth/register` | POST | 否 | 注册，返回 JWT |
| `/api/auth/me` | GET | 否 | 验证 token |
| `/api/generate` | POST | 否 | 启动图示生成任务，返回 `job_id` |
| `/api/poll/:jobId` | GET | 否 | 轮询生成事件（progress/scene_ready/done/error） |
| `/api/modify_scene` | POST | 否 | 修改指定 Scene |
| `/api/bank/save` | POST | ✓ | 保存题目到题库 |
| `/api/bank/list` | GET | ✓ | 获取题库列表（含完成状态） |
| `/api/bank/:id` | GET | ✓ | 获取单条题目（含 scenes/texts） |
| `/api/bank/:id` | DELETE | ✓ | 删除题目 |
| `/api/ocr` | POST | 否 | 图片 OCR 识别 |
| `/api/tts` | POST | 否 | 文字转语音 |
| `/api/asr` | POST | 否 | 语音转文字 |
| `/doc/*` | GET | 否 | 静态图示 HTML 文件 |

## 事件协议（worker.py → generate.ts）

```jsonc
{"type": "progress", "message": "...", "percent": 5}
{"type": "scene_ready", "scene": 1, "url": "doc/output/teacher/..."}
{"type": "done", "scenes": [...], "texts": [...]}
{"type": "error", "message": "..."}
```

## 数据存储

- **用户**: `teacher_app/data/users.json`
- **题库**: `teacher_app/data/users/{username}/database.json`（原子写入 + 写锁）
- **图示输出**: `output/teacher/{topic}/scene{N}/code/{topic}_scene{N}_v{M}.html`
- **完成标记**: `output/teacher/{topic}/doc/solution.html` 存在即为已完成
