# Token 使用量追踪说明

## 修改内容

已对代码进行修改，实现对 `planner_model` 的细粒度 token 消耗追踪，**并确保程序重跑时 token 记录的正确性**。

## 核心特性

### ✅ 断点重跑保护
- **问题**: 程序中断后重跑，已生成的文件会被跳过，导致 token 文件缺失
- **解决**: 自动创建占位符 token 文件，标注为"前次运行生成"
- **保证**: timing.json 始终包含完整的 token 数据结构

## 新增功能

### 1. 场景大纲（Scene Outline）Token 追踪

**文件位置**: `src/core/explanation_planner.py:137-197`

**功能**:
- 在生成场景大纲前后记录 planner_model 的 token 使用量
- 计算差值得到场景大纲生成的实际 token 消耗
- 保存到文件: `output/<topic>/<topic>_scene_outline_tokens.json`

**输出格式**:
```json
{
  "input_tokens": 1234,
  "output_tokens": 5678,
  "total_tokens": 6912
}
```

### 2. 实现计划（Implementation Plan）Token 追踪

**文件位置**: `src/core/explanation_planner.py:194-284`

**功能**:
- 为每个场景的实现计划生成过程单独追踪 token 消耗
- 保存到文件: `output/<topic>/scene<N>/subplans/scene<N>_implementation_tokens.json`

**输出格式**:
```json
{
  "input_tokens": 2345,
  "output_tokens": 3456,
  "total_tokens": 5801
}
```

### 3. 合并到 timing.json

**文件位置**: `generate_explanation.py:1245-1286`

**功能**:
- 在最终的 timing.json 中新增 `planner_model_detailed` 字段
- 包含场景大纲和所有场景实现计划的 token 详情

**输出格式**:
```json
{
  "problem_index": 2,
  "topic": "problem_2_physics_g9",
  "total_time_seconds": 1976.34,
  "total_time_minutes": 32.94,
  "timestamp": "2026-03-14 08:38:11",
  "token_usage": {
    "total_tokens": 97162,
    "input_tokens": 44377,
    "output_tokens": 52785,
    "planner_model": {
      "input_tokens": 7140,
      "output_tokens": 22172,
      "total_tokens": 29312
    },
    "planner_model_detailed": {
      "scene_outline": {
        "input_tokens": 1234,
        "output_tokens": 5678,
        "total_tokens": 6912
      },
      "implementation_plans": {
        "scene_1": {
          "input_tokens": 2345,
          "output_tokens": 3456,
          "total_tokens": 5801
        },
        "scene_2": {
          "input_tokens": 2100,
          "output_tokens": 3200,
          "total_tokens": 5300
        },
        "scene_3": {
          "input_tokens": 1461,
          "output_tokens": 9838,
          "total_tokens": 11299
        }
      }
    },
    "scene_model": {
      "input_tokens": 37237,
      "output_tokens": 30613,
      "total_tokens": 67850
    },
    "helper_model": {
      "input_tokens": 0,
      "output_tokens": 0,
      "total_tokens": 0
    }
  },
  "scene_timings": {
    "scene_1": {...},
    "scene_2": {...},
    "scene_3": {...}
  }
}
```

## 数据分析示例

通过新的追踪机制，可以分析：

1. **场景大纲生成成本**
   - 直接查看 `planner_model_detailed.scene_outline`

2. **各场景实现计划成本**
   - 对比 `planner_model_detailed.implementation_plans` 下各场景的消耗
   - 识别哪些场景规划更复杂

3. **planner_model 总成本构成**
   - Scene Outline tokens
   - Scene 1 Implementation tokens
   - Scene 2 Implementation tokens
   - Scene 3 Implementation tokens
   - (应该等于 `planner_model.total_tokens`)

## 测试方法

### 运行测试脚本
```bash
python test_token_tracking.py [output_dir] [topic]

# 示例
python test_token_tracking.py output/exp_kimi-k25 problem_2_physics_g9
```

### 手动检查文件
```bash
# 查看场景大纲 tokens
cat output/<topic>/<topic>_scene_outline_tokens.json

# 查看场景1实现计划 tokens
cat output/<topic>/scene1/subplans/scene1_implementation_tokens.json

# 查看完整 timing.json
cat output/<topic>/timing.json
```

## 注意事项

1. **向后兼容**: 修改不影响现有代码逻辑，只是增加了额外的 token 追踪
2. **文件生成**: 只有在生成新的场景大纲或实现计划时才会创建对应的 token 文件
3. **重新运行保护**:
   - ✅ 如果场景大纲已存在但 token 文件缺失 → 自动创建占位符文件
   - ✅ 如果实现计划已存在但 token 文件缺失 → 自动创建占位符文件
   - ✅ 占位符文件包含 `note` 字段说明来源
4. **缺失处理**: timing.json 合并时会自动读取所有 token 文件（包括占位符）

### 占位符 Token 文件格式
当文件在之前运行中已生成，token 文件会使用占位符：
```json
{
  "input_tokens": 0,
  "output_tokens": 0,
  "total_tokens": 0,
  "note": "Scene outline was generated in a previous run, tokens not tracked"
}
```

或对于 Scene 2+ (使用 Scene 1 引用):
```json
{
  "input_tokens": 0,
  "output_tokens": 0,
  "total_tokens": 0,
  "note": "Scene uses Scene 1 as reference, no separate implementation plan generated"
}
```

## 重跑场景说明

### 场景 1: 完整的首次运行
- ✓ 场景大纲生成 → token 文件包含真实数据
- ✓ 实现计划生成 → token 文件包含真实数据
- ✓ timing.json 包含完整的真实 token 数据

### 场景 2: 场景大纲已存在，重新生成实现计划
- ✓ 场景大纲加载 → 创建占位符 token 文件（tokens=0）
- ✓ 实现计划生成 → token 文件包含真实数据
- ✓ timing.json 包含混合数据：大纲为占位符，计划为真实数据

### 场景 3: 所有计划文件都已存在
- ✓ 场景大纲加载 → 创建占位符 token 文件（如果不存在）
- ✓ 实现计划加载 → 创建占位符 token 文件（如果不存在）
- ✓ timing.json 包含所有占位符数据
- ⚠️ planner_model 总 tokens 可能为 0（没有新的 API 调用）
- ✓ 使用 `timing_data` 保留机制：如果新 token=0，保留旧数据

### 场景 4: 只进行渲染（plans 已存在）
- ✓ 无 planner_model 调用
- ✓ 仅 scene_model 用于代码生成
- ✓ timing.json 保留已有的 token_usage
- ✓ Token 文件保持不变

## 修改的文件

1. `src/core/explanation_planner.py` - 添加 token 追踪逻辑
2. `generate_explanation.py` - 在 timing.json 中合并详细 token 数据 + 重跑保护
3. `test_token_tracking.py` - 测试脚本（检查 token 文件）
4. `test_token_persistence.py` - 测试脚本（检查重跑场景）
5. `TOKEN_TRACKING_README.md` - 本说明文档

## 测试工具

### 1. 检查 token 文件是否存在
```bash
python test_token_tracking.py output/exp_kimi-k25 problem_2_physics_g9
```

### 2. 检查重跑场景的 token 持久化
```bash
# 查看当前状态
python test_token_persistence.py check output/exp_kimi-k25 problem_2_physics_g9

# 查看所有重跑场景说明
python test_token_persistence.py scenarios
```

### 3. 手动验证
```bash
# 查看场景大纲 tokens
cat output/<topic>/<topic>_scene_outline_tokens.json

# 查看场景1实现计划 tokens
cat output/<topic>/scene1/subplans/scene1_implementation_tokens.json

# 查看完整 timing.json
cat output/<topic>/timing.json | jq '.token_usage.planner_model_detailed'
```

## 代码修改要点

### 1. 场景大纲生成 (explanation_planner.py:137-197)
```python
# 记录生成前后的 token 使用量
tokens_before = self.planner_model.get_token_usage()
response_text = await self.planner_model(messages, ...)
tokens_after = self.planner_model.get_token_usage()

# 计算差值
outline_tokens = {
    "input_tokens": tokens_after["input_tokens"] - tokens_before["input_tokens"],
    "output_tokens": tokens_after["output_tokens"] - tokens_before["output_tokens"],
    "total_tokens": tokens_after["total_tokens"] - tokens_before["total_tokens"]
}

# 保存到文件
with open(token_file, "w") as f:
    json.dump(outline_tokens, f, indent=2)
```

### 2. 重跑保护 (generate_explanation.py:627-655)
```python
if os.path.exists(scene_outline_path):
    # 加载已存在的场景大纲
    with open(scene_outline_path, "r") as f:
        scene_outline = f.read()

    # 如果 token 文件不存在，创建占位符
    if not os.path.exists(outline_token_file):
        placeholder_tokens = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "note": "Scene outline was generated in a previous run, tokens not tracked"
        }
        with open(outline_token_file, "w") as f:
            json.dump(placeholder_tokens, f, indent=2)
```

### 3. 合并到 timing.json (generate_explanation.py:1245-1286)
```python
# 加载所有 token 文件（包括占位符）
planner_detailed_tokens = {
    "scene_outline": {},
    "implementation_plans": {}
}

# 加载场景大纲 tokens
if os.path.exists(outline_token_file):
    with open(outline_token_file, 'r') as f:
        planner_detailed_tokens["scene_outline"] = json.load(f)

# 加载所有场景的实现计划 tokens
for scene_dir in sorted(scene_dirs):
    token_file = os.path.join(..., f"scene{scene_num}_implementation_tokens.json")
    if os.path.exists(token_file):
        with open(token_file, 'r') as f:
            planner_detailed_tokens["implementation_plans"][f"scene_{scene_num}"] = json.load(f)

# 添加到 timing_data
timing_data["token_usage"]["planner_model_detailed"] = planner_detailed_tokens
```
