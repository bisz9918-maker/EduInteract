# Plan: Multi-Dimension Evaluation System

## Context

当前 `eval_one.py` 对每个 scene 独立评测，且只评测交互功能性一个维度。需要重写为4维度评测系统：

- 一个题目一个 workspace，所有 scene + solution 一起上传
- 前置门控：图示能否渲染（pass/fail），不通过则总分0
- 4 个维度：内容准确性、交互功能性、视觉可读性、教育适配性
- 评分单位是**整个题目**，不是 per-scene；agent 综合所有 scene + solution 给出一个维度分
- 总分 = 4个维度分的几何平均

## 评分体系

**每个维度满分 5 分。Agent 综合所有 scene 和 solution 给出整个题目的 0-5 分和评分理由。**

**总分 = 4个维度分的几何平均**

```
题目总分 = (∏ 维度分)^(1/4)
```

**前置门控**：用 Playwright 检查每个 scene 能否渲染，任一 scene 无法渲染则整题0分，不跑 agent。

### 前置门控：图示渲染检查

宿主机 Playwright 本地检查每个 scene HTML 是否能加载并渲染出非空白页面。只做 pass/fail 判断，不参与评分。

任一 scene 渲染失败 → 整题0分，跳过 agent 评测。

### 维度1：内容准确性（5分）— agent: accuracy-eval

Agent 综合所有 scene 和 solution 给出整个题目的 0-5 分和理由。

**核心判断**：图示内容是否符合题意，解题过程是否正确。

**评测方向参考**（agent 根据具体题目自行选择）：
- 题目要求的关键元素是否全部呈现
- 数值、比例、角度等是否准确
- 标注的内容是否正确（数值、符号是否正确）
- 物理量之间的关系是否正确（力的方向、运动轨迹、电路连接等）
- 图形类型是否匹配题意
- 解题过程是否正确：步骤是否合理、推理是否严谨、中间结果是否正确

**与维度3的区分**：本维度只关注"内容对不对"，不关注"看得清不清"（文字重叠、线条模糊、布局拥挤属于维度3）。

### 维度2：交互功能性（5分）— agent: interaction-eval

Agent 综合所有 scene 给出整个题目的 0-5 分和理由。

**评测逻辑**：
1. 读取 spec.json 了解题目要求
2. 读取每个 scene 的 HTML 源代码，分析其中设计了哪些交互
3. 对适用的交互类型用 Playwright 测试 + 截图验证
4. 综合所有 scene 的交互表现给出分数

**关键判断**：
- 题目需要交互 + 交互功能正常 → 高分
- 题目需要交互 + 生成了静态图 → 低分
- 题目不需要交互 + 静态图 → 可给高分
- 题目不需要交互 + 有多余交互 → 不扣分

### 维度3：视觉可读性（5分）— agent: visual-eval

Agent 综合所有 scene 给出整个题目的 0-5 分和理由。

**评测方向参考**：线条清晰度、色彩区分度、标注可读性、布局合理性

**与维度1的区分**：本维度只关注"视觉呈现是否清晰可读"，不关注"内容是否正确"（标注数值对不对、元素是否遗漏、解题过程对不对属于维度1）。

### 维度4：教育适配性（5分）— agent: pedagogy-eval

Agent 综合所有 scene 和 solution 给出整个题目的 0-5 分和理由。

**评测方向参考**：引导性设计、无误导元素、知识点关联、图文配合、solution与图示是否一致、scene划分是否合理

## 文件变更

### 1. 重写 `visual-solver-eval` Runtime（1个 runtime，4个 agent）

```
/Users/bisz/Documents/test_oah_server2/source/runtimes/visual-solver-eval/
└── .openharness/
    ├── settings.yaml          # default_agent: interaction-eval, 4个model配置
    ├── agents/
    │   ├── accuracy-eval.md   # 维度1：内容准确性
    │   ├── interaction-eval.md # 维度2：交互功能性
    │   ├── visual-eval.md     # 维度3：视觉可读性
    │   └── pedagogy-eval.md   # 维度4：教育适配性
    └── models/
        ├── GLM-5.1-FP8.yaml
        └── kimi-k26.yaml
```

settings.yaml：

```yaml
default_agent: interaction-eval
models:
  accuracy-eval:
    ref: platform/kimi-k26
    temperature: 0.1
    top_p: 0.7
  interaction-eval:
    ref: platform/kimi-k26
    temperature: 0.3
    top_p: 0.9
  visual-eval:
    ref: platform/kimi-k26
    temperature: 0.1
    top_p: 0.7
  pedagogy-eval:
    ref: platform/kimi-k26
    temperature: 0.1
    top_p: 0.7
```

### 2. 重写 `eval_one.py`

**核心流程**：

```python
def eval_topic(topic, skip_ocr=False):
    # 1. OCR 题目图片
    # 2. 找到所有 scene HTML + solution.html
    # 3. 前置门控: Playwright 检查所有 scene 能否渲染
    #    - 任一 scene 渲染失败 → 总分0，结束
    # 4. 创建一个 workspace (runtime=visual-solver-eval)
    #    上传所有 scene HTML + solution.html + spec.json + 题目图片
    # 5. 维度1: 创建 session (agentName=accuracy-eval) → 发消息 → 读 dim1_result.txt
    # 6. 维度2: 创建 session (agentName=interaction-eval) → 发消息 → 读 dim2_result.txt
    # 7. 维度3: 创建 session (agentName=visual-eval) → 发消息 → 读 dim3_result.txt
    # 8. 维度4: 创建 session (agentName=pedagogy-eval) → 发消息 → 读 dim4_result.txt
    # 9. 汇总 → 几何平均算总分 → 输出报告
```

**spec.json 结构**（含图片和 solution）：

```json
{
  "topic": "g8vh4t11",
  "description": "OCR文本...",
  "image_file": "topic.png",
  "solution_file": "solution.html",
  "scenes": [
    {"scene_number": 1, "output_file": "scene1.html"},
    {"scene_number": 2, "output_file": "scene2.html"}
  ]
}
```

### 3. Agent 输出格式

每个 agent 将评分写入 `dim{N}_result.txt`，XML 格式（整个题目一个分数）：

```xml
<dim1_accuracy>
  <score>4</score>
  <reasoning>综合所有 scene 和 solution 的分析：图示中的几何体形状正确，
  解题步骤逻辑严谨，但 scene1 的角度标注有偏差，scene 划分覆盖了题目所需</reasoning>
</dim1_accuracy>
```

### 4. 最终报告格式

```xml
<evaluation_report>
  <topic>g8vh4t11</topic>
  <description>OCR文本</description>
  <render_check>
    <scene1 status="passed"/>
    <scene2 status="passed"/>
  </render_check>
  <dimensions>
    <dim1_accuracy score="4">理由...</dim1_accuracy>
    <dim2_interaction score="4.5">理由...</dim2_interaction>
    <dim3_visual score="4">理由...</dim3_visual>
    <dim4_pedagogy score="4">理由...</dim4_pedagogy>
  </dimensions>
  <total_score>4.12</total_score>
</evaluation_report>
```

## 关键文件路径

- 脚本: `/Users/bisz/Documents/EduIllustrate-teacher/eval_one.py`
- Runtime 目录: `/Users/bisz/Documents/test_oah_server2/source/runtimes/visual-solver-eval/`
- 数据目录: `/Users/bisz/Documents/EduIllustrate-teacher/output/Zipped_Items/`
- 图片目录: `/Users/bisz/Documents/EduIllustrate-teacher/data/Zipped_Items/`
- 模型配置: 复制 `visual-solver-eval/.openharness/models/`

## 实现步骤

1. 更新4个 agent prompt：评分单位从 per-scene 改为 per-topic，加入 solution.html 说明
2. 更新 eval_one.py：上传 solution.html，spec.json 加入 solution_file，解析 per-topic 分数
3. 同步 runtime 到 MinIO 并测试

## 验证

1. `python3 eval_one.py g8vh4t11 --skip-ocr` 测试含 solution 的题目
2. 确认前置门控渲染检查正确
3. 确认 solution.html 上传到 workspace 且 spec.json 包含 solution_file
4. 确认4个 agent 给出 per-topic 的整体分数（非 per-scene）
5. 确认最终报告格式正确，几何平均计算无误
