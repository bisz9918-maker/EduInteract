#!/usr/bin/env python3
"""
后处理 SFT 数据：去除连续相似的 Read→Write→Check 重复循环。

策略：检测连续产生相同 check 结果的 fix 循环，只保留第一次。

例：check 结果连续 5 次都是 "1 issue: CROWDED"
→ 保留第 1 次 check + 导致该结果的 fix attempt
→ 删除后续 4 次相同 check 及其 fix attempt
→ 如果之后 check 结果变了（如 "0 issues"），保留

用法:
  source .venv/bin/activate
  python dedup_sft_data.py
"""

import json
import os
import re

SFT_DATA_DIR = "/inspire/qb-ilm/project/ai4education/bishuzhen-CZXS24220022/edu_interact/EduInteract/output/sft_data"


def _get_text(msg):
    """Extract plain text from a message for analysis."""
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if not isinstance(p, dict):
                continue
            if p.get("type") == "text":
                parts.append(p.get("text", ""))
            elif p.get("type") == "image_url":
                parts.append("[IMAGE]")
        return "\n".join(parts)
    return str(content)


def _extract_check_summary(text):
    """Extract a summary of check results for comparison.

    Returns a string like "3:OVERLAP,CROWDED" or "passed" or None.
    """
    m = re.search(r"Found\s+(\d+)\s+layout\s+issue", text)
    if m:
        count = int(m.group(1))
        if count == 0:
            return "passed"
        types = re.findall(r"(OVERLAP|CROWDED|MISALIGNED|CLIPPED|OFFSCREEN)", text)
        return f"{count}:{','.join(sorted(set(types)))}"
    if re.search(r"All\s+clear|No\s+issues|0\s+layout\s+issue", text, re.IGNORECASE):
        return "passed"
    return None


def _find_check_positions(messages):
    """Find positions of check results (tool messages with layout issue reports)."""
    positions = []
    for i, msg in enumerate(messages):
        if msg.get("role") not in ("tool", "user"):
            continue
        text = _get_text(msg)
        summary = _extract_check_summary(text)
        if summary is not None:
            positions.append((i, summary))
    return positions


def dedup_fix_loops(messages):
    """Remove consecutive similar fix loops, keeping first occurrence.

    Algorithm:
    1. Find all "check points" with layout issue summaries
    2. Group consecutive checks with the same summary
    3. For each group with >1 same-summary checks:
       - Keep the first check and the fix attempt that produced it
       - Remove subsequent same-summary checks AND the fix attempts between them
    4. Messages after the last check in any group are always kept
    """
    if len(messages) < 10:
        return messages

    checks = _find_check_positions(messages)
    if len(checks) <= 1:
        return messages

    to_remove = set()

    i = 0
    while i < len(checks):
        # Find end of current run (consecutive same-summary checks)
        j = i + 1
        while j < len(checks) and checks[j][1] == checks[i][1]:
            j += 1

        # Run: checks[i] .. checks[j-1], all with same summary
        run_length = j - i

        if run_length > 1:
            # Keep first check (checks[i]), remove rest + their preceding fix attempts
            # For k in [i+1, j-1]: remove from checks[k-1]+1 to checks[k] (inclusive)
            for k in range(i + 1, j):
                start = checks[k - 1][0] + 1
                end = checks[k][0]
                for idx in range(start, end + 1):
                    to_remove.add(idx)

        i = j

    if not to_remove:
        return messages

    return [m for idx, m in enumerate(messages) if idx not in to_remove]


def process_file(input_path, output_path):
    """Process a single JSONL file, return stats."""
    stats = {
        "total": 0,
        "shortened": 0,
        "unchanged": 0,
        "msgs_before": 0,
        "msgs_after": 0,
        "by_reduction": [],  # (original_len, new_len, reduction%)
    }

    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        for line in fin:
            data = json.loads(line)
            messages = data["messages"]
            orig_len = len(messages)
            stats["total"] += 1
            stats["msgs_before"] += orig_len

            cleaned = dedup_fix_loops(messages)
            new_len = len(cleaned)
            stats["msgs_after"] += new_len

            if new_len < orig_len:
                stats["shortened"] += 1
                pct = (orig_len - new_len) / orig_len * 100
                stats["by_reduction"].append((orig_len, new_len, pct))
            else:
                stats["unchanged"] += 1

            data["messages"] = cleaned
            fout.write(json.dumps(data, ensure_ascii=False) + "\n")

    return stats


def main():
    for fname in ["sft_outline.jsonl", "sft_plan.jsonl", "sft_code.jsonl"]:
        input_path = os.path.join(SFT_DATA_DIR, fname)
        output_path = os.path.join(SFT_DATA_DIR, fname.replace(".jsonl", "_dedup.jsonl"))

        if not os.path.exists(input_path):
            print(f"[SKIP] {fname} not found")
            continue

        print(f"\n{'='*60}")
        print(f"Processing: {fname}")
        print(f"{'='*60}")

        stats = process_file(input_path, output_path)

        print(f"  Samples: {stats['total']} total, {stats['shortened']} shortened, {stats['unchanged']} unchanged")
        print(f"  Messages: {stats['msgs_before']} -> {stats['msgs_after']}")
        reduction = stats["msgs_before"] - stats["msgs_after"]
        pct = (reduction / stats["msgs_before"] * 100) if stats["msgs_before"] > 0 else 0
        print(f"  Reduced: {reduction} messages ({pct:.1f}%)")

        if stats["by_reduction"]:
            top5 = sorted(stats["by_reduction"], key=lambda x: -x[2])[:5]
            print(f"  Top 5 reductions:")
            for orig, new, p in top5:
                print(f"    {orig} -> {new} ({p:.0f}%)")

        print(f"  Output: {output_path}")


if __name__ == "__main__":
    main()
