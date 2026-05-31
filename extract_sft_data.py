#!/usr/bin/env python3
"""
从 EduInteract 的 agentic traces 提取 SFT 训练数据。

过滤条件: results JSON 中 total_score > 4
输出格式: OpenAI messages 格式的 JSONL，按 agent 类型分三个文件
  - sft_outline.jsonl
  - sft_plan.jsonl
  - sft_code.jsonl

用法:
  source .venv/bin/activate
  python extract_sft_data.py
"""

import json
import os
import re
import sys
from collections import defaultdict

# ============================================================
# 配置
# ============================================================

BASE_DIR = "/inspire/qb-ilm/project/ai4education/bishuzhen-CZXS24220022/edu_interact/EduInteract/output"
OUTPUT_DIR = "/inspire/qb-ilm/project/ai4education/bishuzhen-CZXS24220022/edu_interact/EduInteract/output/sft_data"
SCORE_THRESHOLD = 4.0

MODEL_CONFIGS = {
    "Gemini-3.1-Pro": {
        "results_file": "Gemini-3.1-Pro.json",
        "exp_dir": "exp_Gemini-3.1-Pro",
        "trace_prefix": "Gemini-3_1-Pro",
    },
    "Qwen3.5-122B-A10B": {
        "results_file": "Qwen3.5-122B-A10B.json",
        "exp_dir": "exp_qwen35_122b",
        "trace_prefix": "Qwen3_5-122B-A10B",
    },
    "Qwen3.5-397B-A17B-FP8": {
        "results_file": "Qwen3.5-397B-A17B-FP8.json",
        "exp_dir": "exp_qwen35_397b",
        "trace_prefix": "Qwen3_5-397B-A17B-FP8",
    },
    "Qwen3.6-27B": {
        "results_file": "Qwen3.6-27B.json",
        "exp_dir": "exp_qwen36_27b",
        "trace_prefix": "Qwen3_6-27B",
    },
    "Kimi-K2.6": {
        "results_file": "Kimi-K2.6.json",
        "exp_dir": "exp_kimik26",
        "trace_prefix": "kimi-k26",
    },
}

# ============================================================
# Step 1: 收集 qualified (model, problem_id) 对
# ============================================================


def get_qualified_problems():
    """从 results JSON 中筛选 total_score > 4 的 (model, problem_id) 对。"""
    qualified = {}  # (model, problem_id) → {"total_score": float, "scenes": [...]}

    for model, cfg in MODEL_CONFIGS.items():
        results_path = os.path.join(BASE_DIR, "results", cfg["results_file"])
        if not os.path.exists(results_path):
            print(f"  [WARN] {results_path} not found, skipping {model}")
            continue

        data = json.load(open(results_path, encoding="utf-8"))
        topics = data.get("topics", [])

        for topic in topics:
            topic_name = topic.get("topic", "")
            evaluation = topic.get("evaluation", {})
            total_score = evaluation.get("total_score", 0)

            if total_score > SCORE_THRESHOLD:
                # topic_name: "problem_0_physics_g9" → problem_id = 0
                parts = topic_name.split("_")
                if len(parts) >= 2 and parts[1].isdigit():
                    problem_id = int(parts[1])
                else:
                    continue

                # 收集通过了 render_check 的 scenes
                render_check = evaluation.get("render_check", {})
                passed_scenes = sorted(
                    [k for k, v in render_check.items() if v == "passed"]
                )

                qualified[(model, problem_id)] = {
                    "total_score": total_score,
                    "scenes": passed_scenes,
                    "topic_name": topic_name,
                }

    return qualified


# ============================================================
# Step 2: 从 trace 提取完整 agentic 对话
# ============================================================


def _content_to_text(content):
    """将 content (str 或 list) 转为纯文本，保留 base64 图片。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if not isinstance(p, dict):
                continue
            ptype = p.get("type", "")
            if ptype == "text":
                parts.append(p.get("text", ""))
            elif ptype == "image-data":
                # 保留 base64 图片，转为 data URI
                data = p.get("data", "")
                media_type = p.get("mediaType", "image/png")
                parts.append(f"data:{media_type};base64,{data}")
            elif ptype == "tool-call":
                # tool-call 转为可读文本格式
                tool_name = p.get("toolName", "")
                tool_input = p.get("input", {})
                args_str = json.dumps(tool_input, ensure_ascii=False)
                parts.append(f'Tool Call: {tool_name}({args_str})')
            elif ptype == "tool-result":
                # tool-result 内容
                result = p.get("output", p.get("result", ""))
                if isinstance(result, dict):
                    # 提取有意义的输出
                    output = result.get("output", result)
                    if isinstance(output, dict):
                        value = output.get("value", "")
                        if isinstance(value, str):
                            parts.append(value)
                        else:
                            parts.append(json.dumps(value, ensure_ascii=False)[:2000])
                    else:
                        parts.append(json.dumps(output, ensure_ascii=False)[:2000])
                elif isinstance(result, str):
                    parts.append(result)
                else:
                    parts.append(json.dumps(result, ensure_ascii=False)[:2000])
        return "\n".join(parts)
    return str(content)


def _convert_content_part(p):
    """将 trace 中的单个 content part 转为 SFT 格式列表。

    返回 list[dict]，因为一个 content part（如 tool-result）可能包含
    多个 SFT 部分（文本 + 图片），需要拆开才能让模型的视觉模块处理图片。
    """
    if not isinstance(p, dict):
        return []
    ptype = p.get("type", "")

    if ptype == "text":
        return [{"type": "text", "text": p.get("text", "")}]

    elif ptype == "image-data":
        return [{
            "type": "image_url",
            "image_url": {
                "url": f"data:{p.get('mediaType', 'image/png')};base64,{p.get('data', '')}"
            }
        }]

    elif ptype == "tool-call":
        tool_name = p.get("toolName", "")
        tool_input = p.get("input", {})
        args_str = json.dumps(tool_input, ensure_ascii=False)
        return [{"type": "text", "text": f"[Tool Call] {tool_name}\nArguments: {args_str}"}]

    elif ptype == "tool-result":
        result = p.get("output", "")
        parts = [{"type": "text", "text": "[Tool Result]"}]

        if isinstance(result, dict):
            inner = result.get("output", result)
            if isinstance(inner, dict):
                if "errorMessage" in inner:
                    parts.append({"type": "text", "text": f"Error: {inner['errorMessage']}"})
                else:
                    value = inner.get("value", "")
                    if isinstance(value, str):
                        # 检查是否是 base64 图片 data URI
                        if value.startswith("data:image"):
                            parts.append({
                                "type": "image_url",
                                "image_url": {"url": value}
                            })
                        else:
                            parts.append({"type": "text", "text": value})
                    elif isinstance(value, list):
                        for vp in value:
                            if not isinstance(vp, dict):
                                continue
                            vt = vp.get("type", "")
                            if vt == "text":
                                parts.append({"type": "text", "text": vp.get("text", "")})
                            elif vt == "image-data":
                                parts.append({
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{vp.get('mediaType', 'image/png')};base64,{vp.get('data', '')}"
                                    }
                                })
                    else:
                        parts.append({"type": "text", "text": json.dumps(value, ensure_ascii=False)[:2000]})
            else:
                parts.append({"type": "text", "text": str(inner)[:2000]})
        elif isinstance(result, str):
            if result.startswith("data:image"):
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": result}
                })
            else:
                parts.append({"type": "text", "text": result})
        else:
            parts.append({"type": "text", "text": json.dumps(result, ensure_ascii=False)[:2000]})

        return parts

    return []


def _convert_message(msg):
    """将 trace 中的单条 message 转为 SFT 格式。"""
    role = msg.get("role", "")
    content = msg.get("content", "")

    if isinstance(content, list):
        sft_parts = []
        for p in content:
            converted = _convert_content_part(p)
            # _convert_content_part 现在返回 list[dict]
            sft_parts.extend(converted)
        if not sft_parts:
            return None
        if len(sft_parts) == 1 and sft_parts[0].get("type") == "text":
            return {"role": role, "content": sft_parts[0]["text"]}
        return {"role": role, "content": sft_parts}

    if not content:
        return None
    return {"role": role, "content": str(content)}


def _extract_assistant_reply(step):
    """从 model_call step 的 output.response 中提取 assistant 回复。

    Trace 使用 Vercel AI SDK 格式:
      output.response.content = [content parts]  (含 text / tool-call / tool-result)
      output.response.text = 纯文本摘要
      output.response.toolCalls = [tool call objects]
      output.response.toolResults = [tool result objects]
    """
    resp = step.get("output", {}).get("response", {})
    content_parts = resp.get("content", [])

    if not content_parts:
        # 退而用 text 字段
        text = resp.get("text", "")
        if text:
            return {"role": "assistant", "content": text}
        return None

    return {"role": "assistant", "content": content_parts}


def extract_conversation_from_trace(trace_path):
    """从 trace JSON 文件提取完整的 agentic 对话。

    策略: 遍历所有 model_call steps，逐步构建完整对话。
    每个 model_call 的 input.request.messages 是到该步为止的完整对话历史，
    output.response 是该步的 assistant 回复。
    取最后一个 model_call 的 messages + 最后一个 assistant 回复。
    """
    if not os.path.exists(trace_path):
        return None

    try:
        data = json.load(open(trace_path, encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"    [WARN] Failed to parse {trace_path}: {e}")
        return None

    if data.get("status") != "completed":
        return None

    model_call_steps = [s for s in data.get("steps", []) if s.get("stepType") == "model_call"]

    if not model_call_steps:
        return None

    last_step = model_call_steps[-1]

    # 完整对话历史 (input.request.messages 已包含之前所有轮次)
    req = last_step.get("input", {}).get("request", {})
    raw_messages = req.get("messages", [])

    # 最后一次 assistant 回复 (Vercel AI SDK 格式)
    last_assistant = _extract_assistant_reply(last_step)

    # 合并: 历史 + 最后回复
    all_raw = list(raw_messages)
    if last_assistant is not None:
        all_raw.append(last_assistant)

    # 转换为 SFT 格式
    sft_messages = []
    for msg in all_raw:
        sft_msg = _convert_message(msg)
        if sft_msg is not None:
            sft_messages.append(sft_msg)

    # 确保以 system 开头
    if not sft_messages or sft_messages[0].get("role") != "system":
        return None

    # 基本质量检查: 至少要有 system + user + assistant
    has_user = any(m.get("role") == "user" for m in sft_messages)
    has_assistant = any(m.get("role") == "assistant" for m in sft_messages)
    if not (has_user and has_assistant):
        return None

    return {"messages": sft_messages}


# ============================================================
# Step 3: 主流程
# ============================================================


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("Step 1: 收集 qualified problems (total_score > 4)")
    print("=" * 60)

    qualified = get_qualified_problems()
    print(f"  Qualified (model, problem_id) pairs: {len(qualified)}")

    # 按 model 统计
    by_model = defaultdict(int)
    for (model, _), info in qualified.items():
        by_model[model] += 1
    for model, count in sorted(by_model.items()):
        print(f"    {model}: {count} problems")

    print()
    print("=" * 60)
    print("Step 2: 提取 agentic 对话")
    print("=" * 60)

    stats = {"outline": 0, "plan": 0, "code": 0, "skipped": 0, "errors": 0}
    output_files = {
        "outline": open(os.path.join(OUTPUT_DIR, "sft_outline.jsonl"), "w", encoding="utf-8"),
        "plan": open(os.path.join(OUTPUT_DIR, "sft_plan.jsonl"), "w", encoding="utf-8"),
        "code": open(os.path.join(OUTPUT_DIR, "sft_code.jsonl"), "w", encoding="utf-8"),
    }

    total_qualified = len(qualified)
    processed = 0

    for (model, problem_id), info in sorted(qualified.items()):
        processed += 1
        cfg = MODEL_CONFIGS[model]
        trace_dir = os.path.join(BASE_DIR, cfg["exp_dir"], "traces")
        prefix = cfg["trace_prefix"]

        if not os.path.isdir(trace_dir):
            print(f"  [WARN] {trace_dir} not found, skipping")
            stats["skipped"] += 1
            continue

        if processed % 50 == 0 or processed == total_qualified:
            print(f"  Progress: {processed}/{total_qualified}")

        scenes = info["scenes"]  # e.g. ["scene1", "scene2"]

        # --- outline trace ---
        outline_file = os.path.join(trace_dir, f"problem_{problem_id}_{prefix}_outline.json")
        conv = extract_conversation_from_trace(outline_file)
        if conv is not None:
            conv["metadata"] = {
                "model": model,
                "problem_id": problem_id,
                "agent_type": "outline",
                "total_score": info["total_score"],
                "topic_name": info["topic_name"],
            }
            output_files["outline"].write(json.dumps(conv, ensure_ascii=False) + "\n")
            stats["outline"] += 1

        # --- scene plan + code traces ---
        for scene in scenes:
            scene_num = scene.replace("scene", "")  # "scene1" → "1"

            # plan
            plan_file = os.path.join(trace_dir, f"problem_{problem_id}_{prefix}_scene{scene_num}_plan.json")
            conv = extract_conversation_from_trace(plan_file)
            if conv is not None:
                conv["metadata"] = {
                    "model": model,
                    "problem_id": problem_id,
                    "agent_type": "plan",
                    "scene": scene,
                    "total_score": info["total_score"],
                    "topic_name": info["topic_name"],
                }
                output_files["plan"].write(json.dumps(conv, ensure_ascii=False) + "\n")
                stats["plan"] += 1

            # code
            code_file = os.path.join(trace_dir, f"problem_{problem_id}_{prefix}_scene{scene_num}_code.json")
            conv = extract_conversation_from_trace(code_file)
            if conv is not None:
                conv["metadata"] = {
                    "model": model,
                    "problem_id": problem_id,
                    "agent_type": "code",
                    "scene": scene,
                    "total_score": info["total_score"],
                    "topic_name": info["topic_name"],
                }
                output_files["code"].write(json.dumps(conv, ensure_ascii=False) + "\n")
                stats["code"] += 1

    for f in output_files.values():
        f.close()

    print()
    print("=" * 60)
    print("Step 3: 结果统计")
    print("=" * 60)
    print(f"  outline: {stats['outline']} 条")
    print(f"  plan:    {stats['plan']} 条")
    print(f"  code:    {stats['code']} 条")
    print(f"  skipped: {stats['skipped']}")
    print(f"  errors:  {stats['errors']}")
    print()
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"  sft_outline.jsonl")
    print(f"  sft_plan.jsonl")
    print(f"  sft_code.jsonl")


if __name__ == "__main__":
    main()
