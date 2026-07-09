"""
Collect experiment results and generate report (CSV + charts).
Usage: python generate_report.py
"""
import json
import re
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
from matplotlib.patches import Patch

OUTPUT_DIR = Path(__file__).parent / "output"

# ── Model name mapping ──
MODEL_MAP = {
    "exp_Gemini-3.1-Pro": "Gemini-3.1-Pro",
    "exp_kimik26": "Kimi-K2.6",
    "exp_qwen35_122b": "Qwen3.5-122B-A10B",
    "exp_qwen35_397b": "Qwen3.5-397B-A17B-FP8",
    "exp_qwen36_27b": "Qwen3.6-27B",
    "exp_Ministral-3-14B-Instruct-2512": "Ministral-3-14B",
    "exp_Mistral-Large-3-675B-Instruct-2512": "Mistral-Large-3-675B",
}

EVAL_DIR_MAP = {
    "exp_Gemini-3.1-Pro": "evaluate_Gemini-3.1-Pro",
    "exp_kimik26": "evaluate_kimi26",
    "exp_qwen35_122b": "evaluate_qwen35_122b",
    "exp_qwen35_397b": "evaluate_qwen35_397b",
    "exp_qwen36_27b": "evaluate_qwen36_27b",
}

# Input / output price per million tokens
PRICES = {
    "Gemini-3.1-Pro": (2.00, 12.00),
    "Kimi-K2.6": (0.73, 3.49),
    "Qwen3.5-122B-A10B": (0.40, 3.20),
    "Qwen3.5-397B-A17B-FP8": (0.60, 3.60),
    "Qwen3.6-27B": (0.30, 3.20),
}

# ═══════════════════════════════════════════════════════════
#  Part 1: Collect per-model JSON  (from collect_results.py)
# ═══════════════════════════════════════════════════════════

def parse_evaluation_report(report_path: Path) -> dict | None:
    if not report_path.exists():
        return None
    text = report_path.read_text(encoding="utf-8")
    result = {}
    m = re.search(r"<total_score>([^<]+)</total_score>", text)
    if m:
        result["total_score"] = float(m.group(1))
    for tag in ["dim1_accuracy", "dim2_interaction", "dim3_visual",
                 "dim4_pedagogy", "dim5_logic_coherence"]:
        m = re.search(rf'<{tag}\s+score="([\d.]+)"', text)
        if m:
            result[tag] = float(m.group(1))
    render = re.findall(r'<(scene\d+)\s+status="(\w+)"', text)
    if render:
        result["render_check"] = {s: st for s, st in render}
    return result if result else None


def collect_token_usage(exp_dir: Path, topic: str) -> dict:
    topic_dir = exp_dir / topic
    tokens = {}

    outline_files = list(topic_dir.glob("*_scene_outline_tokens.json"))
    for f in outline_files:
        with open(f) as fh:
            data = json.load(fh)
        tokens["outline"] = {
            "input_tokens": data.get("input_tokens", 0),
            "output_tokens": data.get("output_tokens", 0),
            "total_tokens": data.get("total_tokens", 0),
        }

    scene_tokens = {}
    for scene_dir in sorted(topic_dir.glob("scene*")):
        scene_name = scene_dir.name
        scene_data = {}

        impl_files = list(scene_dir.glob("subplans/*_implementation_tokens.json"))
        impl_files += list(scene_dir.glob("*_implementation_tokens.json"))
        for f in impl_files:
            with open(f) as fh:
                data = json.load(fh)
            scene_data["implementation"] = {
                "input_tokens": data.get("input_tokens", 0),
                "output_tokens": data.get("output_tokens", 0),
                "total_tokens": data.get("total_tokens", 0),
            }

        code_files = list(scene_dir.glob("code/*_code_tokens.json"))
        for f in code_files:
            with open(f) as fh:
                data = json.load(fh)
            scene_data["code"] = {
                "input_tokens": data.get("input_tokens", 0),
                "output_tokens": data.get("output_tokens", 0),
                "total_tokens": data.get("total_tokens", 0),
            }

        subplan_files = list(scene_dir.glob("subplans/*_subplan*_tokens.json"))
        for f in subplan_files:
            with open(f) as fh:
                data = json.load(fh)
            key = f.stem.replace(f"{scene_name}_", "").replace("_tokens", "")
            scene_data[key] = {
                "input_tokens": data.get("input_tokens", 0),
                "output_tokens": data.get("output_tokens", 0),
                "total_tokens": data.get("total_tokens", 0),
            }

        if scene_data:
            scene_tokens[scene_name] = scene_data

    if scene_tokens:
        tokens["scenes"] = scene_tokens

    timing_file = topic_dir / "timing.json"
    if timing_file.exists():
        with open(timing_file) as fh:
            timing = json.load(fh)
        usage = timing.get("token_usage", {})
        detailed = usage.get("planner_model_detailed", {})
        scene_detailed = usage.get("scene_model_detailed", {})

        outline = detailed.get("scene_outline", {})
        outline_input = outline.get("input_tokens", 0)
        outline_output = outline.get("output_tokens", 0)

        impl_plans = detailed.get("implementation_plans", {})
        impl_input = sum(v.get("input_tokens", 0) for v in impl_plans.values())
        impl_output = sum(v.get("output_tokens", 0) for v in impl_plans.values())

        code_input = sum(v.get("input_tokens", 0) for v in scene_detailed.values())
        code_output = sum(v.get("output_tokens", 0) for v in scene_detailed.values())

        tokens["stages"] = {
            "outline": {"input_tokens": outline_input, "output_tokens": outline_output},
            "implementation": {"input_tokens": impl_input, "output_tokens": impl_output},
            "code": {"input_tokens": code_input, "output_tokens": code_output},
            "total_input": outline_input + impl_input + code_input,
            "total_output": outline_output + impl_output + code_output,
        }

    return tokens


def collect_model(exp_dir_name: str) -> dict | None:
    exp_dir = OUTPUT_DIR / exp_dir_name
    model_name = MODEL_MAP.get(exp_dir_name, exp_dir_name)
    eval_dir_name = EVAL_DIR_MAP.get(exp_dir_name)
    eval_dir = OUTPUT_DIR / eval_dir_name if eval_dir_name else None

    if not exp_dir.exists():
        return None

    topics = sorted([d.name for d in exp_dir.iterdir()
                     if d.is_dir() and d.name.startswith("problem_")])
    results = []

    for topic in topics:
        entry = {"topic": topic}

        if eval_dir:
            report_path = eval_dir / topic / "evaluation_report.xml"
            eval_data = parse_evaluation_report(report_path)
            if eval_data:
                entry["evaluation"] = eval_data

        token_data = collect_token_usage(exp_dir, topic)
        if token_data:
            entry["tokens"] = token_data

        results.append(entry)

    scored = [r for r in results if r.get("evaluation", {}).get("total_score", 0) > 0]
    # avg_total_score denominator = scored + no_code (missing code counts as 0)
    # agent-0-score topics are excluded from denominator
    no_code = [r for r in results
               if not list((exp_dir / r["topic"] / "doc").glob("scene*.html"))]
    denom = max(len(scored) + len(no_code), 1)
    score_sum = sum(r["evaluation"]["total_score"] for r in scored)  # no_code = 0
    summary = {
        "model": model_name,
        "total_topics": len(topics),
        "evaluated": len(scored),
        "avg_total_score": score_sum / denom,
        "avg_dim_scores": {},
        "total_token_usage": {},
    }

    dim_tags = ["dim1_accuracy", "dim2_interaction", "dim3_visual",
                "dim4_pedagogy", "dim5_logic_coherence"]
    for tag in dim_tags:
        vals = [r["evaluation"][tag] for r in scored if tag in r.get("evaluation", {})]
        if vals:
            summary["avg_dim_scores"][tag] = round(sum(vals) / denom, 2)

    for r in scored:
        stages = r.get("tokens", {}).get("stages", {})
        for stage_name in ["outline", "implementation", "code"]:
            stage = stages.get(stage_name, {})
            summary["total_token_usage"][stage_name] = {
                "input_tokens": summary["total_token_usage"]
                    .get(stage_name, {}).get("input_tokens", 0)
                    + stage.get("input_tokens", 0),
                "output_tokens": summary["total_token_usage"]
                    .get(stage_name, {}).get("output_tokens", 0)
                    + stage.get("output_tokens", 0),
            }
        summary["total_token_usage"]["total_input"] = \
            summary["total_token_usage"].get("total_input", 0) + stages.get("total_input", 0)
        summary["total_token_usage"]["total_output"] = \
            summary["total_token_usage"].get("total_output", 0) + stages.get("total_output", 0)

    n = max(len(scored), 1)
    summary["avg_token_usage_per_topic"] = {}
    for stage_name in ["outline", "implementation", "code"]:
        stage = summary["total_token_usage"].get(stage_name, {})
        summary["avg_token_usage_per_topic"][stage_name] = {
            "input_tokens": round(stage.get("input_tokens", 0) / n),
            "output_tokens": round(stage.get("output_tokens", 0) / n),
        }
    summary["avg_token_usage_per_topic"]["total_input"] = \
        round(summary["total_token_usage"].get("total_input", 0) / n)
    summary["avg_token_usage_per_topic"]["total_output"] = \
        round(summary["total_token_usage"].get("total_output", 0) / n)

    return {"summary": summary, "topics": results}


def save_json_results(results_dir: Path):
    """Save per-model JSON files. Returns dict {model_name: data}."""
    all_data = {}
    for exp_dir_name in MODEL_MAP:
        data = collect_model(exp_dir_name)
        if data is None:
            continue
        model_name = MODEL_MAP[exp_dir_name]
        out_path = results_dir / f"{model_name}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        all_data[model_name] = data
        s = data["summary"]
        print(f"  {model_name}: {s['evaluated']}/{s['total_topics']} evaluated, "
              f"avg_score={s['avg_total_score']:.2f}")
    return all_data


# ═══════════════════════════════════════════════════════════
#  Part 2: CSV summary tables
# ═══════════════════════════════════════════════════════════

def build_csv_tables(all_data: dict, results_dir: Path):
    EXP_MAP = {v: k for k, v in MODEL_MAP.items()}

    # ── Table 1: scores_summary.csv ──
    rows_scores = []
    for model_name in [MODEL_MAP[k] for k in MODEL_MAP]:
        if model_name not in all_data:
            continue
        data = all_data[model_name]
        s = data["summary"]
        exp_dir = OUTPUT_DIR / EXP_MAP[model_name]
        total = s["total_topics"]
        evaluated = s["evaluated"]

        has_code = 0
        render_ok = 0
        for topic_data in data["topics"]:
            topic = topic_data["topic"]
            doc_files = list((exp_dir / topic / "doc").glob("scene*.html"))
            if doc_files:
                has_code += 1
                eval_data = topic_data.get("evaluation", {})
                render_check = eval_data.get("render_check", {})
                if not any(st == "failed" for st in render_check.values()):
                    render_ok += 1

        dim = s.get("avg_dim_scores", {})
        rows_scores.append({
            "模型": model_name,
            "总题数": total,
            "生成code": has_code,
            "渲染成功": render_ok,
            "成功率(%)": round(render_ok / total * 100, 1) if total else 0,
            "已评测": evaluated,
            "平均总分": round(s["avg_total_score"], 2),
            "dim1_accuracy": round(dim.get("dim1_accuracy", 0), 2),
            "dim2_interaction": round(dim.get("dim2_interaction", 0), 2),
            "dim3_visual": round(dim.get("dim3_visual", 0), 2),
            "dim4_pedagogy": round(dim.get("dim4_pedagogy", 0), 2),
            "dim5_logic_coherence": round(dim.get("dim5_logic_coherence", 0), 2),
        })

    csv1 = results_dir / "scores_summary.csv"
    with open(csv1, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=rows_scores[0].keys())
        w.writeheader()
        w.writerows(rows_scores)
    print(f"  {csv1.name}")

    # ── Table 2: token_cost_summary.csv ──
    rows_tokens = []
    for model_name in [MODEL_MAP[k] for k in MODEL_MAP]:
        if model_name not in all_data:
            continue
        s = all_data[model_name]["summary"]
        evaluated = s["evaluated"]
        avg = s.get("avg_token_usage_per_topic", {})
        total_usage = s.get("total_token_usage", {})

        total_in = avg.get("total_input", 0)
        total_out = avg.get("total_output", 0)

        prices = PRICES.get(model_name)
        has_price = prices is not None

        cost_per_topic = 0
        total_cost = 0
        if has_price:
            cost_per_topic = (total_in / 1e6) * prices[0] + (total_out / 1e6) * prices[1]
            total_cost = ((total_usage.get("total_input", 0) / 1e6) * prices[0]
                          + (total_usage.get("total_output", 0) / 1e6) * prices[1])

        rows_tokens.append({
            "模型": model_name,
            "评测题数(非0分)": evaluated,
            "outline输入": avg.get("outline", {}).get("input_tokens", 0),
            "outline输出": avg.get("outline", {}).get("output_tokens", 0),
            "implementation输入": avg.get("implementation", {}).get("input_tokens", 0),
            "implementation输出": avg.get("implementation", {}).get("output_tokens", 0),
            "code输入": avg.get("code", {}).get("input_tokens", 0),
            "code输出": avg.get("code", {}).get("output_tokens", 0),
            "每题平均输入": total_in,
            "每题平均输出": total_out,
            "每题平均总token": total_in + total_out,
            "输入价格($/M)": prices[0] if has_price else "",
            "输出价格($/M)": prices[1] if has_price else "",
            "每题平均费用($)": round(cost_per_topic, 4) if has_price else "",
            "总费用($)": round(total_cost, 2) if has_price else "",
        })

    csv2 = results_dir / "token_cost_summary.csv"
    with open(csv2, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=rows_tokens[0].keys())
        w.writeheader()
        w.writerows(rows_tokens)
    print(f"  {csv2.name}")

    return rows_scores, rows_tokens


# ═══════════════════════════════════════════════════════════
#  Part 3: Charts
# ═══════════════════════════════════════════════════════════

def _setup_font():
    plt.rcParams["font.family"] = "serif"
    plt.rcParams["font.serif"] = ["Times New Roman", "DejaVu Serif"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["mathtext.fontset"] = "stix"


def _draw_radar_subplot(ax, labels, model_values, model_names, colors, title):
    """Draw a single radar subplot."""
    n = len(labels)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    angles += angles[:1]

    for idx, (values, name) in enumerate(zip(model_values, model_names)):
        vals = values + values[:1]
        ax.plot(angles, vals, "o-", linewidth=1.8, label=name,
                color=colors[idx % len(colors)], markersize=5)
        ax.fill(angles, vals, alpha=0.06, color=colors[idx % len(colors)])

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=9, fontweight="bold")
    ax.set_ylim(0, 5.5)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(["1", "2", "3", "4", "5"], fontsize=8)
    ax.yaxis.grid(True, linestyle="--", alpha=0.5)
    ax.set_title(title, fontsize=12, fontweight="bold", pad=18)


def compute_group_scores(all_data: dict, group_key: str) -> dict:
    """Compute per-model average total_score grouped by grade or subject.
    Denominator = scored topics + no-code topics (same as build_breakdown_csvs).
    Topics with code but score=0 are excluded from denominator.
    Returns {group_label: {model: overall_avg_score}}
    """
    EXP_MAP = {v: k for k, v in MODEL_MAP.items()}
    MODELS = [m for m in MODEL_MAP.values()
              if m not in ("Ministral-3-14B", "Mistral-Large-3-675B")]

    GRADE_LABELS = {"g6": "Primary", "g9": "Junior", "g12": "Senior"}
    SUBJECT_LABELS = {
        "physics": "Physics", "chemistry": "Chemistry", "math": "Math",
        "biology": "Biology", "geography": "Geography",
    }
    label_map = GRADE_LABELS if group_key == "grade" else SUBJECT_LABELS
    order = ["g6", "g9", "g12"] if group_key == "grade" else \
            ["physics", "chemistry", "math", "biology", "geography"]

    result = {}
    for gk in order:
        group_label = label_map[gk]
        result[group_label] = {}
        for model in MODELS:
            data = all_data[model]
            exp_dir = OUTPUT_DIR / EXP_MAP[model]
            scored_sum = 0.0
            scored_n = 0
            no_code = 0
            for td in data["topics"]:
                parts = td["topic"].split("_")
                grade, subject = parts[3], parts[2]
                val = grade if group_key == "grade" else subject
                if val != gk:
                    continue
                score = td.get("evaluation", {}).get("total_score", 0)
                doc_files = list((exp_dir / td["topic"] / "doc").glob("scene*.html"))
                if score > 0:
                    scored_sum += score
                    scored_n += 1
                elif not doc_files:
                    no_code += 1
            denom = scored_n + no_code
            avg = scored_sum / denom if denom > 0 else 0
            result[group_label][model] = round(avg, 2)
    return result


def plot_radar(scores_rows: list[dict], all_data: dict, results_dir: Path):
    """Three side-by-side radar charts: by dimension, by subject, by grade."""
    _setup_font()

    models = [r for r in scores_rows if r["平均总分"] > 0]
    model_names = [r["模型"] for r in models]
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]

    # ── Left: By Dimension ──
    dims = ["dim1_accuracy", "dim2_interaction", "dim3_visual",
            "dim4_pedagogy", "dim5_logic_coherence"]
    dim_labels = ["Prob.\nAlign.", "Interact.", "Visual\nQual.", "Pedagogy", "Logic\nCoh."]
    dim_values = [[float(r[d]) for d in dims] for r in models]

    # ── Middle: By Subject ──
    subject_data = compute_group_scores(all_data, "subject")
    subject_labels = ["Physics", "Chemistry", "Math", "Biology", "Geography"]
    subject_values = []
    for r in models:
        model = r["模型"]
        vals = [subject_data.get(s, {}).get(model, 0) for s in subject_labels]
        subject_values.append(vals)

    # ── Right: By Grade ──
    grade_data = compute_group_scores(all_data, "grade")
    grade_labels = ["Primary", "Junior", "Senior"]
    grade_values = []
    for r in models:
        model = r["模型"]
        vals = [grade_data.get(g, {}).get(model, 0) for g in grade_labels]
        grade_values.append(vals)

    # ── Draw 3 subplots ──
    fig, axes = plt.subplots(1, 3, figsize=(18, 6.5),
                              subplot_kw=dict(polar=True))

    _draw_radar_subplot(axes[0], dim_labels, dim_values, model_names,
                        colors, "By Evaluation Dimension")
    _draw_radar_subplot(axes[1], subject_labels, subject_values, model_names,
                        colors, "By Subject")
    _draw_radar_subplot(axes[2], grade_labels, grade_values, model_names,
                        colors, "By Grade Level")

    # Shared legend
    handles = [plt.Line2D([0], [0], color=colors[i], linewidth=2, marker="o",
               markersize=5, label=model_names[i])
               for i in range(len(model_names))]
    fig.legend(handles=handles, loc="lower center", ncol=len(model_names),
               fontsize=10, frameon=True, fancybox=True, shadow=True,
               bbox_to_anchor=(0.5, -0.02))

    plt.tight_layout(rect=[0, 0.06, 1, 1])
    out = results_dir / "radar_chart.png"
    plt.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"  {out.name}")

    # Also save PDF for LaTeX
    out_pdf = results_dir / "radar_chart.pdf"
    fig, axes = plt.subplots(1, 3, figsize=(18, 6.5),
                              subplot_kw=dict(polar=True))
    _draw_radar_subplot(axes[0], dim_labels, dim_values, model_names,
                        colors, "By Evaluation Dimension")
    _draw_radar_subplot(axes[1], subject_labels, subject_values, model_names,
                        colors, "By Subject")
    _draw_radar_subplot(axes[2], grade_labels, grade_values, model_names,
                        colors, "By Grade Level")
    fig.legend(handles=handles, loc="lower center", ncol=len(model_names),
               fontsize=10, frameon=True, fancybox=True, shadow=True,
               bbox_to_anchor=(0.5, -0.02))
    plt.tight_layout(rect=[0, 0.06, 1, 1])
    plt.savefig(out_pdf, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"  {out_pdf.name}")


def plot_token_bar(token_rows: list[dict], results_dir: Path):
    """Stacked bar chart: input/output tokens per model, split by stage."""
    _setup_font()

    models = [r for r in token_rows if r["评测题数(非0分)"] > 0]
    n = len(models)
    x = np.arange(n)
    bar_w = 0.32
    stage_colors = {"outline": "#4e79a7", "implementation": "#f28e2b", "code": "#e15759"}

    fig, ax = plt.subplots(figsize=(12, 6))

    for i, row in enumerate(models):
        oi = int(row["outline输入"]);    ii = int(row["implementation输入"])
        ci = int(row["code输入"])
        oo = int(row["outline输出"]);    io = int(row["implementation输出"])
        co = int(row["code输出"])

        # Input bar
        p = x[i] - bar_w / 2
        ax.bar(p, oi, bar_w, color=stage_colors["outline"], edgecolor="white", linewidth=0.5)
        ax.bar(p, ii, bar_w, bottom=oi, color=stage_colors["implementation"],
               edgecolor="white", linewidth=0.5)
        ax.bar(p, ci, bar_w, bottom=oi + ii, color=stage_colors["code"],
               edgecolor="white", linewidth=0.5)

        # Output bar
        p = x[i] + bar_w / 2
        ax.bar(p, oo, bar_w, color=stage_colors["outline"], edgecolor="white", linewidth=0.5)
        ax.bar(p, io, bar_w, bottom=oo, color=stage_colors["implementation"],
               edgecolor="white", linewidth=0.5)
        ax.bar(p, co, bar_w, bottom=oo + io, color=stage_colors["code"],
               edgecolor="white", linewidth=0.5)

    ax.set_yscale("log")
    ax.set_ylabel("Token Count (log scale)", fontsize=12, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels([r["模型"] for r in models],
                       fontsize=10, fontweight="bold", rotation=15, ha="right")
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.legend(handles=[
        Patch(facecolor=stage_colors["outline"], label="Outline"),
        Patch(facecolor=stage_colors["implementation"], label="Implementation"),
        Patch(facecolor=stage_colors["code"], label="Code"),
    ], loc="upper right", fontsize=11, frameon=True, fancybox=True)
    ax.set_title("Average Token Usage per Problem by Stage",
                 fontsize=14, fontweight="bold", pad=12)

    plt.tight_layout()
    out = results_dir / "token_bar_chart.png"
    plt.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"  {out.name}")


def plot_cost_vs_quality(scores_rows: list[dict], token_rows: list[dict],
                         results_dir: Path):
    """Scatter plot: cost per problem (x) vs overall score (y)."""
    _setup_font()

    scores = {r["模型"]: r["平均总分"] for r in scores_rows}
    data = {}
    for r in token_rows:
        model = r["模型"]
        avg_score = scores.get(model, 0)
        cost_str = r["每题平均费用($)"]
        if cost_str != "" and avg_score > 0:
            data[model] = (float(cost_str), avg_score)

    if not data:
        print("  cost_vs_quality: no data with price, skipped")
        return

    color_map = {
        "Qwen3.5-397B-A17B-FP8": "#2ca02c",
        "Qwen3.5-122B-A10B": "#4e79a7",
        "Qwen3.6-27B": "#9467bd",
        "Kimi-K2.6": "#ff7f0e",
        "Gemini-3.1-Pro": "#d62728",
    }

    fig, ax = plt.subplots(figsize=(9, 7))
    models_sorted = sorted(data.keys(), key=lambda m: data[m][0])

    for model in models_sorted:
        cost, score = data[model]
        color = color_map.get(model, "#333")
        ax.scatter(cost, score, s=200, color=color, zorder=5,
                   edgecolors="white", linewidths=1.5)
        ax.annotate(model, xy=(cost, score), xytext=(8, 5),
                    textcoords="offset points", fontsize=10,
                    fontweight="bold", color=color)

    ax.set_xlabel("Average Cost per Problem (USD)", fontsize=13, fontweight="bold")
    ax.set_ylabel("Overall Score", fontsize=13, fontweight="bold")
    ax.set_xlim(0, max(c for c, _ in data.values()) * 1.25)
    ax.set_ylim(2.5, 5.0)
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.set_title("Cost vs. Quality Trade-off", fontsize=15, fontweight="bold", pad=12)

    # Median lines
    med_c = np.median([c for c, _ in data.values()])
    med_s = np.median([s for _, s in data.values()])
    ax.axhline(y=med_s, color="gray", linestyle=":", alpha=0.4)
    ax.axvline(x=med_c, color="gray", linestyle=":", alpha=0.4)

    plt.tight_layout()
    out = results_dir / "cost_vs_quality.png"
    plt.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"  {out.name}")

    # Also save PDF for LaTeX
    out_pdf = results_dir / "cost_vs_quality.pdf"
    fig, ax = plt.subplots(figsize=(9, 7))
    for model in models_sorted:
        cost, score = data[model]
        color = color_map.get(model, "#333")
        ax.scatter(cost, score, s=200, color=color, zorder=5,
                   edgecolors="white", linewidths=1.5)
        ax.annotate(model, xy=(cost, score), xytext=(8, 5),
                    textcoords="offset points", fontsize=10,
                    fontweight="bold", color=color)
    ax.set_xlabel("Average Cost per Problem (USD)", fontsize=13, fontweight="bold")
    ax.set_ylabel("Overall Score", fontsize=13, fontweight="bold")
    ax.set_xlim(0, max(c for c, _ in data.values()) * 1.25)
    ax.set_ylim(2.5, 5.0)
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.set_title("Cost vs. Quality Trade-off", fontsize=15, fontweight="bold", pad=12)
    ax.axhline(y=med_s, color="gray", linestyle=":", alpha=0.4)
    ax.axvline(x=med_c, color="gray", linestyle=":", alpha=0.4)
    plt.tight_layout()
    plt.savefig(out_pdf, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"  {out_pdf.name}")


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════

def build_breakdown_csvs(all_data: dict, results_dir: Path):
    """Generate scores_by_grade.csv and scores_by_subject.csv."""
    GRADE_LABELS = {"g6": "Primary (g6)", "g9": "Junior (g9)", "g12": "Senior (g12)"}
    SUBJECT_LABELS = {
        "physics": "Physics", "chemistry": "Chemistry", "math": "Math",
        "biology": "Biology", "geography": "Geography",
    }
    EXP_MAP = {v: k for k, v in MODEL_MAP.items()}
    MODELS = [m for m in MODEL_MAP.values()
              if m not in ("Ministral-3-14B", "Mistral-Large-3-675B")]

    def parse_topic(topic):
        parts = topic.split("_")
        return parts[3], parts[2]  # grade, subject

    def compute(group_key, label_map, order):
        rows = []
        for gk in order:
            row = {"Category": label_map[gk]}
            for model in MODELS:
                data = all_data[model]
                exp_dir = OUTPUT_DIR / EXP_MAP[model]
                scored_sum = 0
                scored_n = 0
                no_code = 0
                for td in data["topics"]:
                    grade, subject = parse_topic(td["topic"])
                    val = grade if group_key == "grade" else subject
                    if val != gk:
                        continue
                    score = td.get("evaluation", {}).get("total_score", 0)
                    doc_files = list((exp_dir / td["topic"] / "doc").glob("scene*.html"))
                    if score > 0:
                        scored_sum += score
                        scored_n += 1
                    elif not doc_files:
                        no_code += 1
                    # else: agent gave 0 but has code -> exclude
                denom = scored_n + no_code
                avg = scored_sum / denom if denom > 0 else 0
                row[model] = round(avg, 2)
                row[f"{model}_n"] = denom
            rows.append(row)
        return rows

    grade_rows = compute("grade", GRADE_LABELS, ["g6", "g9", "g12"])
    # Transpose: rows=Model, cols=Category
    grade_transposed = []
    for model in MODELS:
        row = {"Model": model}
        for gr in grade_rows:
            row[gr["Category"]] = f"{gr[model]} ({gr[f'{model}_n']})"
        grade_transposed.append(row)
    csv1 = results_dir / "scores_by_grade.csv"
    with open(csv1, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=grade_transposed[0].keys())
        w.writeheader()
        w.writerows(grade_transposed)
    print(f"  {csv1.name}")

    subject_rows = compute("subject", SUBJECT_LABELS,
                           ["physics", "chemistry", "math", "biology", "geography"])
    subject_transposed = []
    for model in MODELS:
        row = {"Model": model}
        for sr in subject_rows:
            row[sr["Category"]] = f"{sr[model]} ({sr[f'{model}_n']})"
        subject_transposed.append(row)
    csv2 = results_dir / "scores_by_subject.csv"
    with open(csv2, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=subject_transposed[0].keys())
        w.writeheader()
        w.writerows(subject_transposed)
    print(f"  {csv2.name}")


def main():
    results_dir = OUTPUT_DIR / "results"
    results_dir.mkdir(exist_ok=True)

    print("[1/4] Collecting per-model JSON ...")
    all_data = save_json_results(results_dir)

    print("[2/4] Generating CSV tables ...")
    scores_rows, token_rows = build_csv_tables(all_data, results_dir)

    print("[3/4] Generating breakdown CSVs ...")
    build_breakdown_csvs(all_data, results_dir)

    print("[4/4] Generating charts ...")
    plot_radar(scores_rows, all_data, results_dir)
    plot_token_bar(token_rows, results_dir)
    plot_cost_vs_quality(scores_rows, token_rows, results_dir)

    # Copy charts to paper fig directory
    paper_fig = Path(__file__).parent.parent / "EduIllustrate_paper" / "fig"
    if paper_fig.exists():
        import shutil
        chart_files = [
            ("radar_chart", ["png", "pdf"]),
            ("token_bar_chart", ["png"]),
            ("cost_vs_quality", ["png", "pdf"]),
        ]
        for name, exts in chart_files:
            for ext in exts:
                src = results_dir / f"{name}.{ext}"
                if src.exists():
                    shutil.copy2(src, paper_fig / f"{name}.{ext}")
                    print(f"  Copied {name}.{ext} -> {paper_fig}/")

    print(f"\nAll results saved to {results_dir}/")


if __name__ == "__main__":
    main()
