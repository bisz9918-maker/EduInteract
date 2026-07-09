#!/usr/bin/env python3
"""Build a model result JSON in output/results/* format.

This script combines:
  1. Evaluation scores from an evaluate.py summary JSON
     (for example: output/evaluate_qwen36_27b-sft/evaluation_summary.json)
  2. Token usage from a generation output directory
     (for example: output/exp_qwen36_27b-sft)

It writes a JSON with the same shape as:
  output/results/Qwen3.6-27B.json

Examples:
  # Rebuild Qwen3.6-27B.json if you have matching inputs:
  python build_model_result_json.py \
    --model Qwen3.6-27B \
    --input-dir output/exp_qwen36_27b \
    --eval-summary output/evaluate_qwen36_27b/evaluation_summary.json \
    --output output/results/Qwen3.6-27B.json

  # Build the SFT result from the current run:
  python build_model_result_json.py \
    --model Qwen3.6-27B-SFT \
    --input-dir output/exp_qwen36_27b-sft \
    --eval-summary output/evaluate_qwen36_27b-sft/evaluation_summary.json \
    --output output/results/Qwen3.6-27B-SFT.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


DIM_KEYS = [
    "dim1_accuracy",
    "dim2_interaction",
    "dim3_visual",
    "dim4_pedagogy",
    "dim5_logic_coherence",
]

EMPTY_TOKENS = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_token_file(path: Path) -> dict[str, int]:
    """Read one *_tokens.json file, returning zero tokens if it is missing."""
    if not path.exists():
        return dict(EMPTY_TOKENS)

    try:
        data = load_json(path)
    except Exception:
        return dict(EMPTY_TOKENS)

    input_tokens = int(data.get("input_tokens", 0) or 0)
    output_tokens = int(data.get("output_tokens", 0) or 0)
    total_tokens = int(data.get("total_tokens", input_tokens + output_tokens) or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def add_tokens(total: dict[str, int], item: dict[str, int]) -> None:
    total["input_tokens"] += int(item.get("input_tokens", 0) or 0)
    total["output_tokens"] += int(item.get("output_tokens", 0) or 0)
    total["total_tokens"] += int(item.get("total_tokens", 0) or 0)


def scene_number(scene_dir: Path) -> int:
    match = re.fullmatch(r"scene(\d+)", scene_dir.name)
    return int(match.group(1)) if match else 10**9


def discover_scene_dirs(topic_dir: Path) -> list[Path]:
    if not topic_dir.exists():
        return []
    return sorted(
        [p for p in topic_dir.iterdir() if p.is_dir() and re.fullmatch(r"scene\d+", p.name)],
        key=scene_number,
    )


def read_topic_tokens(input_dir: Path, topic: str) -> dict[str, Any]:
    """Read outline/implementation/code token usage for one topic."""
    topic_dir = input_dir / topic
    outline = read_token_file(topic_dir / f"{topic}_scene_outline_tokens.json")

    scenes: dict[str, Any] = {}
    implementation_total = dict(EMPTY_TOKENS)
    code_total = dict(EMPTY_TOKENS)

    for scene_dir in discover_scene_dirs(topic_dir):
        scene_name = scene_dir.name
        n = scene_name.removeprefix("scene")

        implementation = read_token_file(
            scene_dir / "subplans" / f"scene{n}_implementation_tokens.json"
        )

        code = read_token_file(scene_dir / "code" / f"scene{n}_code_tokens.json")
        if code["total_tokens"] == 0:
            # Older outputs sometimes have a different prefix but still end with _code_tokens.json.
            code_token_files = sorted((scene_dir / "code").glob("*_code_tokens.json"))
            if code_token_files:
                code = read_token_file(code_token_files[0])

        scenes[scene_name] = {
            "implementation": implementation,
            "code": code,
        }
        add_tokens(implementation_total, implementation)
        add_tokens(code_total, code)

    stages = {
        "outline": {
            "input_tokens": outline["input_tokens"],
            "output_tokens": outline["output_tokens"],
        },
        "implementation": {
            "input_tokens": implementation_total["input_tokens"],
            "output_tokens": implementation_total["output_tokens"],
        },
        "code": {
            "input_tokens": code_total["input_tokens"],
            "output_tokens": code_total["output_tokens"],
        },
    }
    stages["total_input"] = (
        stages["outline"]["input_tokens"]
        + stages["implementation"]["input_tokens"]
        + stages["code"]["input_tokens"]
    )
    stages["total_output"] = (
        stages["outline"]["output_tokens"]
        + stages["implementation"]["output_tokens"]
        + stages["code"]["output_tokens"]
    )

    return {
        "outline": outline,
        "scenes": scenes,
        "stages": stages,
    }


def build_evaluation(result: dict[str, Any]) -> dict[str, Any]:
    """Convert one evaluation_summary result item to output/results evaluation shape."""
    evaluation: dict[str, Any] = {}
    for key in ["total_score", *DIM_KEYS, "render_check", "status", "error"]:
        if key in result:
            evaluation[key] = result[key]
    return evaluation


def has_dim_scores(topic_item: dict[str, Any]) -> bool:
    evaluation = topic_item.get("evaluation", {})
    return any(key in evaluation for key in DIM_KEYS)


def build_result(model: str, input_dir: Path, eval_summary_path: Path) -> dict[str, Any]:
    eval_summary = load_json(eval_summary_path)
    results = eval_summary.get("results")
    if not isinstance(results, list):
        raise ValueError(f"{eval_summary_path} does not contain a list field named 'results'")

    total_topics = int(eval_summary.get("total", len(results)) or len(results))
    topics: list[dict[str, Any]] = []

    total_token_usage: dict[str, Any] = {
        "outline": {"input_tokens": 0, "output_tokens": 0},
        "implementation": {"input_tokens": 0, "output_tokens": 0},
        "code": {"input_tokens": 0, "output_tokens": 0},
        "total_input": 0,
        "total_output": 0,
    }

    for result in results:
        topic = result["topic"]
        tokens = read_topic_tokens(input_dir, topic)
        stages = tokens["stages"]

        for stage in ["outline", "implementation", "code"]:
            total_token_usage[stage]["input_tokens"] += stages[stage]["input_tokens"]
            total_token_usage[stage]["output_tokens"] += stages[stage]["output_tokens"]
        total_token_usage["total_input"] += stages["total_input"]
        total_token_usage["total_output"] += stages["total_output"]

        topics.append(
            {
                "topic": topic,
                "evaluation": build_evaluation(result),
                "tokens": tokens,
            }
        )

    # Match output/results/Qwen3.6-27B.json convention:
    # averages for score dimensions are over all total_topics, missing/error items count as 0.
    total_score_sum = sum(
        float(item.get("evaluation", {}).get("total_score", 0) or 0) for item in topics
    )
    dim_sums = {
        key: sum(float(item.get("evaluation", {}).get(key, 0) or 0) for item in topics)
        for key in DIM_KEYS
    }

    evaluated = sum(1 for item in topics if has_dim_scores(item))
    avg_divisor = evaluated or total_topics or 1

    avg_token_usage = {
        "outline": {
            "input_tokens": round(total_token_usage["outline"]["input_tokens"] / avg_divisor),
            "output_tokens": round(total_token_usage["outline"]["output_tokens"] / avg_divisor),
        },
        "implementation": {
            "input_tokens": round(total_token_usage["implementation"]["input_tokens"] / avg_divisor),
            "output_tokens": round(total_token_usage["implementation"]["output_tokens"] / avg_divisor),
        },
        "code": {
            "input_tokens": round(total_token_usage["code"]["input_tokens"] / avg_divisor),
            "output_tokens": round(total_token_usage["code"]["output_tokens"] / avg_divisor),
        },
        "total_input": round(total_token_usage["total_input"] / avg_divisor),
        "total_output": round(total_token_usage["total_output"] / avg_divisor),
    }

    summary: dict[str, Any] = {
        "model": model,
        "total_topics": total_topics,
        "evaluated": evaluated,
    }
    for key in ["completed", "skipped", "render_failed", "errors"]:
        if key in eval_summary:
            summary[key] = eval_summary[key]

    summary.update(
        {
            "avg_total_score": total_score_sum / total_topics if total_topics else 0,
            "avg_dim_scores": {
                key: round(dim_sums[key] / total_topics, 2) if total_topics else 0
                for key in DIM_KEYS
            },
            "total_token_usage": total_token_usage,
            "avg_token_usage_per_topic": avg_token_usage,
        }
    )

    return {"summary": summary, "topics": topics}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build output/results/<model>.json from an evaluate.py summary and generation token files."
    )
    parser.add_argument("--model", default="Qwen3.6-27B", help="Model name written to summary.model")
    parser.add_argument(
        "--input-dir",
        default="output/exp_qwen36_27b",
        type=Path,
        help="Generation output directory containing problem_* folders",
    )
    parser.add_argument(
        "--eval-summary",
        default="output/evaluate_qwen36_27b/evaluation_summary.json",
        type=Path,
        help="evaluation_summary.json produced by evaluate.py",
    )
    parser.add_argument(
        "--output",
        default="output/results/Qwen3.6-27B.json",
        type=Path,
        help="Output result JSON path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_result(args.model, args.input_dir, args.eval_summary)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    summary = result["summary"]
    print(f"Saved: {args.output}")
    print(f"Model: {summary['model']}")
    print(f"Topics: {summary['total_topics']}")
    print(f"Evaluated: {summary['evaluated']}")
    if "completed" in summary:
        print(
            f"Completed: {summary.get('completed')} | Skipped: {summary.get('skipped')} | "
            f"Render failed: {summary.get('render_failed')} | Errors: {summary.get('errors')}"
        )
    print(f"Avg total score: {summary['avg_total_score']:.4f}")
    print(
        "Total tokens: "
        f"input={summary['total_token_usage']['total_input']} "
        f"output={summary['total_token_usage']['total_output']}"
    )


if __name__ == "__main__":
    main()
