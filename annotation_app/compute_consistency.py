#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
计算 LLM judge 与人工打分的一致性 (Spearman ρ).

数据源:
  - annotation_keys.json       : LLM judge 分 (interactive 项的 auto_scores)
  - human_annotations.json     : 人工打分 (多标注员)

流程:
  1. 取同时有 LLM 分 和 人工分 的 interactive 项 (交集 key)
  2. 对齐 5 个维度:
       LLM dim1_accuracy        <-> 人工 prob_align
       LLM dim2_interaction     <-> 人工 interact
       LLM dim3_visual          <-> 人工 visual
       LLM dim4_pedagogy        <-> 人工 pedagogy
       LLM dim5_logic_coherence <-> 人工 logic
  3. 多标注员: 取人工均值 (多个标注员的算术平均) 作为单一人工序列
  4. 每个维度 + 5 维总分 分别算 Spearman ρ (带 p 值, 样本数)

输出:
  - 控制台表格
  - consistency_report.json
"""
import json
from pathlib import Path
from statistics import mean

import numpy as np
from scipy.stats import spearmanr

HERE = Path(__file__).parent

# 维度对齐: (LLM key, 人工 key, 中文名)
DIM_PAIRS = [
    ("dim1_accuracy",        "prob_align", "题图匹配"),
    ("dim2_interaction",     "interact",   "交互功能"),
    ("dim3_visual",          "visual",     "视觉呈现"),
    ("dim4_pedagogy",        "pedagogy",   "教学性"),
    ("dim5_logic_coherence", "logic",      "逻辑连贯"),
]


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    llm_data = load_json(HERE / "annotation_keys.json")
    human_data = load_json(HERE / "human_annotations.json")

    # 只用 interactive 项 (static 项 LLM 无分, 人工维度也不同)
    common_keys = sorted(
        k for k in llm_data
        if k in human_data
        and llm_data[k].get("type") == "interactive"
        and llm_data[k].get("auto_scores")
    )

    print(f"=== 样本统计 ===")
    print(f"LLM 有分的 interactive 项 + 人工标注 的交集: {len(common_keys)} 个\n")

    # 每个维度构造 (llm_scores, human_mean_scores)
    results = {}
    for llm_key, human_key, cn in DIM_PAIRS:
        llm_vals, human_vals = [], []
        per_item = []
        for k in common_keys:
            lv = llm_data[k]["auto_scores"].get(llm_key)
            anns = human_data[k]
            hv = [anns[a][human_key] for a in anns if human_key in anns[a]]
            if lv is None or not hv:
                continue
            llm_vals.append(float(lv))
            human_vals.append(float(mean(hv)))
            per_item.append((k, float(lv), float(mean(hv)), len(hv)))

        if len(llm_vals) < 2:
            results[llm_key] = None
            continue

        rho, p = spearmanr(llm_vals, human_vals)
        results[llm_key] = {
            "dim": llm_key,
            "human_dim": human_key,
            "cn": cn,
            "n": len(llm_vals),
            "spearman_rho": float(rho) if not np.isnan(rho) else None,
            "p_value": float(p) if not np.isnan(p) else None,
            "per_item": per_item,
        }

    # 5 维总分: LLM total_score vs 人工 5 维平均
    llm_total, human_total, per_item_total = [], [], []
    for k in common_keys:
        auto = llm_data[k]["auto_scores"]
        tv = auto.get("total_score")
        anns = human_data[k]
        # 人工每个标注员取 5 维平均, 再跨标注员平均
        per_annotator = []
        for scores in anns.values():
            dims = [scores[hk] for _, hk, _ in DIM_PAIRS if hk in scores]
            if dims:
                per_annotator.append(mean(dims))
        if tv is None or not per_annotator:
            continue
        llm_total.append(float(tv))
        human_total.append(float(mean(per_annotator)))
        per_item_total.append((k, float(tv), float(mean(per_annotator)), len(per_annotator)))

    if len(llm_total) >= 2:
        rho_t, p_t = spearmanr(llm_total, human_total)
        results["total"] = {
            "dim": "total_score",
            "human_dim": "human_5dim_mean",
            "cn": "总分",
            "n": len(llm_total),
            "spearman_rho": float(rho_t) if not np.isnan(rho_t) else None,
            "p_value": float(p_t) if not np.isnan(p_t) else None,
            "per_item": per_item_total,
        }

    # ===== 控制台表格 =====
    print(f"{'维度':<22} {'LLM key':<22} {'人工 key':<18} {'N':>5} {'Spearman ρ':>12} {'p-value':>12}")
    print("-" * 95)
    for llm_key, human_key, cn in DIM_PAIRS + [("__total__", "__total__", "总分")]:
        if llm_key == "__total__":
            r = results.get("total")
        else:
            r = results.get(llm_key)
        if not r:
            print(f"{cn:<22} {llm_key:<22} {human_key:<18} {'-':>5} {'N/A':>12} {'':>12}")
            continue
        rho_s = f"{r['spearman_rho']:.4f}" if r["spearman_rho"] is not None else "N/A"
        p_s = f"{r['p_value']:.2e}" if r["p_value"] is not None else "N/A"
        print(f"{cn:<22} {r['dim']:<22} {r['human_dim']:<18} {r['n']:>5} {rho_s:>12} {p_s:>12}")

    # ===== 保存 =====
    # 保存时去掉 per_item 太长, 保留汇总
    summary = {
        k: {kk: vv for kk, vv in v.items() if kk != "per_item"}
        for k, v in results.items() if v
    }
    out = {
        "method": "Spearman rho (human mean vs LLM)",
        "metric": "ordinal",
        "n_common_items": len(common_keys),
        "dimensions": summary,
    }
    with open(HERE / "consistency_report.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {HERE / 'consistency_report.json'}")


if __name__ == "__main__":
    main()
