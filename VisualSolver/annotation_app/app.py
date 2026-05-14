import json
import os
import re
from pathlib import Path

from flask import Flask, jsonify, request, send_file, abort, make_response
import markdown as md

app = Flask(__name__, static_folder="static")

@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp

BASE_DIR = Path(__file__).parent.parent
SAMPLED_JSON = BASE_DIR / "output" / "30_samples.json"
ANNOTATIONS_JSON = BASE_DIR / "output" / "human_annotations.json"

DIMENSIONS = [
    ("logical_coherence",                  "讲解的逻辑连贯性"),
    ("diagram_match",                      "图示与题目的匹配度"),
    ("understandability_and_teaching_effect", "讲解的易懂性和教学效果"),
    ("layout_and_visual_clarity",          "排版和视觉呈现的清晰度"),
    ("element_layout_quality",             "图片元素布局质量"),
    ("visual_consistency",                 "视觉一致性"),
    ("text_diagram_synergy",               "图文协同的流畅性"),
]

with open(SAMPLED_JSON, encoding="utf-8") as f:
    SAMPLED = json.load(f)

KEYS = list(SAMPLED.keys())

if ANNOTATIONS_JSON.exists():
    with open(ANNOTATIONS_JSON, encoding="utf-8") as f:
        annotations = json.load(f)
else:
    annotations = {}


def save_annotations():
    with open(ANNOTATIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(annotations, f, ensure_ascii=False, indent=2)


def render_doc(doc_path: str) -> str:
    """Read solution_chinese.md (fallback to solution.md), resolve image tags to API URLs, return HTML."""
    p = Path(doc_path)
    chinese = p.parent / "solution_chinese.md"
    if chinese.exists():
        p = chinese
    if not p.exists():
        return f"<p style='color:red'>文件不存在: {doc_path}</p>"
    text = p.read_text(encoding="utf-8")

    # 1. 保护数学公式，避免 markdown 解析器破坏 \ ( ) 等字符
    math_blocks = []
    def save_math(m):
        math_blocks.append(m.group(0))
        return f"MATHPLACEHOLDER{len(math_blocks)-1}END"
    # 先保护块级公式 \[...\] 和 $$...$$，再保护行内 \(...\) 和 $...$
    text = re.sub(r'\\\[[\s\S]*?\\\]', save_math, text)
    text = re.sub(r'\$\$[\s\S]*?\$\$', save_math, text)
    text = re.sub(r'\\\(.*?\\\)', save_math, text)
    text = re.sub(r'\$[^\$\n]+?\$', save_math, text)

    # 2. 替换图片路径
    doc_dir = p.parent
    def replace_img(m):
        alt = m.group(1)
        src = m.group(2)
        img_path = doc_dir / src
        return f'![{alt}](image?path={img_path})'
    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', replace_img, text)

    # 3. Markdown → HTML
    html = md.markdown(text, extensions=["tables", "fenced_code"])

    # 4. 还原数学公式
    for i, block in enumerate(math_blocks):
        html = html.replace(f"MATHPLACEHOLDER{i}END", block)

    return html


# ── API ────────────────────────────────────────────────────────────────────────

@app.get("/api/keys")
def api_keys():
    return jsonify({"keys": KEYS, "dimensions": DIMENSIONS})


@app.get("/api/annotations")
def api_annotations():
    return jsonify(annotations)


@app.get("/api/doc/<path:key>")
def api_doc(key):
    if key not in SAMPLED:
        abort(404)
    doc_path = SAMPLED[key]["document"]
    html = render_doc(doc_path)
    auto_scores = SAMPLED[key]["evaluation"]
    return jsonify({"html": html, "auto_scores": auto_scores, "doc_path": doc_path})


@app.post("/api/annotate")
def api_annotate():
    data = request.get_json()
    key = data.get("key")
    scores = data.get("scores")
    annotator = data.get("annotator", "")
    if not key or key not in SAMPLED:
        abort(400)
    annotations[key] = {"annotator": annotator, "scores": scores}
    save_annotations()
    return jsonify({"ok": True, "total_annotated": len(annotations)})


@app.get("/image")
def serve_image():
    path = request.args.get("path", "")
    p = Path(path)
    if not p.exists() or p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        abort(404)
    return send_file(p)


@app.get("/")
def index():
    resp = make_response(send_file("static/index.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860, debug=False)
