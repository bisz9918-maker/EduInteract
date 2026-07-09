# 人工评估打分系统

基于 Flask 的交互式网页打分工具，用于对 AI 讲解文档进行人工评估。

---

## 目录结构

```
annotation_app/
├── app.py              # Flask 后端
├── README.md           # 本文档
└── static/
    └── index.html      # 前端页面
```

相关数据文件（位于上级 `output/` 目录）：

```
output/
├── sampled_scores.json     # 抽样的 50 条待评估记录（输入）
└── human_annotations.json # 人工打分结果（自动生成/更新）
```

---

## 启动方法

```bash
# 1. 激活环境
conda activate tea

# 2. 进入 app 目录
cd /inspire/hdd/project/ai4education/bishuzhen-CZXS24220022/edubench/evaluate_vison_solver/VisualSolver/annotation_app

# 3. 启动服务
python app.py
```

服务启动后访问：**http://localhost:7860**

若需后台运行：

```bash
nohup python app.py > annotation_app.log 2>&1 &
```

---

## 界面说明

界面分为三栏：

```
┌─────────────┬──────────────────────────┬────────────────┐
│  左：文档列表  │     中：文档内容渲染          │  右：评分面板    │
└─────────────┴──────────────────────────┴────────────────┘
```

### 顶部进度条

显示当前已完成打分的数量（如 `12 / 50 已完成`）以及进度条。

### 左侧：文档列表

- 列出全部 50 条待评估记录，格式为 `问题名_模型名`，例如：
  `problem_26_biology_g12_kimi-k25`
- **绿点** = 已完成打分
- **灰点** = 尚未打分
- 点击任意条目即可加载对应文档

### 中间：文档内容

- 渲染对应的 `solution.md` 文档，包含题目、解题步骤、图示（自动加载 `scene*.png`）
- 标题栏显示记录名称及文档路径

### 右侧：评分面板

共 **7 个评分维度**（`correctness_and_completeness` 由模型自动评分，不在此打分）：

| 维度 key | 中文名 |
|---|---|
| `logical_coherence` | 讲解的逻辑连贯性 |
| `diagram_match` | 图示与题目的匹配度 |
| `understandability_and_teaching_effect` | 讲解的易懂性和教学效果 |
| `layout_and_visual_clarity` | 排版和视觉呈现的清晰度 |
| `element_layout_quality` | 图片元素布局质量 |
| `visual_consistency` | 视觉一致性 |
| `text_diagram_synergy` | 图文协同的流畅性 |

每个维度显示**模型自动得分**（供参考），并提供三档人工打分按钮：

| 按钮 | 含义 | 颜色 |
|---|---|---|
| `0` | 不符合要求 | 红色 |
| `0.5` | 基本符合，有明显缺陷 | 黄色 |
| `1` | 符合要求 | 绿色 |

---

## 打分流程

1. 从左侧列表点击一条文档（优先选灰点未完成的）
2. 阅读中间的文档内容及图示
3. 在右侧对每个维度点击 `0` / `0.5` / `1` 打分
4. 所有 7 个维度都选择后，「**保存打分**」按钮激活
5. 点击「**保存打分**」，结果立即写入 `output/human_annotations.json`
6. 点击「**下一条 →**」自动跳转到下一个未打分文档

> 已保存的打分重新打开后会自动回填，可随时修改后再次保存。

---

## 打分结果

所有打分实时保存在：

```
output/human_annotations.json
```

格式示例：

```json
{
  "problem_26_biology_g12_kimi-k25": {
    "logical_coherence": 1,
    "diagram_match": 0.5,
    "understandability_and_teaching_effect": 1,
    "layout_and_visual_clarity": 1,
    "element_layout_quality": 0.5,
    "visual_consistency": 1,
    "text_diagram_synergy": 0.5
  }
}
```

---

## 重新抽样

如需重新生成 50 条抽样数据：

```bash
cd ..  # 回到 VisualSolver 目录
python sample_scores.py
```

然后重启服务使新数据生效。
