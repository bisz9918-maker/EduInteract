#!/usr/bin/env python3
"""Fix token files by recalculating from trace step-level usage.

AI SDK's streamText returns run-level usage that only includes the last
step's inputTokens, undercounting actual API cost by 50-95%. This script
recalculates from step-level data (output.response.usage) which has the
real per-call token counts from the provider.

Token file -> Trace file mapping:
  {topic}/{topic}_scene_outline_tokens.json  <-  traces/{topic}_{model}_outline.json
  {topic}/scene{N}/code/scene{N}_code_tokens.json  <-  traces/{topic}_{model}_scene{N}_code.json
  {topic}/scene{N}/subplans/scene{N}_implementation_tokens.json  <-  traces/{topic}_{model}_scene{N}_plan.json
"""

import json
import os
import glob
import re
import sys


def aggregate_step_usage(steps):
    """Sum token usage across all completed model_call steps.

    Returns dict with snake_case keys matching token file format:
      input_tokens, output_tokens, total_tokens
    """
    agg = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for step in steps:
        if step.get("stepType") != "model_call" or step.get("status") != "completed":
            continue
        resp_usage = step.get("output", {}).get("response", {}).get("usage")
        if isinstance(resp_usage, dict):
            # Trace stores camelCase keys from AI SDK
            agg["input_tokens"] += resp_usage.get("inputTokens", 0) or 0
            agg["output_tokens"] += resp_usage.get("outputTokens", 0) or 0
            agg["total_tokens"] += resp_usage.get("totalTokens", 0) or 0
    return agg


def _topic_prefix(topic):
    """Strip subject suffix like _physics_g9 from topic, returning the problem_N prefix used in trace filenames."""
    m = re.match(r"(problem_\d+)", topic)
    return m.group(1) if m else topic


def find_trace_for_token(exp_dir, token_file, model_names):
    """Find the trace file corresponding to a token file.

    Token file paths:
      {topic}/{topic}_scene_outline_tokens.json
      {topic}/scene{N}/code/scene{N}_code_tokens.json
      {topic}/scene{N}/subplans/scene{N}_implementation_tokens.json

    Trace file paths:
      traces/{short_topic}_{model}_outline.json
      traces/{short_topic}_{model}_scene{N}_code.json
      traces/{short_topic}_{model}_scene{N}_plan.json
    """
    traces_dir = os.path.join(exp_dir, "traces")
    if not os.path.isdir(traces_dir):
        return None

    rel = os.path.relpath(token_file, exp_dir)
    parts = rel.split(os.sep)

    topic = parts[0]  # e.g. problem_0_physics_g9
    basename = os.path.splitext(parts[-1])[0]  # strip .json, keep _tokens suffix
    # Strip trailing _tokens
    if basename.endswith("_tokens"):
        basename = basename[:-7]

    # Determine trace suffix based on path structure and basename
    if len(parts) == 2 and basename == f"{topic}_scene_outline":
        trace_suffix = "_outline.json"
    elif len(parts) == 4 and parts[2] == "code" and basename.endswith("_code"):
        scene_num = basename.replace("scene", "").replace("_code", "")
        trace_suffix = f"_scene{scene_num}_code.json"
    elif len(parts) == 4 and parts[2] == "subplans" and basename.endswith("_implementation"):
        scene_num = basename.replace("scene", "").replace("_implementation", "")
        trace_suffix = f"_scene{scene_num}_plan.json"
    else:
        return None

    short_topic = _topic_prefix(topic)

    # Try short topic first (most common pattern)
    for model_name in model_names:
        trace_file = os.path.join(traces_dir, f"{short_topic}_{model_name}{trace_suffix}")
        if os.path.isfile(trace_file):
            return trace_file

    # Try long topic
    for model_name in model_names:
        trace_file = os.path.join(traces_dir, f"{topic}_{model_name}{trace_suffix}")
        if os.path.isfile(trace_file):
            return trace_file

    # Glob fallback with short topic
    matches = sorted(glob.glob(os.path.join(traces_dir, f"{short_topic}_*{trace_suffix}")))
    if matches:
        return matches[0]

    # Glob fallback with long topic
    matches = sorted(glob.glob(os.path.join(traces_dir, f"{topic}_*{trace_suffix}")))
    return matches[0] if matches else None


def get_model_names(exp_dir):
    """Extract model name variants from trace files."""
    traces_dir = os.path.join(exp_dir, "traces")
    if not os.path.isdir(traces_dir):
        return []
    names = set()
    for f in os.listdir(traces_dir):
        if not f.endswith(".json"):
            continue
        # problem_0_ModelName_outline.json -> ModelName
        # Remove problem_0_ prefix and _outline/_scene suffix
        parts = f.split("_", 2)  # ['problem', '0', 'ModelName_outline.json']
        if len(parts) >= 3:
            rest = parts[2]
            for suffix in ("_outline.json", "_plan.json", "_code.json"):
                rest = rest.replace(suffix, "")
            # Also remove _sceneN parts
            rest = re.sub(r"_scene\d+$", "", rest)
            if rest:
                names.add(rest)
    return list(names)


def fix_exp(exp_dir, dry_run=False):
    """Fix all token files in one experiment directory."""
    exp_name = os.path.basename(exp_dir)
    model_names = get_model_names(exp_dir)

    if not model_names:
        print(f"  [{exp_name}] No traces found, skipping")
        return 0, 0, 0

    token_files = []
    for root, dirs, files in os.walk(exp_dir):
        for f in files:
            if f.endswith("_tokens.json"):
                token_files.append(os.path.join(root, f))

    fixed = 0
    skipped = 0
    errors = 0

    for tf in token_files:
        trace_file = find_trace_for_token(exp_dir, tf, model_names)
        if not trace_file:
            skipped += 1
            continue

        try:
            with open(trace_file) as fh:
                trace = json.load(fh)
        except Exception as e:
            print(f"  ERROR reading {trace_file}: {e}")
            errors += 1
            continue

        agg = aggregate_step_usage(trace.get("steps", []))

        if agg["total_tokens"] == 0:
            skipped += 1
            continue

        try:
            with open(tf) as fh:
                old = json.load(fh)
        except Exception:
            old = {}

        # Check if already correct
        if (old.get("total_tokens") == agg["total_tokens"] and
                old.get("input_tokens") == agg["input_tokens"] and
                old.get("output_tokens") == agg["output_tokens"]):
            skipped += 1
            continue

        if dry_run:
            print(f"  {os.path.relpath(tf, exp_dir)}: "
                  f"total {old.get('total_tokens', 0)} -> {agg['total_tokens']} "
                  f"({old.get('total_tokens', 0) / max(agg['total_tokens'], 1) * 100:.0f}% of actual)")
            fixed += 1
        else:
            with open(tf, "w") as fh:
                json.dump(agg, fh, indent=2)
            fixed += 1

    return fixed, skipped, errors


def main():
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("=== DRY RUN (no files will be modified) ===\n")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "output")

    total_fixed = 0
    total_skipped = 0
    total_errors = 0

    for exp_name in sorted(os.listdir(output_dir)):
        exp_dir = os.path.join(output_dir, exp_name)
        if not os.path.isdir(exp_dir):
            continue
        if not os.path.isdir(os.path.join(exp_dir, "traces")):
            continue

        fixed, skipped, errors = fix_exp(exp_dir, dry_run=dry_run)
        if fixed > 0 or errors > 0:
            print(f"[{exp_name}] fixed={fixed}  skipped={skipped}  errors={errors}")
        total_fixed += fixed
        total_skipped += skipped
        total_errors += errors

    print(f"\nTotal: fixed={total_fixed}  skipped={total_skipped}  errors={total_errors}")


if __name__ == "__main__":
    main()
