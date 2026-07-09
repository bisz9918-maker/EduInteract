#!/usr/bin/env python3
"""
从 K12_Vista.jsonl 中抽取指定科目的12年级题目

用法:
    python extract_g12_samples.py
"""

import json
import random
from pathlib import Path
from collections import defaultdict


def extract_g12_samples(input_path: str, output_path: str, samples_per_subject: int = 10):
    """
    从 K12_Vista.jsonl 抽取指定科目的题目

    Args:
        input_path: 输入的 jsonl 文件路径
        output_path: 输出的 json 文件路径
        samples_per_subject: 每个科目抽取的题目数量
    """
    # 目标科目
    target_subjects = ['physics-g12', 'chemistry-g12', 'biology-g12']

    # 按科目分类存储题目
    subjects_data = defaultdict(list)

    print(f"📖 Reading from: {input_path}")

    # 读取jsonl文件
    total_lines = 0
    with open(input_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            total_lines = line_num
            try:
                data = json.loads(line.strip())
                subject = data.get('subject', '')

                # 只收集目标科目
                if subject in target_subjects:
                    subjects_data[subject].append(data)

            except json.JSONDecodeError as e:
                print(f"⚠️  Line {line_num}: JSON decode error - {e}")
                continue

    print(f"✓ Processed {total_lines} lines")
    print()

    # 显示每个科目的题目数量
    print("📊 Available samples by subject:")
    for subject in target_subjects:
        count = len(subjects_data[subject])
        print(f"  {subject:20s}: {count:4d} problems")
    print()

    # 抽取样本
    selected_samples = []

    print(f"🎯 Extracting {samples_per_subject} samples per subject:")
    for subject in target_subjects:
        available = subjects_data[subject]

        if len(available) == 0:
            print(f"  ❌ {subject}: No problems found!")
            continue

        # 如果可用题目少于需要数量，全部选择
        if len(available) <= samples_per_subject:
            selected = available
            print(f"  ⚠️  {subject}: Only {len(available)} available (taking all)")
        else:
            # 随机抽取
            selected = random.sample(available, samples_per_subject)
            print(f"  ✓ {subject}: Selected {len(selected)} problems")

        selected_samples.extend(selected)

    print()
    print(f"📝 Total selected: {len(selected_samples)} problems")

    # 保存到json文件# 给每个元素加上 index 字段
    for idx, elem in enumerate(selected_samples):
        elem['index'] = idx
        
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(selected_samples, f, ensure_ascii=False, indent=2)

    print(f"✓ Saved to: {output_path}")

    # 显示统计信息
    print()
    print("=" * 70)
    print("📊 Final Statistics:")
    print("=" * 70)

    subject_counts = defaultdict(int)
    for item in selected_samples:
        subject_counts[item['subject']] += 1

    for subject in sorted(subject_counts.keys()):
        print(f"  {subject:20s}: {subject_counts[subject]:3d} problems")

    print("=" * 70)


def main():
    # 文件路径
    input_file = "/inspire/hdd/project/ai4education/bishuzhen-CZXS24220022/edubench/K12-Vista/K12_Vista.jsonl"
    output_file = "/inspire/hdd/project/ai4education/bishuzhen-CZXS24220022/edubench/TheoremExplainAgent/data/science_problem/science-g12_samples.json"

    # 确保输出目录存在
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 抽取样本
    extract_g12_samples(input_file, output_file, samples_per_subject=10)


if __name__ == "__main__":
    main()
