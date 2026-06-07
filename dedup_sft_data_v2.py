#!/usr/bin/env python3
"""
SFT 数据精简 v2：只保留核心对话，去除中间调试循环。

保留策略：
  system → 初始化 → Read spec → Read 题图 → 最后一次包含完整 HTML 的写入 → tool result

写入 HTML 的三种模式：
  1. Write 工具：{"file_path": "scene1.html", ...}           → 每次包含完整 HTML ✓
  2. Bash 直接重定向：cat > scene1.html << 'EOF'             → 每次包含完整 HTML ✓
  3. Bash 间接写入：cat > fix.js ... writeFileSync('*.html')  → 需区分：
     a. 无 readFileSync（从零生成，如 write_skeleton.js）     → 包含完整 HTML ✓
     b. 有 readFileSync（打补丁，如 fix.js）                   → 不包含完整 HTML ✗

精简规则：
  - 保留开头到第一次写入之前的所有消息
  - 保留最后一次「包含完整 HTML 且调用成功」的写入及其 tool result
  - 跳过所有中间修复循环和后续 check/screenshot

用法:
  source .venv/bin/activate
  python dedup_sft_data_v2.py
"""

import json
import os
import re

SFT_DATA_DIR = "/inspire/qb-ilm/project/ai4education/bishuzhen-CZXS24220022/edu_interact/EduInteract/output/sft_data"


def _get_text(msg):
    """Extract plain text from a message."""
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


def _collect_text_parts(msg):
    """Collect all text parts from a message as a list of strings."""
    content = msg.get("content", "")
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [
            p.get("text", "") for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        ]
    return []


def _is_write_html_call(msg):
    """Check if an assistant message writes to an HTML file.

    Matches three patterns:
      1. Write tool call: {"file_path": "scene1.html", ...}
      2. Bash direct redirect to .html: cat > scene1.html << 'EOF'
      3. Bash indirect write: ... writeFileSync('scene1.html', ...)
    """
    if msg.get("role") != "assistant":
        return False

    for text in _collect_text_parts(msg):
        # Pattern 1: Write tool with .html file_path
        if "Write" in text and re.search(r'"file_path"\s*:\s*"[^"]*\.html"', text):
            return True

        if "Bash" not in text:
            continue

        # Pattern 2: Bash direct redirect to .html (only in command value)
        cmd_match = re.search(r'"command"\s*:\s*"', text)
        if cmd_match:
            cmd_start = cmd_match.end()
            cmd_text = text[cmd_start:cmd_start + 300]
            if re.search(r'>\s*\w+\.html\b', cmd_text):
                return True

        # Pattern 3: Bash indirect write via fs.writeFileSync('xxx.html', ...)
        if re.search(r"writeFileSync\s*\(\s*['\"]\w+\.html", text):
            return True

    return False


def _has_full_html(msg):
    """Check if an assistant message's write contains the full HTML content.

    Returns True if the write contains complete HTML (no readFileSync dependency).

    - Write tool → always full HTML
    - Bash direct redirect to .html → always full HTML
    - Bash indirect write:
        - No readFileSync → full HTML (e.g. write_skeleton.js generating from scratch)
        - Has readFileSync → partial / patch, NOT full HTML
    """
    if msg.get("role") != "assistant":
        return False

    for text in _collect_text_parts(msg):
        # Write tool: always full HTML
        if "Write" in text and re.search(r'"file_path"\s*:\s*"[^"]*\.html"', text):
            return True

        if "Bash" not in text:
            continue

        # Bash direct redirect to .html: always full HTML
        cmd_match = re.search(r'"command"\s*:\s*"', text)
        if cmd_match:
            cmd_start = cmd_match.end()
            cmd_text = text[cmd_start:cmd_start + 300]
            if re.search(r'>\s*\w+\.html\b', cmd_text):
                return True

        # Bash indirect write: check if it has readFileSync
        if re.search(r"writeFileSync\s*\(\s*['\"]\w+\.html", text):
            # If it also has readFileSync, it's a patch script, not full HTML
            if re.search(r"readFileSync", text):
                return False
            # No readFileSync → generating from scratch → full HTML
            return True

    return False


def _is_failed_tool_result(msg):
    """Check if a tool result message indicates a failed tool call."""
    if msg.get("role") != "tool":
        return False
    text = _get_text(msg)
    if "Invalid input for tool" in text:
        return True
    if "JSON parsing failed" in text:
        return True
    if "Type validation failed" in text:
        return True
    if text.strip().startswith("Error:"):
        return True
    return False


def _find_last_full_html_write_index(messages):
    """Find the index of the last successful write that contains full HTML.

    Walks backwards through all write-html calls, returning the last one that:
      1. Contains full HTML (not a patch script with readFileSync)
      2. Its tool result does not indicate failure
    """
    candidates = []
    for i, msg in enumerate(messages):
        if _is_write_html_call(msg):
            candidates.append(i)

    for idx in reversed(candidates):
        # Skip writes that don't contain full HTML
        if not _has_full_html(messages[idx]):
            continue
        # Skip writes whose tool result indicates failure
        if idx + 1 < len(messages) and _is_failed_tool_result(messages[idx + 1]):
            continue
        return idx

    # No full-HTML write found — fallback to the last write of any kind
    for idx in reversed(candidates):
        if idx + 1 < len(messages) and _is_failed_tool_result(messages[idx + 1]):
            continue
        return idx

    return candidates[-1] if candidates else None


def _find_first_write_html_index(messages):
    """Find the index of the first Write HTML call."""
    for i, msg in enumerate(messages):
        if _is_write_html_call(msg):
            return i
    return None


def slim_messages(messages):
    """Remove intermediate fix loops, keeping only core conversation.

    Strategy:
      [0..first_write-1]  →  KEEP  (system, init, Read spec, Read 题图, etc.)
      [first_write]       →  SKIP  (first Write, replaced by last full-HTML Write)
      [first_write+1..last_write-1]  →  SKIP  (all intermediate fix loops)
      [last_write]        →  KEEP  (last full-HTML Write)
      [last_write+1]      →  KEEP  (tool result for last Write, if exists)
      [last_write+2..]    →  SKIP  (post-write checks, screenshots, etc.)
    """
    if len(messages) < 5:
        return messages

    first_write = _find_first_write_html_index(messages)
    last_write = _find_last_full_html_write_index(messages)

    # No Write found or only one Write — no change needed
    if first_write is None or last_write is None:
        return messages
    if first_write == last_write:
        # Only one Write, but still remove stuff after Write + tool result
        tool_result_end = last_write + 1
        # Check if the next message is the tool result
        if tool_result_end < len(messages) and messages[tool_result_end].get("role") == "tool":
            tool_result_end += 1
        return messages[:tool_result_end]

    # Build the slim version
    result = []

    # Part 1: everything before the first Write (system, init, Read spec, Read 题图)
    result.extend(messages[:first_write])

    # Part 2: the last full-HTML Write call
    result.append(messages[last_write])

    # Part 3: tool result for the last Write (if it's the next message)
    if last_write + 1 < len(messages) and messages[last_write + 1].get("role") == "tool":
        result.append(messages[last_write + 1])

    return result


def process_file(input_path, output_path):
    """Process a single JSONL file, return stats."""
    stats = {
        "total": 0,
        "shortened": 0,
        "unchanged": 0,
        "msgs_before": 0,
        "msgs_after": 0,
        "by_reduction": [],
    }

    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        skipped_bad = 0
        for line in fin:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                skipped_bad += 1
                continue
            messages = data["messages"]
            orig_len = len(messages)
            stats["total"] += 1
            stats["msgs_before"] += orig_len

            cleaned = slim_messages(messages)
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

    if skipped_bad:
        print(f"  Skipped {skipped_bad} malformed lines")
    return stats


def main():
    for fname in ["sft_outline.jsonl", "sft_plan.jsonl", "sft_code.jsonl"]:
        input_path = os.path.join(SFT_DATA_DIR, fname)
        output_path = os.path.join(SFT_DATA_DIR, fname.replace(".jsonl", "_slim.jsonl"))

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

    # 合并所有 slim 文件到 sft_all_slim.jsonl
    merge_path = os.path.join(SFT_DATA_DIR, "sft_all_slim.jsonl")
    slim_files = [
        "sft_outline_slim.jsonl",
        "sft_plan_slim.jsonl",
        "sft_code_slim.jsonl",
    ]
    total_lines = 0
    with open(merge_path, "w", encoding="utf-8") as fout:
        for slim_fname in slim_files:
            slim_fpath = os.path.join(SFT_DATA_DIR, slim_fname)
            if not os.path.exists(slim_fpath):
                print(f"[SKIP] {slim_fname} not found for merging")
                continue
            count = 0
            with open(slim_fpath, "r", encoding="utf-8") as fin:
                for line in fin:
                    fout.write(line)
                    count += 1
            total_lines += count
            print(f"  Merged {count} lines from {slim_fname}")

    print(f"\n{'='*60}")
    print(f"Merged output: {merge_path}")
    print(f"Total lines: {total_lines}")


if __name__ == "__main__":
    main()
