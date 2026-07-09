import json
import os
import re
from pathlib import Path

import markdown as md
from flask import Flask, jsonify, request, send_file, abort, make_response

app = Flask(__name__, static_folder="static")

@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"
ANNOTATIONS_JSON = Path(__file__).parent / "human_annotations.json"

# Static diagram directory (Gemini-3-Pro unified reference)
STATIC_DIAGRAM_DIR = Path(
    "/inspire/hdd/project/ai4education/bishuzhen-CZXS24220022/"
    "edubench/TheoremExplainAgent/output/exp_gemini-3-pro-preview"
)

EXP_TO_MODEL = {
    "exp_Gemini-3.1-Pro": "Gemini-3.1-Pro",
    "exp_kimik26": "Kimi-K2.6",
    "exp_qwen35_122b": "Qwen3.5-122B",
    "exp_qwen35_397b": "Qwen3.5-397B",
    "exp_qwen36_27b": "Qwen3.6-27B",
    "k12_vista_math_g9": "k12_vista_math_g9",
    "k12_vista_math_g12": "k12_vista_math_g12",
    "k12_vista_physics_g9": "k12_vista_physics_g9",
    "k12_vista_physics_g12": "k12_vista_physics_g12",
}

EVAL_TO_EXP = {
    "evaluate_Gemini-3.1-Pro": "exp_Gemini-3.1-Pro",
    "evaluate_kimi26": "exp_kimik26",
    "evaluate_qwen35_122b": "exp_qwen35_122b",
    "evaluate_qwen35_397b": "exp_qwen35_397b",
    "evaluate_qwen36_27b": "exp_qwen36_27b",
    "evaluate_math_g9": "k12_vista_math_g9",
    "evaluate_math_g12": "k12_vista_math_g12",
    "evaluate_physics_g9": "k12_vista_physics_g9",
    "evaluate_physics_g12": "k12_vista_physics_g12",
}

MODELS_ORDER = ["Gemini-3.1-Pro", "Kimi-K2.6", "Qwen3.5-397B", "Qwen3.5-122B", "Qwen3.6-27B",
                "k12_vista_math_g9", "k12_vista_math_g12", "k12_vista_physics_g9", "k12_vista_physics_g12"]

# 5-dimension scoring for interactive items
# Each: (key, display_name, scoring_guide)
DIMENSIONS = [
    ("prob_align", "题图匹配 (Problem Alignment)",
     "图示内容是否与题意对齐？\n"
     "5: 关键元素全部呈现，数值/比例/角度准确，解题过程正确\n"
     "4: 内容基本正确，有轻微标注偏差但不影响理解\n"
     "3: 部分关键元素缺失或有数值错误，但不严重偏离题意\n"
     "2: 多处内容错误或与题意不符，解题过程有明显漏洞\n"
     "1: 内容严重错误或与题意无关"),
    ("interact", "交互功能 (Interactive Functionality)",
     "交互功能是否正常有效？\n"
     "5: 所有应有交互功能均正常，响应流畅自然\n"
     "4: 交互功能基本正常，偶有反馈不够明显\n"
     "3: 部分交互有响应但效果不理想，或缺少部分应有交互\n"
     "2: 交互功能严重不足，大多操作无可见响应\n"
     "1: 完全无交互功能，或应有交互但完全不可用"),
    ("visual", "视觉质量 (Visual Quality)",
     "元素质量、布局、风格一致性如何？\n"
     "5: 元素精良清晰，布局合理，跨scene和交互前后风格完全一致\n"
     "4: 元素质量良好，布局基本合理，风格基本一致但有微小差异\n"
     "3: 部分元素模糊/重叠，布局偏挤或偏空，scene间风格有差异\n"
     "2: 元素质量差（文字重叠、线条断裂），布局混乱，风格不一致\n"
     "1: 完全不可读，或风格严重不一致"),
    ("pedagogy", "教学效果 (Pedagogical Effectiveness)",
     "教学设计质量如何？\n"
     "5: 认知引导优秀，步骤循序渐进，交互有助于理解因果关系，自主探索空间充足\n"
     "4: 教学设计良好，引导清晰，但探索空间或节奏稍有不足\n"
     "3: 基本能辅助理解，但步骤节奏不合理或缺少操作提示\n"
     "2: 教学设计差，信息过载或步骤跳跃，交互仅为炫技无教学意义\n"
     "1: 可能误导学生，或与教学目标无关"),
    ("logic", "逻辑连贯 (Logical Coherence)",
     "scene间递进关系和交互状态一致性如何？\n"
     "5: scene递进合理（已知→推导→结论），交互操作后状态符合几何/物理约束\n"
     "4: 逻辑基本连贯，偶有轻微跳跃但整体通顺\n"
     "3: scene间衔接不够自然，或交互后个别状态不太合理\n"
     "2: 存在明显逻辑断裂或交互状态矛盾（如拖动后图形断裂）\n"
     "1: scene完全脱节，交互操作导致严重逻辑错误"),
]

# Questions for static items (compared with interactive)
# Two options: "static" (静态更好) / "interactive" (交互式更好)
QUESTIONS = [
    ("comprehension", "相比静态图示，交互式图示是否更有助于理解题目内容和解题过程？"),
    ("experience", "相比静态图示，交互式图示的学习体验是否更好？"),
    ("pedagogy", "相比静态图示，交互式图示的教学效果是否更好（如分步演示、逻辑引导）？"),
    ("engagement", "相比静态图示，交互式图示是否更能吸引你主动探索和思考？"),
    ("overall", "综合来看，你更倾向于使用哪种图示来学习这道题？"),
]


def render_markdown(text: str) -> str:
    """Render markdown to HTML, preserving LaTeX math."""
    math_blocks = []

    def save_math(m):
        math_blocks.append(m.group(0))
        return f"MATHPLACEHOLDER{len(math_blocks)-1}END"

    # Protect block math \[...\] and $$...$$
    text = re.sub(r'\\\[[\s\S]*?\\\]', save_math, text)
    text = re.sub(r'\$\$[\s\S]*?\$\$', save_math, text)
    # Protect inline math \(...\) and $...$
    text = re.sub(r'\\\(.*?\\\)', save_math, text)
    text = re.sub(r'(?<!\$)\$(?!\$)([^\$\n]+?)(?<!\$)\$(?!\$)', save_math, text)

    html = md.markdown(text, extensions=["tables", "fenced_code"])

    # Restore math
    for i, block in enumerate(math_blocks):
        html = html.replace(f"MATHPLACEHOLDER{i}END", block)

    return html


def _scan_exp_dir(exp_dir: Path, model: str, samples: dict, require_eval: bool = True):
    """Scan an exp dir for topics with HTML scenes.

    If require_eval is True, only include topics that have an evaluation_report.xml
    in the corresponding evaluate dir. Otherwise, include all topics with doc/scene*.html.
    """
    if not exp_dir.exists():
        return

    for topic_dir in sorted(exp_dir.iterdir()):
        if not topic_dir.is_dir() or not topic_dir.name.startswith("problem_"):
            continue
        topic = topic_dir.name

        # Check evaluation report if required
        if require_eval:
            # Find corresponding eval dir
            eval_dir_name = None
            for ev, ex in EVAL_TO_EXP.items():
                if ex == exp_dir.name:
                    eval_dir_name = ev
                    break
            if eval_dir_name:
                report_path = OUTPUT_DIR / eval_dir_name / topic / "evaluation_report.xml"
                if not report_path.exists():
                    continue

        # Collect scene HTML files
        doc_dir = topic_dir / "doc"
        scenes = sorted([f.name for f in doc_dir.glob("scene*.html")]) if doc_dir.exists() else []
        if not scenes:
            continue

        key = f"{model}/{topic}"

        # Parse evaluation scores (if available)
        scores = {}
        if require_eval and eval_dir_name:
            report_path = OUTPUT_DIR / eval_dir_name / topic / "evaluation_report.xml"
            if report_path.exists():
                text = report_path.read_text(encoding="utf-8")
                for tag, idx in [("dim1_accuracy", 1), ("dim2_interaction", 2),
                                 ("dim3_visual", 3), ("dim4_pedagogy", 4),
                                 ("dim5_logic_coherence", 5)]:
                    m = re.search(rf'<{tag}\s+score="([\d.]+)"', text)
                    if m:
                        scores[f"dim{idx}"] = float(m.group(1))

        # Get full outline as rendered HTML
        outline_html = ""
        outline_files = list(topic_dir.glob("*_scene_outline.txt"))
        if outline_files:
            outline_text = outline_files[0].read_text(encoding="utf-8")
            text_blocks = re.findall(r'<TEXT_\d+>(.*?)</TEXT_\d+>', outline_text, re.DOTALL)
            if text_blocks:
                full_md = "\n\n---\n\n".join(b.strip() for b in text_blocks)
                lines = full_md.split('\n')
                cleaned = []
                for line in lines:
                    cleaned.append(line.lstrip())
                full_md = '\n'.join(cleaned)
                outline_html = render_markdown(full_md)

        # Problem diagram
        diagram_path = ""
        diagram_file = topic_dir / "problem_diagram.png"
        if diagram_file.exists():
            diagram_path = str(diagram_file)

        samples[key] = {
            "model": model,
            "topic": topic,
            "scenes": scenes,
            "auto_scores": scores,
            "outline_html": outline_html,
            "diagram_path": diagram_path,
            "exp_dir": str(topic_dir),
        }


def build_samples() -> dict:
    """Scan output dirs and collect evaluated topics with HTML scenes."""
    samples = {}
    # Evaluated models: require eval dir
    for eval_dir_name, exp_dir_name in EVAL_TO_EXP.items():
        exp_dir = OUTPUT_DIR / exp_dir_name
        model = EXP_TO_MODEL.get(exp_dir_name, exp_dir_name)
        _scan_exp_dir(exp_dir, model, samples, require_eval=True)

    # Show-only models: no eval dir needed
    for exp_dir_name, model in EXP_TO_MODEL.items():
        if exp_dir_name in EVAL_TO_EXP.values():
            continue  # already scanned above
        exp_dir = OUTPUT_DIR / exp_dir_name
        _scan_exp_dir(exp_dir, model, samples, require_eval=False)

    return samples


# ── Original samples (internal use, keep for data lookup) ──
SAMPLES = build_samples()


def select_divergent_problems(n: int = 30) -> list:
    """Select n problems with the largest score divergence across models.

    Reads evaluation_summary.json from each model's evaluate dir,
    computes max(total_score) - min(total_score) per topic,
    and returns the top n topic names sorted by divergence (descending).
    Only includes topics that appear in 4+ models with valid scores.
    """
    # Collect total_score per topic across models
    # Note: items with status "skipped" still have valid total_score
    # Exclude scores of 0 (indicates evaluation failure, not real quality)
    topic_scores = {}  # topic -> [total_score, ...]
    for eval_dir_name in EVAL_TO_EXP:
        summary_path = OUTPUT_DIR / eval_dir_name / "evaluation_summary.json"
        if not summary_path.exists():
            continue
        with open(summary_path, encoding="utf-8") as f:
            summary = json.load(f)
        for item in summary.get("results", []):
            if item.get("status") == "error":
                continue
            topic = item.get("topic", "")
            total = item.get("total_score")
            if total is None or total == 0:
                continue
            topic_scores.setdefault(topic, []).append(total)

    # Filter: must have 4+ models with valid (non-zero) scores
    candidates = []
    for topic, scores in topic_scores.items():
        if len(scores) >= 4:
            divergence = max(scores) - min(scores)
            candidates.append((topic, divergence))

    # Sort by divergence descending
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [c[0] for c in candidates[:n]]


def build_selected_samples() -> tuple:
    """Build the selected samples dict with anonymous keys.

    Returns:
        selected: dict mapping anonymous key -> sample data
        keys: ordered list of anonymous keys (grouped by topic)
    """
    selected_topics = select_divergent_problems(30)

    # Build lookup of valid (non-zero) total_scores per model per topic
    # so we can skip models that scored 0 for a topic
    valid_model_topics = set()  # (model, topic) pairs with non-zero score
    for eval_dir_name in EVAL_TO_EXP:
        model = EXP_TO_MODEL.get(EVAL_TO_EXP.get(eval_dir_name, ""), "")
        if not model:
            continue
        summary_path = OUTPUT_DIR / eval_dir_name / "evaluation_summary.json"
        if not summary_path.exists():
            continue
        with open(summary_path, encoding="utf-8") as f:
            summary = json.load(f)
        for item in summary.get("results", []):
            if item.get("status") == "error":
                continue
            topic = item.get("topic", "")
            total = item.get("total_score")
            if total is None or total == 0:
                continue
            valid_model_topics.add((model, topic))

    selected = {}
    keys = []

    for topic in selected_topics:
        # Collect all models that have this topic with valid (non-zero) score
        model_entries = []
        for model in MODELS_ORDER:
            if (model, topic) not in valid_model_topics:
                continue
            internal_key = f"{model}/{topic}"
            if internal_key in SAMPLES:
                model_entries.append((model, internal_key))

        # Add interactive entries: _1, _2, _3, ...
        for idx, (model, internal_key) in enumerate(model_entries, start=1):
            anon_key = f"{topic}_{idx}"
            # Collect static scene images for this topic
            static_scenes = []
            if STATIC_DIAGRAM_DIR.exists():
                static_doc = STATIC_DIAGRAM_DIR / topic / "doc"
                if static_doc.exists():
                    static_scenes = sorted([f.name for f in static_doc.glob("scene*.png")])

            selected[anon_key] = {
                "type": "interactive",
                "internal_key": internal_key,
                "topic": topic,
                "index": idx,
                "static_scenes": static_scenes,
            }
            keys.append(anon_key)

        # Add static entry: _static
        anon_key_static = f"{topic}_static"
        # Static diagram and scenes from Gemini-3-Pro dir
        static_diagram = ""
        static_scenes = []
        # Use Chinese outline from the first interactive model (same topic content)
        shared_outline_html = ""
        if model_entries:
            first_internal = SAMPLES.get(model_entries[0][1], {})
            shared_outline_html = first_internal.get("outline_html", "")
        if STATIC_DIAGRAM_DIR.exists():
            topic_static = STATIC_DIAGRAM_DIR / topic
            diag = topic_static / "problem_diagram.png"
            if diag.exists():
                static_diagram = str(diag)
            doc_dir = topic_static / "doc"
            if doc_dir.exists():
                static_scenes = sorted([f.name for f in doc_dir.glob("scene*.png")])

        selected[anon_key_static] = {
            "type": "static",
            "topic": topic,
            "static_diagram": static_diagram,
            "static_scenes": static_scenes,
            "outline_html": shared_outline_html,
        }
        keys.append(anon_key_static)

    return selected, keys


def build_show_samples() -> tuple:
    """Build the show-mode samples dict with model names visible.

    All models, all topics — grouped by model.
    Only interactive (HTML scenes) entries, no static items.
    Keys use format: {model}/{topic} (not anonymized).
    """
    selected = {}
    keys = []

    for model in MODELS_ORDER:
        # Find all topics for this model
        model_topics = []
        for internal_key, sample in SAMPLES.items():
            if sample["model"] == model:
                model_topics.append((internal_key, sample["topic"]))

        model_topics.sort(key=lambda x: x[1])

        for internal_key, topic in model_topics:
            show_key = f"{model}/{topic}"
            selected[show_key] = {
                "type": "interactive",
                "internal_key": internal_key,
                "topic": topic,
                "model": model,
            }
            keys.append(show_key)

    return selected, keys


# ── Mode selection via environment variable ──
ANNOTATION_MODE = os.environ.get("ANNOTATION_MODE", "eval")

if ANNOTATION_MODE == "show":
    SELECTED, KEYS = build_show_samples()
else:
    SELECTED, KEYS = build_selected_samples()


if ANNOTATIONS_JSON.exists():
    with open(ANNOTATIONS_JSON, encoding="utf-8") as f:
        _raw = json.load(f)
else:
    _raw = {}

# Migration: old format {key: {annotator, scores}} -> {key: {annotator_name: {scores}}}
annotations = {}
for k, v in _raw.items():
    if isinstance(v, dict) and "annotator" in v and "scores" in v:
        # Old format — migrate
        name = v["annotator"] or "unknown"
        annotations[k] = {name: v["scores"]}
    else:
        annotations[k] = v


def save_annotations():
    with open(ANNOTATIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(annotations, f, ensure_ascii=False, indent=2)


# ── API ────────────────────────────────────────────────────────────────────────

@app.get("/api/keys")
def api_keys():
    return jsonify({
        "keys": KEYS,
        "dimensions": DIMENSIONS,
        "questions": QUESTIONS,
        "mode": ANNOTATION_MODE,
    })


@app.get("/api/annotations")
def api_annotations():
    annotator = request.args.get("annotator", "")
    if annotator:
        # Return only this annotator's work: {key: {scores}} for matching keys
        filtered = {}
        for k, annotators in annotations.items():
            if annotator in annotators:
                filtered[k] = annotators[annotator]
        return jsonify(filtered)
    return jsonify(annotations)


@app.get("/api/doc/<path:key>")
def api_doc(key):
    if key not in SELECTED:
        abort(404)
    s = SELECTED[key]

    if s["type"] == "interactive":
        # Look up original sample data
        internal = SAMPLES.get(s["internal_key"])
        if not internal:
            abort(404)
        # Build URLs for scene HTML files (use internal key for /html route)
        scene_urls = [f"/html?key={s['internal_key']}&scene={sn}" for sn in internal["scenes"]]
        # Display name: show model name in show mode, anonymous index in eval mode
        if ANNOTATION_MODE == "show":
            display_name = s["model"] + " - " + s["topic"].replace("_", " ")
        else:
            display_name = s["topic"].replace("_", " ") + " - " + str(s["index"])
        return jsonify({
            "type": "interactive",
            "topic": s["topic"],
            "display_name": display_name,
            "model": s.get("model", ""),
            "outline_html": internal["outline_html"],
            "diagram_url": f"/diagram?key={s['internal_key']}" if internal["diagram_path"] else "",
            "scenes": scene_urls,
            "scene_names": internal["scenes"],
            "scoring_mode": "dimensions",
        })
    else:
        # Static item
        # Build URLs for static scene images
        static_scene_urls = [f"/static_scene?key={key}&scene={sn}" for sn in s["static_scenes"]]
        if ANNOTATION_MODE == "show":
            display_name = s.get("model", "") + " - " + s["topic"].replace("_", " ") + " - static"
        else:
            display_name = s["topic"].replace("_", " ") + " - static"
        return jsonify({
            "type": "static",
            "topic": s["topic"],
            "display_name": display_name,
            "model": s.get("model", ""),
            "outline_html": s.get("outline_html", ""),
            "diagram_url": f"/static_diagram?key={key}" if s.get("static_diagram") else "",
            "static_scenes": static_scene_urls,
            "static_scene_names": s["static_scenes"],
            "scoring_mode": "questions",
        })


@app.post("/api/annotate")
def api_annotate():
    data = request.get_json()
    key = data.get("key")
    scores = data.get("scores")
    annotator = data.get("annotator", "")
    if not key or key not in SELECTED:
        abort(400)
    if key not in annotations:
        annotations[key] = {}
    annotations[key][annotator] = scores
    save_annotations()
    # Count how many keys this annotator has completed
    done = sum(1 for v in annotations.values() if annotator in v)
    return jsonify({"ok": True, "total_annotated": done, "total_keys": len(KEYS)})


def _fix_scene_html(data: bytes) -> bytes:
    """Fix LLM-generated scene HTML for correct MathJax rendering.

    Issues:
    1. JS strings eat backslash escapes: \\frac → \\f(form-feed)+rac in template
       literals; \\triangle → \\t(tab)+riangle in quoted strings.
       Fix: replace JS strings containing LaTeX with
       document.getElementById("...").textContent reading from
       <script type="text/template"> tags (not executed, backslashes preserved).
    2. No MathJax config for $ delimiters — default only supports \\(\\).
       Fix: inject MathJax config before the script tag.
    """
    import re
    text = data.decode("utf-8", errors="replace")
    tpl_counter = [0]

    def _restore_ctrl(content: str) -> str:
        """Restore control chars produced by JS escape interpretation."""
        content = content.replace("\x0crac", "\\frac")
        content = content.replace("\x0dightarrow", "\\rightarrow")
        content = content.replace("\x0dight", "\\right")
        content = content.replace("\x0aightarrow", "\\rightarrow")
        content = content.replace("\x0aight", "\\right")
        content = content.replace("\x09imes", "\\times")
        content = content.replace("\x09herefore", "\\therefore")
        content = content.replace("\x09ext", "\\text")
        content = content.replace("\x09iangle", "\\triangle")
        content = content.replace("\x08ecause", "\\because")
        content = content.replace("\x0c", "\\f")
        content = content.replace("\x0d", "\\r")
        content = content.replace("\x0a", "\\n")
        content = content.replace("\x09", "\\t")
        content = content.replace("\x08", "\\b")
        return content

    def _has_latex(s: str, allow_newlines: bool = False) -> bool:
        ctrl_chars = ("\x08", "\x09", "\x0c") if allow_newlines else ("\x08", "\x09", "\x0c", "\x0a", "\x0d")
        if any(c in s for c in ctrl_chars):
            return True
        # Common LaTeX commands that JS string interpretation would break
        # (backslash + letter → JS drops the backslash for unknown escapes)
        if re.search(r"\\(?:frac|triangle|therefore|because|times|angle|circ|cong|perp|parallel|approx|neq|leq|geq|cdot|cdot|sqrt|overline|underline|overrightarrow|left|right|displaystyle|textstyle|lim|sum|prod|int|infty|partial|nabla|alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lambda|mu|nu|xi|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega|quad|qquad|hfill|vfill|quad|text|mathrm|mathbf|mathit|mathsf|mathtt|mathcal|mathbb|mathfrak|boldsymbol|vec|hat|bar|dot|ddot|tilde|widehat|widetilde|overleftarrow|overrightarrow|overline|underline|boxed|cancel|bf|it|rm|sf|tt|cal|footnotesize|small|normalsize|large|Large|huge|Huge)\b", s):
            return True
        # Also detect $...$ which likely contain LaTeX (require backslash inside)
        if re.search(r'\$[^$]*\\[^$]+\$', s):
            return True
        return False


    # --- Fix 1a: move stepsMath template strings to template tags ---
    m = re.search(r"stepsMath\s*=\s*\[(.*?)\];", text, re.DOTALL)
    if m:
        body = m.group(1)
        step_contents = [_restore_ctrl(sm.group(1)) for sm in re.finditer(r"`([^`]*)`", body)]
        template_blocks = []
        for i, content in enumerate(step_contents):
            template_blocks.append(f'<script type="text/template" id="step-{i}">{content}</script>')
        template_html = "\n".join(template_blocks)
        new_stepsmath = (
            "stepsMath = Array.from(document.querySelectorAll("
            "'script[type=\"text/template\"][id^=\"step-\"]'))"
            ".map(s => s.textContent);"
        )
        script_open = text.rfind("<script>", 0, m.start())
        if script_open < 0:
            script_open = text.rfind("<script>\n", 0, m.start())
        text = text[:script_open] + template_html + "\n" + text[script_open:m.start()] + new_stepsmath + text[m.end():]

    # --- Fix 1b: replace single/double-quoted strings with LaTeX ---
    # Only search inside <script> blocks to avoid matching quotes in
    # HTML/SVG content (e.g. <text>A'</text>).
    # The raw file content already has correct single-backslash LaTeX.
    # Putting it in <script type="text/template"> bypasses JS string
    # interpretation entirely, so NO unescaping needed—just restore
    # any control chars that JS already consumed.
    # Also convert \(...\) → $...$ and \[...\] → $$...$$ in template
    # content because typeWriter's char-by-char rendering breaks MathJax,
    # and $ delimiters work reliably with direct innerHTML assignment.
    replacements = []
    script_blocks = [(m.start(), m.end(), m.group(0)) for m in re.finditer(r'<script[^>]*>.*?</script>', text, re.DOTALL)]
    # Collect all double-quote string ranges first, so we can skip
    # single-quote matches that fall inside them (e.g. "$T'$" where
    # the apostrophe in T' should not be treated as a string delimiter).
    dq_ranges = [(m.start(), m.end()) for m in re.finditer(r'"((?:[^"\\]|\\.)*?)"', text)]
    for quote_char, pattern in [('"', r'"((?:[^"\\]|\\.)*?)"'), ("'", r"'((?:[^'\\]|\\.)*?)'")]:
        for m_str in re.finditer(pattern, text):
            # Only consider matches inside non-module <script> blocks
            in_script = None
            for s_start, s_end, s_text in script_blocks:
                if s_start <= m_str.start() < s_end:
                    in_script = s_text
                    break
            if not in_script:
                continue
            # Skip ES module scripts — they have their own scope and
            # template literal handling differs from regular scripts
            if 'type="module"' in in_script[:80] or "type='module'" in in_script[:80]:
                continue
            # Skip single-quote matches that overlap with a double-quote string.
            # E.g. in "text with $T'$ more text", the ' in T' should NOT
            # be treated as a single-quote string boundary. Also catches
            # cases where a SQ match starts outside but ends inside a DQ string.
            content = m_str.group(1)
            if quote_char == "'":
                overlaps_dq = any(m_str.start() < dq_e and m_str.end() > dq_s for dq_s, dq_e in dq_ranges)
                if overlaps_dq:
                    continue
                # Skip single-quote matches that span multiple lines or contain
                # HTML tags — these are almost certainly fragments from a broken
                # string (e.g. 'E} \perp \vec{BD}\)</span>' extracted from
                # '\(\vec{A'E}...') rather than legitimate JS string literals.
                if '\n' in content or '<' in content:
                    continue
            # Inside <script> blocks, \x0a/\x0d are legitimate line breaks,
            # not LaTeX corruption. Only check for \x08/\x09/\x0c and LaTeX commands.
            has_latex = _has_latex(content, allow_newlines=True)
            if has_latex:
                restored = _restore_ctrl(content)
                # Convert \(...\) → $...$ and \[...\] → $$...$$
                restored = re.sub(r'\\\((.+?)\\\)', r'$\1$', restored)
                restored = re.sub(r'\\\[(.+?)\\\]', r'$$\1$$', restored)
                tid = f"tpl-{tpl_counter[0]}"
                tpl_counter[0] += 1
                js_read = f'document.getElementById("{tid}").textContent'
                replacements.append((m_str.start(), m_str.end(), js_read, restored, tid))

    # Replace from end to start to preserve positions
    for start, end, js_read, restored, tid in reversed(replacements):
        text = text[:start] + js_read + text[end:]

    # Insert template tags (find js_read text, insert before nearest <script>)
    for start, end, js_read, restored, tid in reversed(replacements):
        tag = f'<script type="text/template" id="{tid}">{restored}</script>\n'
        search_pos = text.find(js_read)
        if search_pos >= 0:
            script_pos = text.rfind("<script>", 0, search_pos)
            if script_pos >= 0:
                text = text[:script_pos] + tag + text[script_pos:]

    # --- Fix 1c: replace typeWriter calls with direct innerHTML ---
    # typeWriter renders char-by-char which breaks MathJax rendering.
    # Replace with direct innerHTML + MathJax.typesetPromise.
    # Must NOT match function definitions like
    # "async function typeWriter(text, element, animId)".
    def _replace_typewriter_calls(text):
        pattern = r'typeWriter\(\s*text\s*,\s*(\w+)\s*,\s*\w+\s*\)'
        result = []
        last_end = 0
        for m in re.finditer(pattern, text):
            before = text[:m.start()].rstrip()
            if before.endswith('function'):
                # Skip function definition
                result.append(text[last_end:m.end()])
            else:
                el = m.group(1)
                replacement = f'{el}.innerHTML = text; if (window.MathJax) MathJax.typesetPromise([{el}])'
                result.append(text[last_end:m.start()] + replacement)
            last_end = m.end()
        result.append(text[last_end:])
        return ''.join(result)

    text = _replace_typewriter_calls(text)

    # --- Fix 1d: restore control chars in HTML content ---
    # Some scene files have broken LaTeX directly in HTML (not in JS strings).
    # \r/\n in LaTeX commands like \rightarrow, \right must be restored, but
    # we cannot blindly replace all \n/\r since they are legitimate line breaks.
    # Strategy: restore known LaTeX word fragments first, then handle remaining
    # control chars only within $...$ or \(...\) delimiters.
    if any(c in text for c in ("\x08", "\x09", "\x0c")):
        text = text.replace("\x0crac", "\\frac")
        text = text.replace("\x09imes", "\\times")
        text = text.replace("\x09herefore", "\\therefore")
        text = text.replace("\x09ext", "\\text")
        text = text.replace("\x09iangle", "\\triangle")
        text = text.replace("\x08ecause", "\\because")
        text = text.replace("\x0c", "\\f")
        text = text.replace("\x09", "\\t")
        text = text.replace("\x08", "\\b")
        text = re.sub(r'\\\((.+?)\\\)', r'$\1$', text)
        text = re.sub(r'\\\[(.+?)\\\]', r'$$\1$$', text)

    # Fix \r/\n inside LaTeX: restore \right, \rightarrow etc.
    # Must do this BEFORE general $...$ conversion so the patterns match.
    # These replacements are safe across the whole text since the patterns
    # are specific LaTeX words that never appear legitimately as control chars.
    if "\x0dight" in text or "\x0aight" in text:
        text = text.replace("\x0dightarrow", "\\rightarrow")
        text = text.replace("\x0dight", "\\right")
        text = text.replace("\x0aightarrow", "\\rightarrow")
        text = text.replace("\x0aight", "\\right")
    # For remaining \r/\n inside $ delimiters in HTML content (not <script> blocks):
    # only fix short inline math that doesn't span HTML tags or JS template literals.
    # We process only the non-script portions to avoid corrupting JS template literals
    # like `translate(${x}, 0)`.
    script_ranges = [(m.start(), m.end()) for m in re.finditer(r'<script[^>]*>.*?</script>', text, re.DOTALL)]
    def _in_script(pos):
        return any(s <= pos < e for s, e in script_ranges)
    def _fix_newlines_in_dollars(m):
        if _in_script(m.start()):
            return m.group(0)  # Don't touch $ inside <script> blocks
        content = m.group(1)
        if '<' in content or '>' in content:
            return m.group(0)  # Skip if it spans HTML tags
        content = content.replace("\x0d", "\\r")
        content = content.replace("\x0a", "\\n")
        return f'${content}$'
    text = re.sub(r'\$([^$]*[\x0a\x0d][^$]*)\$', _fix_newlines_in_dollars, text)

    # --- Fix 2: inject MathJax config for $ and \( delimiters ---
    # HTML source needs \\( so JS interprets it as \( (the MathJax delimiter)
    mathjax_config = (
        "<script>\nMathJax = {\n"
        "  tex: { inlineMath: [['\\\\(', '\\\\)'], ['$', '$']],"
        " displayMath: [['\\\\[', '\\\\]'], ['$$', '$$']] },\n"
        "  options: { skipHtmlTags: ['script','noscript','style','textarea','pre'] }\n"
        "};\n</script>\n"
    )
    if "MathJax =" not in text and "MathJax=" not in text:
        text = text.replace(
            '<script src="https://cdn.jsdelivr.net/npm/mathjax@3',
            mathjax_config + '<script src="https://cdn.jsdelivr.net/npm/mathjax@3',
            1,
        )

    return text.encode("utf-8")


@app.get("/html")
def serve_html():
    key = request.args.get("key", "")
    scene = request.args.get("scene", "")
    if key not in SAMPLES:
        abort(404)
    exp_dir = Path(SAMPLES[key]["exp_dir"])
    html_path = exp_dir / "doc" / scene
    if not html_path.exists():
        abort(404)
    data = html_path.read_bytes()
    # Always apply fix: ensures MathJax config, \(→$ conversion, and
    # control char restoration for all scene HTML files
    data = _fix_scene_html(data)
    resp = make_response(data)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@app.get("/diagram")
def serve_diagram():
    key = request.args.get("key", "")
    if key not in SAMPLES or not SAMPLES[key]["diagram_path"]:
        abort(404)
    p = Path(SAMPLES[key]["diagram_path"])
    if not p.exists():
        abort(404)
    return send_file(p)


@app.get("/static_diagram")
def serve_static_diagram():
    """Serve the Gemini-3-Pro static problem diagram."""
    key = request.args.get("key", "")
    if key not in SELECTED or SELECTED[key]["type"] != "static":
        abort(404)
    diag = SELECTED[key].get("static_diagram", "")
    if not diag:
        abort(404)
    p = Path(diag)
    if not p.exists():
        abort(404)
    return send_file(p)


@app.get("/static_scene")
def serve_static_scene():
    """Serve a Gemini-3-Pro static scene image."""
    key = request.args.get("key", "")
    scene = request.args.get("scene", "")
    if key not in SELECTED or SELECTED[key]["type"] != "static":
        abort(404)
    topic = SELECTED[key]["topic"]
    scene_path = STATIC_DIAGRAM_DIR / topic / "doc" / scene
    if not scene_path.exists() or scene_path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        abort(404)
    return send_file(scene_path)


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
