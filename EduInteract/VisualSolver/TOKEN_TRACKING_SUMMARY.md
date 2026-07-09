# Token 追踪功能实现总结

## 🎯 实现目标

分别记录 `planner_model` 的场景大纲（Scene Outline）和实现计划（Implementation Plans）的 token 消耗，并确保程序断开重跑时数据的完整性。

## ✅ 已完成的修改

### 1. 核心功能
- ✓ 场景大纲生成时的 token 追踪
- ✓ 每个场景实现计划生成时的 token 追踪
- ✓ 将详细 token 数据合并到 timing.json
- ✓ 重跑时的占位符机制（防止数据缺失）

### 2. 文件结构

#### 新增 token 文件位置：
```
output/<topic>/
├── <topic>_scene_outline_tokens.json          # 场景大纲 tokens
├── scene1/
│   └── subplans/
│       └── scene1_implementation_tokens.json  # 场景1实现计划 tokens
├── scene2/
│   └── subplans/
│       └── scene2_implementation_tokens.json  # 场景2实现计划 tokens
├── scene3/
│   └── subplans/
│       └── scene3_implementation_tokens.json  # 场景3实现计划 tokens
└── timing.json                                # 汇总所有 token 数据
```

#### timing.json 新增字段：
```json
{
  "token_usage": {
    "planner_model": {...},           // 原有：总计
    "planner_model_detailed": {       // 新增：详细分解
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
        "scene_2": {...},
        "scene_3": {...}
      }
    },
    "scene_model": {...},
    "helper_model": {...}
  }
}
```

### 3. 重跑保护机制

#### 问题场景：
程序中断后重跑，已生成的文件（scene outline / implementation plans）会被跳过加载，不会重新生成，导致对应的 token 文件缺失。

#### 解决方案：
自动检测并创建占位符 token 文件，包含以下信息：
```json
{
  "input_tokens": 0,
  "output_tokens": 0,
  "total_tokens": 0,
  "note": "Scene outline was generated in a previous run, tokens not tracked"
}
```

#### 保证结果：
- ✅ timing.json 始终包含完整的 `planner_model_detailed` 结构
- ✅ 不会因为文件缺失导致数据读取错误
- ✅ 通过 `note` 字段标识数据来源（新生成 vs 占位符）

## 📊 使用示例

### 分析 token 消耗
```bash
# 查看完整的 planner_model 详细数据
cat output/problem_2_physics_g9/timing.json | jq '.token_usage.planner_model_detailed'

# 输出：
{
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
    "scene_2": {...},
    "scene_3": {...}
  }
}
```

### 测试工具
```bash
# 1. 检查所有 token 文件是否存在
python test_token_tracking.py output/exp_kimi-k25 problem_2_physics_g9

# 2. 检查重跑场景的处理
python test_token_persistence.py check output/exp_kimi-k25 problem_2_physics_g9

# 3. 查看重跑场景说明
python test_token_persistence.py scenarios
```

## 🔍 数据分析价值

通过详细的 token 追踪，可以分析：

1. **规划阶段成本**
   - 场景大纲生成的 token 消耗
   - 各场景实现计划的 token 消耗对比

2. **优化方向**
   - 识别哪些场景的规划更复杂（token 更多）
   - 对比 planner_model 和 scene_model 的成本比例

3. **成本验证**
   - `planner_model.total_tokens` 应该等于：
     - `scene_outline.total_tokens`
     - \+ sum(所有 `implementation_plans[scene_N].total_tokens`)

## 📝 重要说明

### 首次运行 vs 重跑的差异

| 情况 | Scene Outline Tokens | Implementation Plan Tokens | 说明 |
|------|---------------------|---------------------------|------|
| **首次运行** | 真实值（API 调用） | 真实值（API 调用） | 完整记录实际消耗 |
| **重跑（已有 outline）** | 0（占位符） | 真实值（新生成） | Outline 未重新生成 |
| **重跑（全部已有）** | 0（占位符） | 0（占位符） | 全部从文件加载 |

### 注意事项
1. 占位符文件的 `note` 字段说明了 token=0 的原因
2. 如果需要重新统计真实 token，需删除对应的计划文件重新生成
3. timing.json 的 `planner_model.total_tokens` 反映的是**本次运行**的实际 API 调用量

## 📂 修改文件清单

1. ✅ `src/core/explanation_planner.py` - 添加 token 记录逻辑
2. ✅ `generate_explanation.py` - 重跑保护 + timing.json 合并
3. ✅ `test_token_tracking.py` - 测试工具（检查文件）
4. ✅ `test_token_persistence.py` - 测试工具（检查重跑）
5. ✅ `TOKEN_TRACKING_README.md` - 详细说明文档
6. ✅ `TOKEN_TRACKING_SUMMARY.md` - 本总结文档

## ✨ 后续可能的扩展

- [ ] 添加时间戳记录每个阶段的生成时间
- [ ] 生成可视化图表展示 token 分布
- [ ] 支持 CSV 导出用于批量分析
- [ ] 添加成本估算（根据 token 价格）
