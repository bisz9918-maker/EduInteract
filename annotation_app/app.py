import json
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

EXP_TO_MODEL = {
    "exp_Gemini-3.1-Pro": "Gemini-3.1-Pro",
    "exp_kimik26": "Kimi-K2.6",
    "exp_qwen35_122b": "Qwen3.5-122B",
    "exp_qwen35_397b": "Qwen3.5-397B",
    "exp_qwen36_27b": "Qwen3.6-27B",
}

EVAL_TO_EXP = {
    "evaluate_Gemini-3.1-Pro": "exp_Gemini-3.1-Pro",
    "evaluate_kimi26": "exp_kimik26",
    "evaluate_qwen35_122b": "exp_qwen35_122b",
    "evaluate_qwen35_397b": "exp_qwen35_397b",
    "evaluate_qwen36_27b": "exp_qwen36_27b",
}

MODELS_ORDER = ["Gemini-3.1-Pro", "Kimi-K2.6", "Qwen3.5-397B", "Qwen3.5-122B", "Qwen3.6-27B"]

DIMENSIONS = [
    ("prob_align", "Problem Alignment (题图匹配)"),
    ("interact", "Interactive Functionality (交互功能)"),
    ("visual", "Visual Quality (视觉质量)"),
    ("pedagogy", "Pedagogical Effectiveness (教学效果)"),
    ("logic", "Logical Coherence (逻辑连贯)"),
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


def build_samples() -> dict:
    """Scan output dirs and collect evaluated topics with HTML scenes."""
    samples = {}
    for eval_dir_name, exp_dir_name in EVAL_TO_EXP.items():
        eval_dir = OUTPUT_DIR / eval_dir_name
        exp_dir = OUTPUT_DIR / exp_dir_name
        if not eval_dir.exists() or not exp_dir.exists():
            continue
        model = EXP_TO_MODEL.get(exp_dir_name, exp_dir_name)

        for topic_dir in sorted(eval_dir.iterdir()):
            if not topic_dir.is_dir() or not topic_dir.name.startswith("problem_"):
                continue
            report_path = topic_dir / "evaluation_report.xml"
            if not report_path.exists():
                continue
            topic = topic_dir.name
            key = f"{model}/{topic}"

            # Collect scene HTML files from exp dir
            doc_dir = exp_dir / topic / "doc"
            scenes = sorted([f.name for f in doc_dir.glob("scene*.html")]) if doc_dir.exists() else []

            # Parse evaluation scores
            scores = {}
            text = report_path.read_text(encoding="utf-8")
            for tag, idx in [("dim1_accuracy", 1), ("dim2_interaction", 2),
                             ("dim3_visual", 3), ("dim4_pedagogy", 4),
                             ("dim5_logic_coherence", 5)]:
                m = re.search(rf'<{tag}\s+score="([\d.]+)"', text)
                if m:
                    scores[f"dim{idx}"] = float(m.group(1))

            # Get full outline as rendered HTML
            outline_html = ""
            outline_files = list((exp_dir / topic).glob("*_scene_outline.txt"))
            if outline_files:
                outline_text = outline_files[0].read_text(encoding="utf-8")
                # Extract all TEXT_k blocks
                text_blocks = re.findall(r'<TEXT_\d+>(.*?)</TEXT_\d+>', outline_text, re.DOTALL)
                if text_blocks:
                    full_md = "\n\n---\n\n".join(b.strip() for b in text_blocks)
                    # Dedent: remove common leading whitespace per line
                    lines = full_md.split('\n')
                    cleaned = []
                    for line in lines:
                        # Strip up to 4 spaces of common indent
                        cleaned.append(line.lstrip())
                    full_md = '\n'.join(cleaned)
                    outline_html = render_markdown(full_md)

            # Problem diagram
            diagram_path = ""
            diagram_file = exp_dir / topic / "problem_diagram.png"
            if diagram_file.exists():
                diagram_path = str(diagram_file)

            samples[key] = {
                "model": model,
                "topic": topic,
                "scenes": scenes,
                "auto_scores": scores,
                "outline_html": outline_html,
                "diagram_path": diagram_path,
                "exp_dir": str(exp_dir / topic),
            }

    return samples


SAMPLES = build_samples()
KEYS = list(SAMPLES.keys())

if ANNOTATIONS_JSON.exists():
    with open(ANNOTATIONS_JSON, encoding="utf-8") as f:
        annotations = json.load(f)
else:
    annotations = {}


def save_annotations():
    with open(ANNOTATIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(annotations, f, ensure_ascii=False, indent=2)


# ── API ────────────────────────────────────────────────────────────────────────

@app.get("/api/keys")
def api_keys():
    return jsonify({"keys": KEYS, "dimensions": DIMENSIONS, "models": MODELS_ORDER})


@app.get("/api/annotations")
def api_annotations():
    return jsonify(annotations)


@app.get("/api/doc/<path:key>")
def api_doc(key):
    if key not in SAMPLES:
        abort(404)
    s = SAMPLES[key]
    # Build URLs for scene HTML files
    scene_urls = [f"/html?key={key}&scene={sn}" for sn in s["scenes"]]
    return jsonify({
        "model": s["model"],
        "topic": s["topic"],
        "outline_html": s["outline_html"],
        "diagram_url": f"/diagram?key={key}" if s["diagram_path"] else "",
        "scenes": scene_urls,
        "scene_names": s["scenes"],
        "auto_scores": s["auto_scores"],
    })


@app.post("/api/annotate")
def api_annotate():
    data = request.get_json()
    key = data.get("key")
    scores = data.get("scores")
    annotator = data.get("annotator", "")
    if not key or key not in SAMPLES:
        abort(400)
    annotations[key] = {"annotator": annotator, "scores": scores}
    save_annotations()
    return jsonify({"ok": True, "total_annotated": len(annotations)})


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
