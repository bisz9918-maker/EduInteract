#!/usr/bin/env python3
"""
根据token使用情况和价格计算成本
"""
import json
import csv
from pathlib import Path

# 读取token统计数据
token_stats_file = "/inspire/hdd/project/ai4education/bishuzhen-CZXS24220022/edubench/TheoremExplainAgent/token_usage_summary.json"

with open(token_stats_file, 'r') as f:
    token_stats = json.load(f)

# 定义价格（每百万token的美元价格）
prices = {
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "gemini-3-pro-preview": {"input": 2.00, "output": 12.00},
    "kimi-k25": {"input": 0.45, "output": 2.20},
    "gpt-5": {"input": 1.25, "output": 10.00},
    "qwen3.5-35b": {"input": 0.16, "output": 1.30},
}

# 计算成本
results = []

for model_name, stats in token_stats.items():
    if model_name not in prices:
        print(f"Warning: No price info for {model_name}")
        continue

    price_info = prices[model_name]

    # 总token数
    total_input_tokens = stats['sum_input_tokens']
    total_output_tokens = stats['sum_output_tokens']
    total_tokens = stats['sum_total_tokens']

    # 平均token数
    avg_input_tokens = stats['avg_input_tokens']
    avg_output_tokens = stats['avg_output_tokens']
    avg_total_tokens = stats['avg_total_tokens']

    # 计算成本（价格是per million tokens）
    input_cost = (total_input_tokens / 1_000_000) * price_info['input']
    output_cost = (total_output_tokens / 1_000_000) * price_info['output']
    total_cost = input_cost + output_cost

    # 平均每题成本
    avg_cost_per_problem = total_cost / stats['count'] if stats['count'] > 0 else 0

    results.append({
        'Model': model_name,
        'Count': stats['count'],
        'Total_Input_Tokens': total_input_tokens,
        'Total_Output_Tokens': total_output_tokens,
        'Total_Tokens': total_tokens,
        'Avg_Input_Tokens': f"{avg_input_tokens:.2f}",
        'Avg_Output_Tokens': f"{avg_output_tokens:.2f}",
        'Avg_Total_Tokens': f"{avg_total_tokens:.2f}",
        'Input_Price_Per_M': f"${price_info['input']:.2f}",
        'Output_Price_Per_M': f"${price_info['output']:.2f}",
        'Input_Cost': f"${input_cost:.4f}",
        'Output_Cost': f"${output_cost:.4f}",
        'Total_Cost': f"${total_cost:.4f}",
        'Avg_Cost_Per_Problem': f"${avg_cost_per_problem:.4f}",
    })

# 按模型名称排序
results.sort(key=lambda x: x['Model'])

# 输出CSV
csv_file = "/inspire/hdd/project/ai4education/bishuzhen-CZXS24220022/edubench/TheoremExplainAgent/token_cost_analysis.csv"

fieldnames = [
    'Model', 'Count',
    'Total_Input_Tokens', 'Total_Output_Tokens', 'Total_Tokens',
    'Avg_Input_Tokens', 'Avg_Output_Tokens', 'Avg_Total_Tokens',
    'Input_Price_Per_M', 'Output_Price_Per_M',
    'Input_Cost', 'Output_Cost', 'Total_Cost', 'Avg_Cost_Per_Problem'
]

with open(csv_file, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(results)

print(f"CSV file saved to: {csv_file}")
print()

# 打印表格
print("=" * 150)
print("Token Usage and Cost Analysis")
print("=" * 150)
print(f"{'Model':<25} {'Count':>6} {'Avg Input':>12} {'Avg Output':>12} {'Total Cost':>12} {'Cost/Problem':>12}")
print("-" * 150)

for r in results:
    print(f"{r['Model']:<25} {r['Count']:>6} {r['Avg_Input_Tokens']:>12} {r['Avg_Output_Tokens']:>12} {r['Total_Cost']:>12} {r['Avg_Cost_Per_Problem']:>12}")

print("=" * 150)
