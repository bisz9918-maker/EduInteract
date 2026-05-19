#!/usr/bin/env python3
"""
4维度评测 HTML 图示（渲染检查为前置门控）：
  门控: 图示是否能渲染（宿主机本地，仅 pass/fail）
  维度1: 内容准确性（agent: accuracy-eval）
  维度2: 交互功能性（agent: interaction-eval）
  维度3: 视觉可读性（agent: visual-eval）
  维度4: 教育适配性（agent: pedagogy-eval）

每个维度 agent 给出整个题目的 0-5 分，总分 = 4个维度分的几何平均。
渲染检查不通过则总分0。

用法:
    # 评测整个目录下所有问题
    python3 eval_one.py --input_dir output/exp_kimik26 --output_dir evaluate_kimi26
    # 只评测单个问题
    python3 eval_one.py --input_dir output/exp_kimik26 --output_dir evaluate_kimi26 --problem problem_0_physics_g9
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

# Force unbuffered output so progress is visible immediately
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

ROOT = Path(__file__).resolve().parent
if load_dotenv:
    load_dotenv(ROOT / ".env", override=True)

API_URL = os.getenv("OAH_API_URL", "http://localhost:8787")
OAH_URL = API_URL
RUNTIME = "visual-solver-eval"


# ── OAH API helpers ──────────────────────────────────────────────

def _req(method, path, body=None, headers=None, params=None):
    url = f"{API_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Accept", "application/json")
    if data is not None:
        if headers and "Content-Type" in headers:
            r.add_header("Content-Type", headers["Content-Type"])
        else:
            r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=600) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OAH API error: {e.code} {e.reason} — {body_text[:500]}")


def _upload_buffer(ws_id, data_bytes, ws_path):
    _req("PUT", f"/api/v1/sandboxes/{ws_id}/files/upload",
         body=data_bytes,
         headers={"Content-Type": "application/octet-stream"},
         params={"path": ws_path, "overwrite": "true"})
    print(f"  uploaded {ws_path} ({len(data_bytes)} bytes)")


def _wait_file(ws_id, path, retries=10, interval=3):
    for i in range(retries):
        try:
            d = _req("GET", f"/api/v1/sandboxes/{ws_id}/files/content", params={"path": path})
            if d.get("content", "").strip():
                print(f"  {path} synced ({i+1} attempts)")
                return True
        except Exception:
            pass
        time.sleep(interval)
    print(f"  WARNING: {path} not synced after {retries} retries")
    return False


def _wait_run(run_id, max_s=600, poll=3):
    t0 = time.monotonic()
    last = ""
    while time.monotonic() - t0 < max_s:
        st = _req("GET", f"/api/v1/runs/{run_id}").get("status", "")
        if st != last:
            print(f"  run status: {st} ({time.monotonic()-t0:.0f}s)")
            last = st
        if st in ("completed", "failed", "cancelled"):
            return st
        time.sleep(poll)
    raise TimeoutError(f"Run {run_id} timed out")


# ── File discovery ──────────────────────────────────────────────

def find_scenes(topic_dir: Path):
    doc_dir = topic_dir / "doc"
    scenes = []
    if doc_dir.exists():
        for f in sorted(doc_dir.iterdir()):
            m = re.match(r"scene(\d+)\.html$", f.name)
            if m:
                scenes.append((int(m.group(1)), f))
    return scenes


def find_solution(topic_dir: Path):
    """Find solution.html if it exists."""
    sol = topic_dir / "doc" / "solution.html"
    return sol if sol.exists() else None


# ── Render check (gate) ──────────────────────────────────────────

def check_render(scenes):
    """前置门控：检查所有 scene 是否能渲染。返回 (passed: bool, details: dict)"""
    from playwright.sync_api import sync_playwright

    details = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for scene_n, html_path in scenes:
            page = browser.new_page()
            try:
                page.goto(f"file://{html_path.resolve()}", wait_until="domcontentloaded", timeout=10000)
                time.sleep(2)
                screenshot_path = html_path.parent / f"_check_scene{scene_n}.png"
                page.screenshot(path=str(screenshot_path))

                from PIL import Image as PILImage
                import numpy as np
                img = PILImage.open(screenshot_path)
                arr = np.array(img)
                pixel_std = arr.std()
                rendered = pixel_std > 5
                screenshot_path.unlink(missing_ok=True)

                details[f"scene{scene_n}"] = {
                    "loaded": True,
                    "rendered": rendered,
                    "pixel_std": round(pixel_std, 2),
                }
                if not rendered:
                    print(f"  scene{scene_n}: loaded but blank (std={pixel_std:.1f})")
                else:
                    print(f"  scene{scene_n}: OK (std={pixel_std:.1f})")
            except Exception as e:
                print(f"  scene{scene_n}: FAILED to load — {e}")
                details[f"scene{scene_n}"] = {
                    "loaded": False,
                    "rendered": False,
                    "error": str(e)[:200],
                }
            finally:
                page.close()
        browser.close()

    all_passed = all(d.get("rendered") for d in details.values())
    return all_passed, details


# ── Agent-based evaluation ───────────────────────────────────────

def eval_agent_dimension(ws_id, agent_name, dim_name, result_file, topic, ocr_text, scenes, image_path):
    """Run an agent evaluation for one dimension."""
    print(f"\n--- {dim_name} (agent: {agent_name}) ---")

    # Create session with specific agent
    ses = _req("POST", f"/api/v1/workspaces/{ws_id}/sessions", {
        "title": f"{dim_name} evaluation",
        "agentName": agent_name
    })
    ses_id = ses["id"]
    print(f"  session: {ses_id} (agent: {agent_name})")

    # Build message content with topic image
    from PIL import Image as PILImage
    import io
    img = PILImage.open(image_path)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    scene_list = ", ".join(f"scene{s[0]}" for s in scenes)
    msg_text = (
        f"请评测题目 {topic} 的{dim_name}。"
        f"题目描述：{ocr_text[:300] if ocr_text else '见附件图片'}。"
        f"请读取 spec.json 了解详情，综合所有 scene 给出整个题目的评分，"
        f"并将结果写入 {result_file}。"
    )
    content_parts = [
        {"type": "text", "text": msg_text},
        {"type": "image", "image": img_b64, "mediaType": "image/png"},
    ]

    run = _req("POST", f"/api/v1/sessions/{ses_id}/messages",
               {"content": content_parts})
    print(f"  run: {run['runId']}")

    # Wait for completion
    st = _wait_run(run["runId"], max_s=600)
    print(f"  result: {st}")

    if st != "completed":
        print(f"  {dim_name} evaluation failed")
        return None

    # Read result file
    try:
        d = _req("GET", f"/api/v1/sandboxes/{ws_id}/files/content",
                 params={"path": result_file})
        content = d.get("content", "")
        if content.strip():
            print(f"  {result_file} ({len(content)} chars)")
            return content.strip()
        else:
            print(f"  {result_file} is empty")
            return None
    except Exception as e:
        print(f"  Failed to read {result_file}: {e}")
        return None


# ── Parse agent XML results ──────────────────────────────────────

def parse_topic_score(xml_content, dim_tag):
    """Parse a per-topic score from agent XML output. Returns (score, reasoning)."""
    if not xml_content:
        return 0.0, ""

    # Match <score>X</score> inside the dim tag
    score_match = re.search(r"<score>\s*([\d.]+)\s*</score>", xml_content)
    score = float(score_match.group(1)) if score_match else 0.0

    reasoning_match = re.search(r"<reasoning>(.*?)</reasoning>", xml_content, re.DOTALL)
    reasoning = reasoning_match.group(1).strip() if reasoning_match else ""

    return score, reasoning


# ── Geometric mean ───────────────────────────────────────────────

def geometric_mean(values):
    if not values:
        return 0.0
    has_zero = any(v == 0 for v in values)
    product = 1.0
    for v in values:
        product *= max(v, 0.001)
    result = product ** (1 / len(values))
    return 0.0 if has_zero else round(result, 2)


# ── Main evaluation flow ─────────────────────────────────────────

def eval_topic(topic: str, input_dir: Path, output_dir: Path):
    topic_dir = input_dir / topic
    if not topic_dir.exists():
        print(f"ERROR: topic dir not found: {topic_dir}")
        return {"topic": topic, "status": "error", "error": "topic dir not found", "total_score": 0.0}

    image_path = topic_dir / "problem_diagram.png"
    if not image_path.exists():
        print(f"ERROR: image not found: {image_path}")
        return {"topic": topic, "status": "error", "error": "image not found", "total_score": 0.0}

    # Find all scenes and solution
    scenes = find_scenes(topic_dir)
    if not scenes:
        print(f"ERROR: no scene HTML files found in {topic_dir / 'doc'}")
        return {"topic": topic, "status": "error", "error": "no scene HTML files", "total_score": 0.0}

    solution_path = find_solution(topic_dir)
    print(f"Found {len(scenes)} scenes: {[s[0] for s in scenes]}")
    if solution_path:
        print(f"Found solution: {solution_path.name}")

    # ── Gate: Render check ──
    print("\n" + "=" * 60)
    print("前置检查：图示是否能渲染")
    print("=" * 60)
    render_passed, render_details = check_render(scenes)

    if not render_passed:
        print("\n前置检查未通过：有 scene 无法渲染，总分 0")
        eval_dir = output_dir / topic
        eval_dir.mkdir(parents=True, exist_ok=True)
        _write_report(eval_dir, topic, "", render_details,
                      dim_scores={}, total_score=0.0)
        return {"topic": topic, "status": "render_failed", "total_score": 0.0}

    print("\n前置检查通过，开始4维度评测")

    # ── Create workspace and upload files ──
    print("\n" + "=" * 60)
    print("创建 workspace 并上传文件")
    print("=" * 60)

    ws = _req("POST", "/api/v1/workspaces", {
        "name": f"eval-{topic}-{int(time.time())}",
        "runtime": RUNTIME
    })
    ws_id = ws["id"]
    print(f"  workspace: {ws_id}")

    # Wait for sandbox to be ready (container may need time to start)
    print("  Waiting for sandbox to be ready...")
    for attempt in range(10):
        try:
            _req("GET", f"/api/v1/sandboxes/{ws_id}/files/content", params={"path": "."})
            print(f"  Sandbox ready ({attempt+1} attempts)")
            break
        except Exception:
            time.sleep(2)
    else:
        print("  WARNING: Sandbox may not be ready, proceeding anyway")

    # Upload topic image
    img_bytes = image_path.read_bytes()
    _upload_buffer(ws_id, img_bytes, "topic.png")

    # Build and upload spec.json
    spec = {
        "topic": topic,
        "description": "",
        "image_file": "topic.png",
        "scenes": [
            {"scene_number": n, "output_file": f"scene{n}.html"}
            for n, _ in scenes
        ]
    }
    if solution_path:
        spec["solution_file"] = "solution.html"
    _upload_buffer(ws_id, json.dumps(spec, ensure_ascii=False).encode("utf-8"), "spec.json")

    # Upload all scene HTML files
    for scene_n, scene_html_path in scenes:
        html_bytes = scene_html_path.read_bytes()
        _upload_buffer(ws_id, html_bytes, f"scene{scene_n}.html")

    # Upload solution.html if exists
    if solution_path:
        sol_bytes = solution_path.read_bytes()
        _upload_buffer(ws_id, sol_bytes, "solution.html")

    # Wait for all files to sync
    print("Waiting for file sync...")
    _wait_file(ws_id, "spec.json")
    _wait_file(ws_id, "topic.png")
    for scene_n, _ in scenes:
        _wait_file(ws_id, f"scene{scene_n}.html")
    if solution_path:
        _wait_file(ws_id, "solution.html")

    # ── Dimension 1-4: Agent evaluation ──
    agent_dims = [
        ("problem-alignment-eval", "内容准确性", "dim1_result.txt", "dim1_accuracy"),
        ("interactive-functionality-eval", "交互功能性", "dim2_result.txt", "dim2_interaction"),
        ("visual-quality-eval", "视觉可读性", "dim3_result.txt", "dim3_visual"),
        ("pedagogical-effectiveness-eval", "教育适配性", "dim4_result.txt", "dim4_pedagogy"),
    ]

    # Create eval output directory
    eval_dir = output_dir / topic
    eval_dir.mkdir(parents=True, exist_ok=True)
    print(f"  eval output: {eval_dir}")

    dim_scores = {}   # {dim_key: score}
    dim_reasons = {}  # {dim_key: reasoning}

    for agent_name, dim_name, result_file, dim_tag in agent_dims:
        xml_content = eval_agent_dimension(
            ws_id, agent_name, dim_name, result_file,
            topic, "", scenes, image_path
        )
        score, reasoning = parse_topic_score(xml_content, dim_tag)
        dim_scores[dim_tag] = score
        dim_reasons[dim_tag] = reasoning
        print(f"  {dim_name}: {score}/5 — {reasoning[:80]}")

        # Save raw agent output
        if xml_content:
            raw_path = eval_dir / result_file
            raw_path.write_text(xml_content, encoding="utf-8")
            print(f"  saved {raw_path}")

    # ── Compute total score ──
    print("\n" + "=" * 60)
    print("汇总评分")
    print("=" * 60)

    total_score = geometric_mean(list(dim_scores.values()))

    dim_labels = {
        "dim1_accuracy": "内容准确性",
        "dim2_interaction": "交互功能性",
        "dim3_visual": "视觉可读性",
        "dim4_pedagogy": "教育适配性",
    }
    print(f"\n{'维度':<12} {'分数':>6}")
    print("-" * 20)
    for dim_tag in [d[3] for d in agent_dims]:
        print(f"{dim_labels[dim_tag]:<12} {dim_scores[dim_tag]:>6.2f}")
    print("-" * 20)
    print(f"{'总分':<12} {total_score:>6.2f}")

    _write_report(eval_dir, topic, "", render_details, dim_scores, dim_reasons, total_score)

    return {"topic": topic, "status": "completed", "total_score": total_score, **{k: v for k, v in dim_scores.items()}}


def _write_report(eval_dir, topic, ocr_text, render_details, dim_scores, dim_reasons=None, total_score=0.0):
    """Write evaluation report to XML file."""
    all_scene_names = sorted(render_details.keys())

    report_lines = [
        '<evaluation_report>',
        f'  <topic>{topic}</topic>',
        f'  <description>{ocr_text[:200]}</description>',
        '  <render_check>',
    ]
    for scene_name in all_scene_names:
        d = render_details[scene_name]
        status = "passed" if d.get("rendered") else "failed"
        report_lines.append(f'    <{scene_name} status="{status}"/>')
    report_lines.append('  </render_check>')

    if dim_scores:
        dim_labels = {
            "dim1_accuracy": "内容准确性",
            "dim2_interaction": "交互功能性",
            "dim3_visual": "视觉可读性",
            "dim4_pedagogy": "教育适配性",
        }
        report_lines.append('  <dimensions>')
        for dim_tag in ["dim1_accuracy", "dim2_interaction", "dim3_visual", "dim4_pedagogy"]:
            score = dim_scores.get(dim_tag, 0.0)
            reasoning = dim_reasons.get(dim_tag, "") if dim_reasons else ""
            # Escape XML special chars in reasoning
            reasoning_esc = reasoning.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            report_lines.append(f'    <{dim_tag} score="{score}">{reasoning_esc}</{dim_tag}>')
        report_lines.append('  </dimensions>')

    report_lines.append(f'  <total_score>{total_score}</total_score>')
    report_lines.append('</evaluation_report>')

    report_xml = '\n'.join(report_lines)
    report_path = eval_dir / "evaluation_report.xml"
    report_path.write_text(report_xml, encoding="utf-8")
    print(f"\nReport saved to {report_path}")
    print(report_xml)


def find_problem_dirs(input_dir: Path) -> list[str]:
    """扫描 input_dir 下所有 problem_* 子目录，返回排序后的目录名列表。"""
    if not input_dir.exists():
        print(f"ERROR: input dir not found: {input_dir}")
        sys.exit(1)
    problems = sorted([
        d.name for d in input_dir.iterdir()
        if d.is_dir() and d.name.startswith("problem_")
    ])
    print(f"Found {len(problems)} problem directories in {input_dir}")
    return problems


def eval_batch(input_dir: Path, output_dir: Path, problem: str | None = None):
    """批量评测 input_dir 下所有（或指定）问题，结果输出到 output_dir。"""
    if problem:
        problems = [problem]
    else:
        problems = find_problem_dirs(input_dir)

    if not problems:
        print("No problems to evaluate.")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i, topic in enumerate(problems):
        print(f"\n{'#' * 70}")
        print(f"# 评测进度: {i+1}/{len(problems)} — {topic}")
        print(f"{'#' * 70}")
        try:
            result = eval_topic(topic, input_dir, output_dir)
            results.append(result)
        except Exception as e:
            print(f"ERROR evaluating {topic}: {e}")
            results.append({"topic": topic, "status": "error", "error": str(e), "total_score": 0.0})

    # Write summary
    total = len(results)
    completed = sum(1 for r in results if r["status"] == "completed")
    render_failed = sum(1 for r in results if r["status"] == "render_failed")
    errors = sum(1 for r in results if r["status"] == "error")
    avg_score = sum(r["total_score"] for r in results if r["status"] == "completed") / max(completed, 1)

    summary = {
        "total": total,
        "completed": completed,
        "render_failed": render_failed,
        "errors": errors,
        "average_score": round(avg_score, 2),
        "results": results,
    }
    summary_path = output_dir / "evaluation_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'=' * 60}")
    print(f"评测完成: {completed}/{total} 成功, {render_failed} 渲染失败, {errors} 错误")
    print(f"平均分: {avg_score:.2f}")
    print(f"汇总报告: {summary_path}")
    print(f"{'=' * 60}")


def main():
    global API_URL
    parser = argparse.ArgumentParser(description="4-dimension evaluation of interactive HTML diagrams")
    parser.add_argument("--input_dir", required=True, type=Path,
                        help="实验产出目录 (如 output/exp_kimik26)")
    parser.add_argument("--output_dir", required=True, type=Path,
                        help="评测结果输出目录 (如 evaluate_kimi26)")
    parser.add_argument("--problem", type=str, default=None,
                        help="只评测指定问题 (如 problem_0_physics_g9)")
    parser.add_argument("--oah_url", type=str, default=None,
                        help="OAH API 地址 (如 http://127.0.0.1:8790)")
    args = parser.parse_args()

    if args.oah_url:
        API_URL = args.oah_url

    input_dir = args.input_dir if args.input_dir.is_absolute() else ROOT / args.input_dir
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir

    eval_batch(input_dir, output_dir, problem=args.problem)


if __name__ == "__main__":
    main()
