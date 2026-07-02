#!/usr/bin/env python3
"""
从 evaluate_{subject} 目录和 k12_vista_{subject} 目录重建 Kimi-K2.6-k12-vista.json。

评测目录结构:
  output/evaluate_{subject}/problem_XXX_{subject}/dim{1-5}_result.txt
  每个 dim 文件含 <score>N</score>

实验目录结构:
  output/k12_vista_{subject}/problem_XXX_{subject}/sceneN/succ_rendered.txt
  存在即 render_check = "passed"

输出格式与现有 Kimi-K2.6-k12-vista.json 一致:
  {"topics": [{"topic": "problem_XXX_subject", "evaluation": {...}}]}

用法:
  python build_k12_vista_results.py
  python build_k12_vista_results.py --output /path/to/output.json
"""

import argparse
import json
import os
import re
from collections import Counter


BASE_DIR = "/inspire/qb-ilm/project/ai4education/bishuzhen-CZXS24220022/edu_interact/EduInteract/output"

SUBJECTS = ["math_g9", "math_g12", "physics_g9", "physics_g12"]

# dim key → JSON field name
DIM_NAMES = {
    "dim1": "dim1_accuracy",
    "dim2": "dim2_interaction",
    "dim3": "dim3_visual",
    "dim4": "dim4_pedagogy",
    "dim5": "dim5_logic_coherence",
}


def parse_dim_score(filepath):
    """从 dim result 文件中提取 <score>N</score>。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"<score>(\d+(?:\.\d+)?)</score>", text)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


def get_render_check(exp_dir, topic_name):
    """检查各 scene 目录的 succ_rendered.txt 判断渲染状态。"""
    problem_dir = os.path.join(exp_dir, topic_name)
    if not os.path.isdir(problem_dir):
        return {}

    render_check = {}
    for entry in sorted(os.listdir(problem_dir)):
        scene_dir = os.path.join(problem_dir, entry)
        if not os.path.isdir(scene_dir) or not entry.startswith("scene"):
            continue
        succ_file = os.path.join(scene_dir, "succ_rendered.txt")
        render_check[entry] = "passed" if os.path.exists(succ_file) else "failed"

    return render_check


def build_results(base_dir):
    """遍历四个学科的 evaluate 目录，构建完整的 results 列表。"""
    results = []

    for subject in SUBJECTS:
        eval_dir = os.path.join(base_dir, f"evaluate_{subject}")
        exp_dir = os.path.join(base_dir, f"k12_vista_{subject}")

        if not os.path.isdir(eval_dir):
            print(f"  [SKIP] {eval_dir} not found")
            continue

        problem_dirs = sorted(
            d for d in os.listdir(eval_dir) if d.startswith("problem_")
        )
        print(f"  {subject}: {len(problem_dirs)} evaluated problems")

        missing_exp = 0

        for prob_dir_name in problem_dirs:
            prob_dir = os.path.join(eval_dir, prob_dir_name)

            # 解析五维评分
            scores = {}
            missing_dim = False
            for dim in range(1, 6):
                dim_file = os.path.join(prob_dir, f"dim{dim}_result.txt")
                score = parse_dim_score(dim_file)
                if score is not None:
                    scores[f"dim{dim}"] = score
                else:
                    scores[f"dim{dim}"] = 0.0
                    missing_dim = True

            if missing_dim:
                print(f"    [WARN] {prob_dir_name}: some dim scores missing, using 0")

            # 计算总分（五维均值）
            total_score = sum(scores.values()) / 5.0

            # 获取 render_check
            render_check = get_render_check(exp_dir, prob_dir_name)
            if not render_check and not os.path.isdir(os.path.join(exp_dir, prob_dir_name)):
                missing_exp += 1

            # 构建评测条目
            evaluation = {"total_score": round(total_score, 2)}
            for dim_key, dim_name in DIM_NAMES.items():
                evaluation[dim_name] = scores[dim_key]
            evaluation["render_check"] = render_check

            results.append({"topic": prob_dir_name, "evaluation": evaluation})

        if missing_exp:
            print(f"    [WARN] {missing_exp} problems have no exp dir for render_check")

    # 按题目名排序
    results.sort(key=lambda x: x["topic"])
    return results


def main():
    parser = argparse.ArgumentParser(
        description="从 evaluate 目录重建 Kimi-K2.6-k12-vista.json"
    )
    parser.add_argument(
        "--base-dir",
        default=BASE_DIR,
        help="EduInteract output 根目录",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(BASE_DIR, "results", "Kimi-K2.6-k12-vista.json"),
        help="输出 JSON 路径",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("重建 Kimi-K2.6-k12-vista.json")
    print("=" * 60)
    print(f"  Base dir: {args.base_dir}")

    results = build_results(args.base_dir)

    print()
    print(f"Total results: {len(results)}")

    # 按学科统计
    suffixes = Counter()
    for r in results:
        parts = r["topic"].split("_", 2)
        if len(parts) >= 3:
            suffixes[parts[2]] += 1
    for subj, count in sorted(suffixes.items()):
        print(f"  {subj}: {count}")

    # 分数分布
    scores = [r["evaluation"]["total_score"] for r in results]
    print(f"\nScore range: {min(scores):.2f} - {max(scores):.2f}")
    print(f"Mean score:  {sum(scores) / len(scores):.2f}")
    passed = sum(1 for s in scores if s > 4)
    print(f"Score > 4:   {passed}/{len(scores)}")

    # 保存
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"topics": results}, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
