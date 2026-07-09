#!/usr/bin/env python3
"""
从 EduInteract 的实验输出目录提取 SFT 训练数据（单轮 user/assistant 对话格式）。

与原版 extract_sft_data.py 不同，本脚本直接从 output 目录的文件组织数据，
而非从 agentic trace 中提取。输出格式为 user/assistant 单轮对话：
  - user: 由 prompts_raw 中的 prompt 模板填充得到（含图片的多模态 content）
  - assistant: 对应的输出文件内容

三类数据：
  1. scene_plan   → user=_prompt_scene_plan(description=题目描述+参考答案),  assistant=scene_outline.txt
  2. scene_design → user=_prompt_scene_design_and_implementation(scene_number, description, scene_outline),
                    assistant=implementation_plan.txt
  3. code_gen     → user=_prompt_code_generation(scene_number, description, scene_outline, scene_implementation),
                    assistant=scene code (.html)

description 的构建方式与 generate_explanation.py 中 _build_description 一致：
  - 文本部分: prob["question"] + format_answer 参考答案
  - 图片部分: prob["img"] (base64) 作为 image_url 插入 user message

过滤条件: results JSON 中 total_score > 4 且 scene 的 render_check 为 passed

用法:
  source .venv/bin/activate
  python extract_sft_data_single_turn.py
"""

import base64
import json
import os
import re
import sys
from collections import defaultdict

# ============================================================
# 配置
# ============================================================

BASE_DIR = "/inspire/qb-ilm/project/ai4education/bishuzhen-CZXS24220022/edu_interact/EduInteract/output"
DATA_DIR = "/inspire/qb-ilm/project/ai4education/bishuzhen-CZXS24220022/edu_interact/EduInteract/data"
OUTPUT_DIR = "/inspire/qb-ilm/project/ai4education/bishuzhen-CZXS24220022/edu_interact/EduInteract/output/sft_data_single_turn"
SCORE_THRESHOLD = 4.0

# 题库文件路径
BENCHMARK_FILE = os.path.join(DATA_DIR, "benchmark", "benchmark.json")       # 5 模型共用
K12_VISTA_FILE = os.path.join(DATA_DIR, "k12_vista", "K12_Vista.jsonl")     # K12 Vista 四科

MODEL_CONFIGS = {
    "Gemini-3.1-Pro": {
        "results_file": "Gemini-3.1-Pro.json",
        "exp_dir": "exp_Gemini-3.1-Pro",
        "problem_bank": "benchmark",
    },
    "Qwen3.5-122B-A10B": {
        "results_file": "Qwen3.5-122B-A10B.json",
        "exp_dir": "exp_qwen35_122b",
        "problem_bank": "benchmark",
    },
    "Qwen3.5-397B-A17B-FP8": {
        "results_file": "Qwen3.5-397B-A17B-FP8.json",
        "exp_dir": "exp_qwen35_397b",
        "problem_bank": "benchmark",
    },
    "Qwen3.6-27B": {
        "results_file": "Qwen3.6-27B.json",
        "exp_dir": "exp_qwen36_27b",
        "problem_bank": "benchmark",
    },
    "Kimi-K2.6": {
        "results_file": "Kimi-K2.6.json",
        "exp_dir": "exp_kimik26",
        "problem_bank": "benchmark",
    },
    # K12 Vista 四科（trace 在各自目录，topic_name 含学科后缀）
    "Kimi-K2.6-k12-math-g12": {
        "results_file": "Kimi-K2.6-k12-vista.json",
        "exp_dir": "k12_vista_math_g12",
        "topic_filter": "math_g12",
        "problem_bank": "k12_vista",
    },
    "Kimi-K2.6-k12-math-g9": {
        "results_file": "Kimi-K2.6-k12-vista.json",
        "exp_dir": "k12_vista_math_g9",
        "topic_filter": "math_g9",
        "problem_bank": "k12_vista",
    },
    "Kimi-K2.6-k12-physics-g12": {
        "results_file": "Kimi-K2.6-k12-vista.json",
        "exp_dir": "k12_vista_physics_g12",
        "topic_filter": "physics_g12",
        "problem_bank": "k12_vista",
    },
    "Kimi-K2.6-k12-physics-g9": {
        "results_file": "Kimi-K2.6-k12-vista.json",
        "exp_dir": "k12_vista_physics_g9",
        "topic_filter": "physics_g9",
        "problem_bank": "k12_vista",
    },
}

# ============================================================
# 导入 prompt 模板
# ============================================================

PROMPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "VisualSolver", "visual_solver", "task_generator"
)
sys.path.insert(0, os.path.dirname(PROMPTS_DIR))

from task_generator.prompts_raw import (
    _prompt_scene_plan,
    _prompt_scene_design_and_implementation,
    _prompt_code_generation,
)

# ============================================================
# Step 1: 加载题库
# ============================================================


def load_problem_bank(bank_name):
    """加载题库，返回 dict: (index, subject) → {"question": ..., "img": ..., "format_answer": ...}

    Args:
        bank_name: "benchmark" 或 "k12_vista"
    """
    problems = {}

    if bank_name == "benchmark":
        with open(BENCHMARK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            idx = item.get("index", 0)
            subject = item.get("subject", "")
            problems[(idx, subject)] = {
                "question": item.get("question", ""),
                "img": item.get("img", ""),
                "format_answer": item.get("format_answer"),
            }

    elif bank_name == "k12_vista":
        with open(K12_VISTA_FILE, "r", encoding="utf-8") as f:
            for line in f:
                item = json.loads(line)
                idx = item.get("index", 0)
                subject = item.get("subject", "")
                problems[(idx, subject)] = {
                    "question": item.get("question", ""),
                    "img": item.get("img", ""),
                    "format_answer": item.get("format_answer"),
                }

    return problems


def build_description_text(prob_info):
    """构建 description 文本部分（与 generate_explanation.py 中 _build_description 一致）。

    包含题目文本 + 参考答案。
    """
    problem_text = prob_info["question"]
    lines = [problem_text]

    format_answer = prob_info.get("format_answer")
    if format_answer:
        lines += [
            "",
            "Reference answer (for correctness checking only; do NOT copy verbatim):",
            json.dumps(format_answer, ensure_ascii=False, indent=2),
        ]

    return "\n".join(lines)


def build_user_content(prompt_text, prob_info):
    """构建 user message 的多模态 content。

    统一返回 list 格式: [{"type": "text", "text": ...}, (可选) {"type": "image_url", ...}]
    - text: prompt 全文（将所有 <image> 标记去除）
    - image_url: 题目配图（base64 data URI），有图时才附加
    """
    img_b64 = prob_info.get("img", "")

    # 去掉所有 <image> 标记，合并为单个 text
    clean_text = prompt_text.replace("<image>", "").strip()

    content = [
        {"type": "text", "text": clean_text},
    ]

    if img_b64:
        image_url = f"data:image/jpeg;base64,{img_b64}"
        content.append({"type": "image_url", "image_url": image_url})
    return content


# ============================================================
# Step 2: 收集 qualified (model, topic_name) 对及其 scenes
# ============================================================


def get_qualified_problems():
    """从 results JSON 中筛选 total_score > 4 的 (model, topic_name) 对。"""
    qualified = {}  # (model, topic_name) → {"total_score": float, "scenes": [...]}

    results_cache = {}

    for model, cfg in MODEL_CONFIGS.items():
        results_path = os.path.join(BASE_DIR, "results", cfg["results_file"])
        if not os.path.exists(results_path):
            print(f"  [WARN] {results_path} not found, skipping {model}")
            continue

        if results_path not in results_cache:
            results_cache[results_path] = json.load(open(results_path, encoding="utf-8"))
        data = results_cache[results_path]
        topics = data.get("topics", [])

        topic_filter = cfg.get("topic_filter")

        for topic in topics:
            topic_name = topic.get("topic", "")
            evaluation = topic.get("evaluation", {})
            total_score = evaluation.get("total_score", 0)

            if topic_filter and topic_filter not in topic_name:
                continue

            if total_score > SCORE_THRESHOLD:
                render_check = evaluation.get("render_check", {})
                passed_scenes = sorted(
                    [k for k, v in render_check.items() if v == "passed"]
                )

                qualified[(model, topic_name)] = {
                    "total_score": total_score,
                    "scenes": passed_scenes,
                }

    return qualified


# ============================================================
# Step 3: 从输出目录读取文件并组织训练数据
# ============================================================


def parse_topic_to_index_subject(topic_name):
    """从 topic_name 解析 (index, subject)。

    例: "problem_0_physics_g9" → (0, "physics-g9")
        "problem_6775_math_g12" → (6775, "math-g12")
    """
    # topic_name 格式: problem_{index}_{subject_with_underscore}
    # subject 可能含多个下划线: physics_g9 → physics-g9
    match = re.match(r'problem_(\d+)_(.+)', topic_name)
    if not match:
        return None, None
    idx = int(match.group(1))
    subject = match.group(2).replace("_", "-")
    return idx, subject


def extract_scene_outline_block(outline_text, scene_number):
    """从 scene_outline.txt 中提取 <SCENE_k> 块的内容。"""
    tag = f"SCENE_{scene_number}"
    pattern = rf'<{tag}>(.*?)</{tag}>'
    match = re.search(pattern, outline_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def build_sft_record(user_content, assistant_content, metadata):
    """构建单条 SFT 训练记录（user/assistant 单轮对话格式）。

    user_content 可以是 str（纯文本）或 list（多模态 content）。
    """
    return {
        "messages": [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ],
        "metadata": metadata,
    }


# ============================================================
# Step 4: 主流程
# ============================================================


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # --- 加载题库 ---
    print("=" * 60)
    print("Step 0: 加载题库")
    print("=" * 60)

    banks = {}
    for bank_name in ("benchmark", "k12_vista"):
        banks[bank_name] = load_problem_bank(bank_name)
        print(f"  {bank_name}: {len(banks[bank_name])} problems")

    # --- 收集 qualified problems ---
    print()
    print("=" * 60)
    print("Step 1: 收集 qualified problems (total_score > 4)")
    print("=" * 60)

    qualified = get_qualified_problems()
    print(f"  Qualified (model, topic_name) pairs: {len(qualified)}")

    by_model = defaultdict(int)
    for (model, _), info in qualified.items():
        by_model[model] += 1
    for model, count in sorted(by_model.items()):
        print(f"    {model}: {count} problems")

    # --- 组织训练数据 ---
    print()
    print("=" * 60)
    print("Step 2: 从输出目录组织训练数据（user/assistant 单轮对话）")
    print("=" * 60)

    stats = {"scene_plan": 0, "scene_design": 0, "code_gen": 0, "skipped": 0, "errors": 0}
    output_files = {
        "scene_plan": open(os.path.join(OUTPUT_DIR, "sft_scene_plan.jsonl"), "w", encoding="utf-8"),
        "scene_design": open(os.path.join(OUTPUT_DIR, "sft_scene_design.jsonl"), "w", encoding="utf-8"),
        "code_gen": open(os.path.join(OUTPUT_DIR, "sft_code_gen.jsonl"), "w", encoding="utf-8"),
    }

    total_qualified = len(qualified)
    processed = 0

    for (model, topic_name), info in sorted(qualified.items()):
        processed += 1
        cfg = MODEL_CONFIGS[model]
        problem_dir = os.path.join(BASE_DIR, cfg["exp_dir"], topic_name)

        if not os.path.isdir(problem_dir):
            print(f"  [WARN] {problem_dir} not found, skipping")
            stats["skipped"] += 1
            continue

        if processed % 50 == 0 or processed == total_qualified:
            print(f"  Progress: {processed}/{total_qualified}")

        # --- 从题库查找该题目的 description 和图片 ---
        idx, subject = parse_topic_to_index_subject(topic_name)
        bank_name = cfg["problem_bank"]
        prob_info = banks.get(bank_name, {}).get((idx, subject))

        if prob_info is None:
            # fallback: 尝试不同的 subject 格式
            # 有些题库用 "physics-g9"，有些用 "physics_g9"
            for alt_subj in [subject, subject.replace("-", "_"), subject.replace("-", " ")]:
                prob_info = banks.get(bank_name, {}).get((idx, alt_subj))
                if prob_info is not None:
                    break

        if prob_info is None:
            print(f"  [WARN] Problem not found in bank for topic={topic_name} (idx={idx}, subject={subject}), skipping")
            stats["skipped"] += 1
            continue

        # 构建 description 文本
        description_text = build_description_text(prob_info)

        # 如果有图片，追加图片说明（与 generate_explanation.py 一致）
        if prob_info.get("img"):
            description_text += "\n(Note: The attached image is the original diagram illustrating the problem setup.)"

        # --- 读取 scene_outline.txt ---
        outline_files = [f for f in os.listdir(problem_dir) if f.endswith("_scene_outline.txt")]
        if not outline_files:
            stats["skipped"] += 1
            continue
        outline_path = os.path.join(problem_dir, outline_files[0])

        try:
            with open(outline_path, "r", encoding="utf-8") as f:
                outline_text = f.read()
        except Exception as e:
            print(f"  [WARN] Failed to read {outline_path}: {e}")
            stats["errors"] += 1
            continue

        # ----------------------------------------------------------
        # 1. scene_plan: user=_prompt_scene_plan(description), assistant=完整 outline
        # ----------------------------------------------------------
        try:
            user_prompt_plan = _prompt_scene_plan.format(description=description_text)
            user_content = build_user_content(user_prompt_plan, prob_info)
            record = build_sft_record(
                user_content,
                outline_text,
                {
                    "model": model,
                    "topic_name": topic_name,
                    "type": "scene_plan",
                    "total_score": info["total_score"],
                },
            )
            output_files["scene_plan"].write(json.dumps(record, ensure_ascii=False) + "\n")
            stats["scene_plan"] += 1
        except Exception as e:
            print(f"  [WARN] scene_plan failed for {topic_name}: {e}")
            stats["errors"] += 1

        # ----------------------------------------------------------
        # 2. scene_design & code_gen: 按 scene 逐个处理
        # ----------------------------------------------------------
        scenes = info["scenes"]  # e.g. ["scene1", "scene2"]

        for scene in scenes:
            scene_num = int(scene.replace("scene", ""))  # "scene1" → 1
            scene_dir = os.path.join(problem_dir, scene)

            if not os.path.isdir(scene_dir):
                continue

            # 提取 <SCENE_k> 块作为 scene_outline
            scene_outline = extract_scene_outline_block(outline_text, scene_num)
            if scene_outline is None:
                # 如果提取不到，使用整个 outline 作为 fallback
                scene_outline = outline_text

            # --- 2a. scene_design ---
            # 找到 implementation_plan 文件
            impl_files = [f for f in os.listdir(scene_dir)
                          if f.endswith("_implementation_plan.txt")]
            if not impl_files:
                continue

            impl_path = os.path.join(scene_dir, impl_files[0])
            try:
                with open(impl_path, "r", encoding="utf-8") as f:
                    impl_text = f.read()
            except Exception as e:
                print(f"  [WARN] Failed to read {impl_path}: {e}")
                stats["errors"] += 1
                continue

            try:
                user_prompt_design = _prompt_scene_design_and_implementation.format(
                    scene_number=scene_num,
                    description=description_text,
                    scene_outline=scene_outline,
                )
                user_content = build_user_content(user_prompt_design, prob_info)
                record = build_sft_record(
                    user_content,
                    impl_text,
                    {
                        "model": model,
                        "topic_name": topic_name,
                        "type": "scene_design",
                        "scene": scene,
                        "total_score": info["total_score"],
                    },
                )
                output_files["scene_design"].write(json.dumps(record, ensure_ascii=False) + "\n")
                stats["scene_design"] += 1
            except Exception as e:
                print(f"  [WARN] scene_design failed for {topic_name}/{scene}: {e}")
                stats["errors"] += 1
                continue  # impl_text 不可用，跳过 code_gen

            # --- 2b. code_gen ---
            # 找到成功渲染的代码文件
            code_dir = os.path.join(scene_dir, "code")
            if not os.path.isdir(code_dir):
                continue

            # 检查 succ_rendered.txt 确认渲染成功
            succ_file = os.path.join(scene_dir, "succ_rendered.txt")
            if not os.path.exists(succ_file):
                continue

            # 读取 succ_rendered.txt 确定成功版本
            try:
                with open(succ_file, "r", encoding="utf-8") as f:
                    succ_versions = [line.strip() for line in f if line.strip()]
            except Exception:
                succ_versions = ["v0"]

            # 找到对应版本的代码文件
            for ver in succ_versions:
                # 文件名格式: problem_XXX_sceneN_v0.html
                code_files = [f for f in os.listdir(code_dir)
                              if f.endswith(f"_{ver}.html")]
                if code_files:
                    code_path = os.path.join(code_dir, code_files[0])
                    try:
                        with open(code_path, "r", encoding="utf-8") as f:
                            code_text = f.read()

                        user_prompt_code = _prompt_code_generation.format(
                            scene_number=scene_num,
                            description=description_text,
                            scene_outline=scene_outline,
                            scene_implementation=impl_text,
                        )
                        user_content = build_user_content(user_prompt_code, prob_info)
                        record = build_sft_record(
                            user_content,
                            code_text,
                            {
                                "model": model,
                                "topic_name": topic_name,
                                "type": "code_gen",
                                "scene": scene,
                                "version": ver,
                                "total_score": info["total_score"],
                            },
                        )
                        output_files["code_gen"].write(json.dumps(record, ensure_ascii=False) + "\n")
                        stats["code_gen"] += 1
                    except Exception as e:
                        print(f"  [WARN] code_gen failed for {topic_name}/{scene}/{ver}: {e}")
                        stats["errors"] += 1
                    break  # 只取第一个成功版本

    for f in output_files.values():
        f.close()

    print()
    print("=" * 60)
    print("Step 3: 结果统计")
    print("=" * 60)
    print(f"  scene_plan:   {stats['scene_plan']} 条")
    print(f"  scene_design: {stats['scene_design']} 条")
    print(f"  code_gen:     {stats['code_gen']} 条")
    print(f"  skipped:      {stats['skipped']}")
    print(f"  errors:       {stats['errors']}")

    # ----------------------------------------------------------
    # Step 4: 合并三个文件为一个
    # ----------------------------------------------------------
    print()
    print("=" * 60)
    print("Step 4: 合并三个 JSONL 为一个文件")
    print("=" * 60)

    merged_path = os.path.join(OUTPUT_DIR, "sft_all.jsonl")
    part_files = [
        os.path.join(OUTPUT_DIR, "sft_scene_plan.jsonl"),
        os.path.join(OUTPUT_DIR, "sft_scene_design.jsonl"),
        os.path.join(OUTPUT_DIR, "sft_code_gen.jsonl"),
    ]

    # 先收集所有行，再随机 shuffle
    all_lines = []
    for pf in part_files:
        if not os.path.exists(pf):
            continue
        with open(pf, "r", encoding="utf-8") as in_f:
            for line in in_f:
                all_lines.append(line)

    import random
    random.shuffle(all_lines)

    total_merged = 0
    with open(merged_path, "w", encoding="utf-8") as out_f:
        for line in all_lines:
            out_f.write(line)
            total_merged += 1

    print(f"  合并写入: {merged_path}")
    print(f"  总条数: {total_merged} (随机 shuffled)")

    # 按 type 统计
    type_counts = defaultdict(int)
    with open(merged_path, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            t = rec.get("metadata", {}).get("type", "unknown")
            type_counts[t] += 1
    for t, c in sorted(type_counts.items()):
        print(f"    {t}: {c}")

    print()
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"  sft_scene_plan.jsonl   (user: _prompt_scene_plan, assistant: scene_outline.txt)")
    print(f"  sft_scene_design.jsonl (user: _prompt_scene_design_and_implementation, assistant: implementation_plan.txt)")
    print(f"  sft_code_gen.jsonl     (user: _prompt_code_generation, assistant: .html code)")
    print(f"  sft_all.jsonl          (以上三者合并)")


if __name__ == "__main__":
    main()
