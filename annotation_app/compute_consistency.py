#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
计算 LLM judge 与人工打分的一致性, 以及人类评分者之间的一致性.

数据源:
  - annotation_keys.json       : LLM judge 分 (interactive 项的 auto_scores)
  - human_annotations.json     : 真实人工打分 (多标注员)
  - human_annotations_2.json   : 合成人工打分 (10 标注员)

两类一致性:
  A. LLM vs 人工 (Spearman ρ)
       每个 interactive 项: 不取多人均值 (会被平滑拉高), 而是逐个标注者单独
       与 LLM 算 ρ, 再取所有标注者的 ρ 均值. 反映「单个评分者与 judge 的一致性」.
       逐 5 个维度计算 (不计算总分一致性).

  B. 人类评分者之间 (Krippendorff's α, ordinal)
       每个 interactive 项的每个维度, 取所有标注员的打分构成 reliability matrix,
       计算 ordinal α. 只在有 >=2 个标注员的题目上计算.

用法:
  python compute_consistency.py                          # 默认用真实标注
  python compute_consistency.py --human human_annotations_2.json  # 用合成标注

输出:
  - 控制台表格
  - consistency_report.json
"""
import argparse
import json
from pathlib import Path
import statistics as st
from statistics import mean

import numpy as np
from scipy.stats import spearmanr
import krippendorff

HERE = Path(__file__).parent

# 维度对齐: (LLM auto_scores key, 人工维度 key, 中文名)
DIM_PAIRS = [
    ("dim1_accuracy",        "prob_align", "题图匹配"),
    ("dim2_interaction",     "interact",   "交互功能"),
    ("dim3_visual",          "visual",     "视觉呈现"),
    ("dim4_pedagogy",        "pedagogy",   "教学性"),
    ("dim5_logic_coherence", "logic",      "逻辑连贯"),
]

SCORE_RANGE = [1, 2, 3, 4, 5]


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def clamp_safe(v):
    """转 float, 越界视为缺失 (NaN)."""
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return np.nan
    if fv < SCORE_RANGE[0] or fv > SCORE_RANGE[-1]:
        return np.nan
    return fv


# ── A. LLM vs 人工 (Spearman ρ) ────────────────────────────────────────────────

def common_interactive_keys(llm_data, human_data):
    """交集: interactive 项 + 有 LLM auto_scores + 有人工标注."""
    return sorted(
        k for k in llm_data
        if k in human_data
        and llm_data[k].get("type") == "interactive"
        and llm_data[k].get("auto_scores")
    )


def compute_llm_distribution(llm_data, common_keys):
    """统计每个维度的 LLM 分分布 (用于诊断天花板/地板效应).

    返回 {llm_key: {n, mean, std, dist: {score: count}, top_ratio, bottom_ratio}}
    top_ratio    = 最高分(5)占比, 衡量天花板效应
    bottom_ratio = 最低分(1)占比, 衡量地板效应
    """
    dist = {}
    for llm_key, human_key, cn in DIM_PAIRS:
        vals = []
        for k in common_keys:
            lv = llm_data[k]["auto_scores"].get(llm_key)
            if lv is not None:
                vals.append(float(lv))
        if not vals:
            dist[llm_key] = None
            continue
        counts = {}
        for v in vals:
            counts[v] = counts.get(v, 0) + 1
        counts = dict(sorted(counts.items()))
        dist[llm_key] = {
            "dim": llm_key, "cn": cn,
            "n": len(vals),
            "mean": round(st.mean(vals), 2),
            "std": round(st.pstdev(vals), 2),
            "dist": {str(k): v for k, v in counts.items()},
            "top_ratio": round(counts.get(5.0, 0) / len(vals), 3),
            "bottom_ratio": round(counts.get(1.0, 0) / len(vals), 3),
        }
    return dist


def compute_llm_vs_human(llm_data, human_data):
    """LLM 分 vs 人工, 逐维度, 逐标注者算 Spearman ρ 再平均.

    不再取多人均值 (会被中心极限平滑、人为拉高 ρ), 而是每个标注者
    单独与 LLM 算 ρ, 再取所有标注者的 ρ 均值, 反映「单个评分者与
    judge 的一致性」.
    """
    common_keys = common_interactive_keys(llm_data, human_data)

    # 收集所有标注员 (与 inter-annotator 口径一致)
    annotators = set()
    for k in common_keys:
        for a, sc in human_data[k].items():
            if isinstance(sc, dict):
                annotators.add(a)
    annotators = sorted(annotators)

    results = {}
    for llm_key, human_key, cn in DIM_PAIRS:
        # 先按题收集 (llm_val, {annotator: human_val})
        per_item = []
        for k in common_keys:
            lv = llm_data[k]["auto_scores"].get(llm_key)
            if lv is None:
                continue
            anns = human_data[k]
            hv = {a: anns[a][human_key] for a in anns
                  if isinstance(anns[a], dict) and human_key in anns[a]}
            if not hv:
                continue
            per_item.append((float(lv), hv))

        n = len(per_item)
        if n < 2:
            results[llm_key] = {"dim": llm_key, "human_dim": human_key, "cn": cn,
                                "n": n, "n_annotators": 0,
                                "spearman_rho": None, "p_value": None,
                                "per_annotator_rho": []}
            continue

        # 每个标注者单独算 ρ
        rhos, ps = [], []
        per_annotator = []
        for a in annotators:
            llm_vals, human_vals = [], []
            for lv, hv in per_item:
                if a in hv:
                    llm_vals.append(lv)
                    human_vals.append(float(hv[a]))
            if len(llm_vals) < 2:
                continue
            rho, p = spearmanr(llm_vals, human_vals)
            if np.isnan(rho):
                continue
            rhos.append(float(rho))
            ps.append(float(p) if not np.isnan(p) else None)
            per_annotator.append({"annotator": a, "n": len(llm_vals), "rho": float(rho)})

        results[llm_key] = {
            "dim": llm_key, "human_dim": human_key, "cn": cn,
            "n": n,
            "n_annotators": len(rhos),
            "spearman_rho": round(mean(rhos), 4) if rhos else None,
            "rho_std": round(st.pstdev(rhos), 4) if len(rhos) > 1 else 0.0,
            "rho_min": round(min(rhos), 4) if rhos else None,
            "rho_max": round(max(rhos), 4) if rhos else None,
            "per_annotator_rho": per_annotator,
        }

    return results, len(common_keys)
    if len(llm_vals) < 2:
        return {"dim": dim, "human_dim": human_dim, "cn": cn,
                "n": len(llm_vals), "spearman_rho": None, "p_value": None}
    rho, p = spearmanr(llm_vals, human_vals)
    return {
        "dim": dim, "human_dim": human_dim, "cn": cn,
        "n": len(llm_vals),
        "spearman_rho": float(rho) if not np.isnan(rho) else None,
        "p_value": float(p) if not np.isnan(p) else None,
    }


# ── B. 人类评分者之间 (Krippendorff's α, ordinal) ───────────────────────────────

def compute_inter_annotator(human_data, llm_data):
    """逐维度 Krippendorff α.

    对每个维度, 收集所有 interactive 项 (有 LLM 分的) 上各标注员的打分,
    构成 reliability matrix (annotator × item), 缺失值用 NaN.
    """
    # interactive 项集合 (有 LLM 分的)
    interactive_keys = common_interactive_keys(llm_data, human_data)

    # 收集所有标注员
    annotators = set()
    for k in interactive_keys:
        for a, sc in human_data[k].items():
            if isinstance(sc, dict):
                annotators.add(a)
    annotators = sorted(annotators)

    results = {}
    for llm_key, human_key, cn in DIM_PAIRS:
        # reliability matrix: 每行一个标注员, 每列一个 item
        matrix = []
        n_items_with_data = 0
        for a in annotators:
            row = []
            for k in interactive_keys:
                sc = human_data[k].get(a, {})
                v = sc.get(human_key) if isinstance(sc, dict) else None
                row.append(clamp_safe(v) if v is not None else np.nan)
            matrix.append(row)
        # 统计至少 2 人标注的 item 数
        col_counts = [
            sum(1 for r in range(len(annotators)) if not np.isnan(matrix[r][c]))
            for c in range(len(interactive_keys))
        ]
        n_items_with_data = sum(1 for c in col_counts if c >= 2)

        alpha = None
        if n_items_with_data >= 2 and len(annotators) >= 2:
            try:
                alpha = krippendorff.alpha(
                    reliability_data=np.array(matrix, dtype=float),
                    level_of_measurement='ordinal',
                    value_domain=SCORE_RANGE,
                )
                alpha = float(alpha) if not np.isnan(alpha) else None
            except Exception as e:
                alpha = None

        results[llm_key] = {
            "dim": llm_key, "human_dim": human_key, "cn": cn,
            "n_annotators": len(annotators),
            "n_items_with_2plus": n_items_with_data,
            "krippendorff_alpha": alpha,
        }

    return results, len(interactive_keys), annotators


# ── 输出 ───────────────────────────────────────────────────────────────────────

def print_llm_distribution(dist):
    """打印 LLM 分分布 (诊断天花板/地板效应)."""
    print(f"\n{'='*92}")
    print(f"  LLM 打分分布统计 (诊断天花板/地板效应)")
    print(f"{'='*92}")
    print(f"{'维度':<14} {'N':>4} {'均值':>6} {'std':>6} {'5分占比':>8} {'1分占比':>8}  分布(分:题数)")
    print("-" * 92)
    for llm_key, human_key, cn in DIM_PAIRS:
        d = dist.get(llm_key)
        if not d:
            print(f"{cn:<14} {'-':>4} {'-':>6} {'-':>6} {'-':>8} {'-':>8}")
            continue
        dist_str = "  ".join(f"{s}:{c}" for s, c in d["dist"].items())
        # 标注天花板/地板效应
        flag = ""
        if d["top_ratio"] >= 0.5:
            flag = "  ← 天花板效应"
        elif d["bottom_ratio"] >= 0.5:
            flag = "  ← 地板效应"
        print(f"{cn:<14} {d['n']:>4} {d['mean']:>6.2f} {d['std']:>6.2f} "
              f"{d['top_ratio']*100:>7.1f}% {d['bottom_ratio']*100:>7.1f}%  {dist_str}{flag}")


def print_llm_vs_human(results):
    print(f"\n{'='*100}")
    print(f"  A. LLM judge vs 人工打分 (Spearman ρ, 逐标注者算再平均)")
    print(f"{'='*100}")
    print(f"{'维度':<14} {'LLM key':<22} {'人工 key':<18} {'N':>5} {'人数':>4} "
          f"{'ρ均值':>8} {'std':>6} {'min':>7} {'max':>7}")
    print("-" * 100)
    for llm_key, human_key, cn in DIM_PAIRS:
        r = results.get(llm_key)
        if not r or r["spearman_rho"] is None:
            print(f"{cn:<14} {llm_key:<22} {human_key:<18} {'-':>5} {'-':>4} {'N/A':>8}")
            continue
        print(f"{cn:<14} {r['dim']:<22} {r['human_dim']:<18} {r['n']:>5} {r['n_annotators']:>4} "
              f"{r['spearman_rho']:>8.4f} {r['rho_std']:>6.4f} "
              f"{r['rho_min']:>7.4f} {r['rho_max']:>7.4f}")


def print_inter_annotator(results, annotators):
    print(f"\n{'='*92}")
    print(f"  B. 人类评分者之间 (Krippendorff's α, ordinal)")
    print(f"{'='*92}")
    print(f"标注员 ({len(annotators)} 人): {', '.join(annotators)}")
    print(f"{'维度':<14} {'LLM key':<22} {'人工 key':<18} {'标注员数':>8} {'有效题数(≥2人)':>14} {'α':>10}")
    print("-" * 92)
    for llm_key, human_key, cn in DIM_PAIRS:
        r = results.get(llm_key)
        if not r:
            print(f"{cn:<14} {llm_key:<22} {human_key:<18} {'-':>8} {'-':>14} {'N/A':>10}")
            continue
        a_s = f"{r['krippendorff_alpha']:.4f}" if r["krippendorff_alpha"] is not None else "N/A"
        print(f"{cn:<14} {r['dim']:<22} {r['human_dim']:<18} {r['n_annotators']:>8} "
              f"{r['n_items_with_2plus']:>14} {a_s:>10}")


def main():
    parser = argparse.ArgumentParser(description="一致性计算")
    parser.add_argument("--human", default="human_annotations.json",
                        help="人工标注文件 (默认 human_annotations.json)")
    args = parser.parse_args()

    llm_data = load_json(HERE / "annotation_keys.json")
    human_path = HERE / args.human
    human_data = load_json(human_path)

    print(f"LLM 数据:  annotation_keys.json")
    print(f"人工数据:  {args.human}")

    # A. LLM vs 人工
    llm_results, n_common = compute_llm_vs_human(llm_data, human_data)
    print(f"\n=== 样本统计 ===")
    print(f"LLM 有分的 interactive 项 + 人工标注 的交集: {n_common} 个")
    print_llm_vs_human(llm_results)

    # LLM 分分布统计 (诊断天花板/地板效应)
    llm_dist = compute_llm_distribution(llm_data, common_interactive_keys(llm_data, human_data))
    print_llm_distribution(llm_dist)

    # B. 人类评分者之间
    ia_results, n_inter, annotators = compute_inter_annotator(human_data, llm_data)
    print_inter_annotator(ia_results, annotators)

    # 保存
    out = {
        "method_llm_vs_human": "Spearman rho (human mean vs LLM)",
        "method_inter_annotator": "Krippendorff alpha (ordinal)",
        "human_source": args.human,
        "n_common_items": n_common,
        "n_interactive_items": n_inter,
        "annotators": annotators,
        "llm_vs_human": {k: {kk: vv for kk, vv in v.items()}
                         for k, v in llm_results.items() if v},
        "llm_score_distribution": {k: v for k, v in llm_dist.items() if v},
        "inter_annotator": {k: v for k, v in ia_results.items() if v},
    }
    out_path = HERE / "consistency_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {out_path}")


if __name__ == "__main__":
    main()
