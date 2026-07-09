#!/usr/bin/env python3
"""
统计多个模型实验的平均token使用情况
"""
import json
import os
from pathlib import Path
from typing import Dict, List

def collect_token_stats(model_path: str, start_index: int = 0) -> Dict:
    """收集单个模型所有问题的token统计

    start_index: 只统计目录名中problem编号 > start_index 的题目
    """
    total_tokens_list = []
    input_tokens_list = []
    output_tokens_list = []

    scene_outline_input_list = []
    scene_outline_output_list = []

    impl_plan_input_list = []
    impl_plan_output_list = []

    scene_model_input_list = []
    scene_model_output_list = []

    model_dir = Path(model_path)

    if not model_dir.exists():
        print(f"Warning: Directory not found: {model_path}")
        return None

    if start_index > 0:
        print(f"  Only counting problems with index > {start_index}")

    # 遍历所有problem目录
    for problem_dir in sorted(model_dir.iterdir()):
        if not (problem_dir.is_dir() and problem_dir.name.startswith('problem_')):
            continue
        if start_index > 0:
            try:
                prob_idx = int(problem_dir.name.split('_')[1])
            except (IndexError, ValueError):
                continue
            if prob_idx <= start_index:
                continue
        timing_file = problem_dir / 'timing.json'

        if timing_file.exists():
            try:
                with open(timing_file, 'r') as f:
                    data = json.load(f)
                    token_usage = data.get('token_usage', {})

                    total = token_usage.get('total_tokens', 0)
                    input_t = token_usage.get('input_tokens', 0)
                    output_t = token_usage.get('output_tokens', 0)

                    # 只统计非零的数据
                    if total > 0:
                        total_tokens_list.append(total)
                        input_tokens_list.append(input_t)
                        output_tokens_list.append(output_t)

                    # scene_outline
                    planner_detailed = token_usage.get('planner_model_detailed', {})
                    scene_outline = planner_detailed.get('scene_outline', {})
                    so_in = scene_outline.get('input_tokens', 0)
                    so_out = scene_outline.get('output_tokens', 0)
                    if so_in + so_out > 0:
                        scene_outline_input_list.append(so_in)
                        scene_outline_output_list.append(so_out)

                    # implementation_plans (所有scene的sum)
                    impl_plans = planner_detailed.get('implementation_plans', {})
                    ip_in = sum(v.get('input_tokens', 0) for v in impl_plans.values() if isinstance(v, dict))
                    ip_out = sum(v.get('output_tokens', 0) for v in impl_plans.values() if isinstance(v, dict))
                    if ip_in + ip_out > 0:
                        impl_plan_input_list.append(ip_in)
                        impl_plan_output_list.append(ip_out)

                    # scene_model
                    scene_model = token_usage.get('scene_model', {})
                    sm_in = scene_model.get('input_tokens', 0)
                    sm_out = scene_model.get('output_tokens', 0)
                    if sm_in + sm_out > 0:
                        scene_model_input_list.append(sm_in)
                        scene_model_output_list.append(sm_out)

            except Exception as e:
                print(f"Error reading {timing_file}: {e}")

    if not total_tokens_list:
        return None

    def avg(lst): return sum(lst) / len(lst) if lst else 0

    return {
        'count': len(total_tokens_list),
        'avg_total_tokens': avg(total_tokens_list),
        'avg_input_tokens': avg(input_tokens_list),
        'avg_output_tokens': avg(output_tokens_list),
        'sum_total_tokens': sum(total_tokens_list),
        'sum_input_tokens': sum(input_tokens_list),
        'sum_output_tokens': sum(output_tokens_list),
        'scene_outline': {
            'avg_input': avg(scene_outline_input_list),
            'avg_output': avg(scene_outline_output_list),
            'sum_input': sum(scene_outline_input_list),
            'sum_output': sum(scene_outline_output_list),
        },
        'implementation_plans': {
            'avg_input': avg(impl_plan_input_list),
            'avg_output': avg(impl_plan_output_list),
            'sum_input': sum(impl_plan_input_list),
            'sum_output': sum(impl_plan_output_list),
        },
        'scene_model': {
            'avg_input': avg(scene_model_input_list),
            'avg_output': avg(scene_model_output_list),
            'sum_input': sum(scene_model_input_list),
            'sum_output': sum(scene_model_output_list),
        },
    }

def main():
    # 定义模型路径
    base_path = "/inspire/hdd/project/ai4education/bishuzhen-CZXS24220022/edubench"

    models = [
        ("claude-sonnet-4-5", f"{base_path}/VisualSolver/output/exp_claude-sonnet-4-5", 118),
        ("gemini-3-pro-preview", f"{base_path}/TheoremExplainAgent/output/exp_gemini-3-pro-preview", 118),
        ("gpt-5", f"{base_path}/TheoremExplainAgent/output/exp_gpt-5", 118),
        ("qwen3.5-35b", f"{base_path}/TheoremExplainAgent/output/exp_qwen3.5-35b", 118),
        ("kimi-k25", f"{base_path}/VisualSolver/output/exp_kimi-k25", 118),
        ("all_parallel","/inspire/hdd/project/ai4education/bishuzhen-CZXS24220022/edubench/VisualSolver/output/exp_gemini-3-pro-preview_workflow2",0),
        ("Ministral-3-14B-Instruct-2512", f"{base_path}/TheoremExplainAgent/output/exp_Ministral-3-14B-Instruct-2512", 0),
        ("Mistral-Large-3-675B-Instruct-2512", f"{base_path}/TheoremExplainAgent/output/exp_Mistral-Large-3-675B-Instruct-2512", 0),
        ("Mistral-Small-4-119B-2603", f"{base_path}/TheoremExplainAgent/output/exp_Mistral-Small-4-119B-2603", 0),
        ("Qwen3.5-122B-A10B", f"{base_path}/TheoremExplainAgent/output/exp_Qwen3.5-122B-A10B", 0),
        ("qwen3.5-397b", f"{base_path}/TheoremExplainAgent/output/exp_qwen3.5-397b", 0),
    ]

    print("=" * 110)
    print("Token Usage Statistics for Each Model (problem_index > 118)")
    print("=" * 110)
    print()

    all_stats = {}

    for model_name, model_path, start_index in models:
        print(f"Processing: {model_name}")
        print(f"Path: {model_path}")

        stats = collect_token_stats(model_path, start_index=start_index)

        if stats:
            all_stats[model_name] = stats
            print(f"  Valid problems: {stats['count']}")
            print(f"  Average total_tokens:  {stats['avg_total_tokens']:,.2f}")
            print(f"  Average input_tokens:  {stats['avg_input_tokens']:,.2f}")
            print(f"  Average output_tokens: {stats['avg_output_tokens']:,.2f}")
            print(f"  Sum total_tokens:      {stats['sum_total_tokens']:,}")
            print(f"  --- scene_outline ---")
            so = stats['scene_outline']
            print(f"    avg_input:  {so['avg_input']:,.2f}  avg_output: {so['avg_output']:,.2f}")
            print(f"    sum_input:  {so['sum_input']:,}  sum_output: {so['sum_output']:,}")
            print(f"  --- implementation_plans ---")
            ip = stats['implementation_plans']
            print(f"    avg_input:  {ip['avg_input']:,.2f}  avg_output: {ip['avg_output']:,.2f}")
            print(f"    sum_input:  {ip['sum_input']:,}  sum_output: {ip['sum_output']:,}")
            print(f"  --- scene_model ---")
            sm = stats['scene_model']
            print(f"    avg_input:  {sm['avg_input']:,.2f}  avg_output: {sm['avg_output']:,.2f}")
            print(f"    sum_input:  {sm['sum_input']:,}  sum_output: {sm['sum_output']:,}")
        else:
            print(f"  No valid data found")

        print("-" * 110)
        print()

    # 输出汇总表格
    print("\n" + "=" * 110)
    print("Summary Table")
    print("=" * 110)
    print(f"{'Model':<25} {'Count':>8} {'Avg Total':>15} {'Avg Input':>15} {'Avg Output':>15} {'SO AvgIn':>12} {'SO AvgOut':>12} {'IP AvgIn':>12} {'IP AvgOut':>12} {'SM AvgIn':>12} {'SM AvgOut':>12}")
    print("-" * 110)

    for model_name in ["claude-sonnet-4-5", "gemini-3-pro-preview", "gpt-5", "qwen3.5-35b", "kimi-k25",
                        "Ministral-3-14B-Instruct-2512", "Mistral-Large-3-675B-Instruct-2512",
                        "Mistral-Small-4-119B-2603", "Qwen3.5-122B-A10B", "qwen3.5-397b"]:
        if model_name in all_stats:
            stats = all_stats[model_name]
            so = stats['scene_outline']
            ip = stats['implementation_plans']
            sm = stats['scene_model']
            print(f"{model_name:<25} {stats['count']:>8} "
                  f"{stats['avg_total_tokens']:>15,.2f} "
                  f"{stats['avg_input_tokens']:>15,.2f} "
                  f"{stats['avg_output_tokens']:>15,.2f} "
                  f"{so['avg_input']:>12,.2f} "
                  f"{so['avg_output']:>12,.2f} "
                  f"{ip['avg_input']:>12,.2f} "
                  f"{ip['avg_output']:>12,.2f} "
                  f"{sm['avg_input']:>12,.2f} "
                  f"{sm['avg_output']:>12,.2f}")

    print("=" * 110)

    # 保存JSON格式的结果
    output_file = f"{base_path}/TheoremExplainAgent/token_usage_summary.json"
    with open(output_file, 'w') as f:
        json.dump(all_stats, f, indent=2)

    print(f"\nResults saved to: {output_file}")

    # 保存简明CSV
    csv_file = f"{base_path}/TheoremExplainAgent/token_usage_avg.csv"
    with open(csv_file, 'w', encoding='utf-8') as f:
        f.write("Model,Avg_Input_Tokens,Avg_Output_Tokens\n")
        for model_name, _, _ in models:
            if model_name in all_stats:
                stats = all_stats[model_name]
                f.write(f"{model_name},{stats['avg_input_tokens']:.2f},{stats['avg_output_tokens']:.2f}\n")
    print(f"CSV saved to: {csv_file}")

if __name__ == "__main__":
    main()
