import os
import re
from typing import Optional, List, Dict


def _markdown_to_html(text: str) -> str:
    """Convert a subset of Markdown to HTML, preserving LaTeX math delimiters for MathJax.

    Handles: headings, bold, italic, inline code, ordered/unordered lists, paragraphs (<p>).
    Math spans ($...$, $$...$$, \\(...\\), \\[...\\]) are left untouched.
    """
    # Protect math regions from Markdown processing
    math_blocks = []

    def protect(m):
        math_blocks.append(m.group(0))
        return f'\x00MATH{len(math_blocks)-1}\x00'

    # Protect display math first, then inline math
    text = re.sub(r'\$\$[\s\S]*?\$\$', protect, text)
    text = re.sub(r'\\\[[\s\S]*?\\\]', protect, text)
    text = re.sub(r'\\\([\s\S]*?\\\)', protect, text)
    text = re.sub(r'\$[^\$\n]+?\$', protect, text)

    lines = text.split('\n')
    html_lines = []
    in_ul = False
    in_ol = False
    para_lines = []   # buffer for current paragraph lines

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            html_lines.append('</ul>')
            in_ul = False
        if in_ol:
            html_lines.append('</ol>')
            in_ol = False

    def flush_para():
        """Flush buffered paragraph lines as a <p> block."""
        if para_lines:
            html_lines.append('<p>' + '<br>'.join(para_lines) + '</p>')
            para_lines.clear()

    def inline(s):
        # Bold+italic
        s = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', s)
        # Bold
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'__(.+?)__', r'<strong>\1</strong>', s)
        # Italic
        s = re.sub(r'\*(.+?)\*', r'<em>\1</em>', s)
        s = re.sub(r'_(.+?)_', r'<em>\1</em>', s)
        # Inline code
        s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
        return s

    for line in lines:
        # Headings
        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if m:
            flush_para()
            close_lists()
            level = len(m.group(1))
            html_lines.append(f'<h{level}>{inline(m.group(2))}</h{level}>')
            continue

        # Unordered list
        m = re.match(r'^[\*\-\+]\s+(.*)', line)
        if m:
            flush_para()
            if in_ol:
                html_lines.append('</ol>')
                in_ol = False
            if not in_ul:
                html_lines.append('<ul>')
                in_ul = True
            html_lines.append(f'<li>{inline(m.group(1))}</li>')
            continue

        # Ordered list
        m = re.match(r'^\d+\.\s+(.*)', line)
        if m:
            flush_para()
            if in_ul:
                html_lines.append('</ul>')
                in_ul = False
            if not in_ol:
                html_lines.append('<ol>')
                in_ol = True
            html_lines.append(f'<li>{inline(m.group(1))}</li>')
            continue

        # Blank line → flush paragraph, close lists
        if line.strip() == '':
            flush_para()
            close_lists()
            continue

        # Horizontal rule
        if re.match(r'^[\-\*\_]{3,}\s*$', line):
            flush_para()
            close_lists()
            html_lines.append('<hr>')
            continue

        # Regular text line → buffer into paragraph
        close_lists()
        para_lines.append(inline(line.strip()))

    flush_para()
    close_lists()
    result = '\n'.join(html_lines)

    # Restore math regions
    for i, m in enumerate(math_blocks):
        result = result.replace(f'\x00MATH{i}\x00', m)

    return result


def _scope_scene_styles(css: str, scene_num: int) -> str:
    """Remove body/html rules from scene CSS and scope remaining rules under the scene container."""
    # Remove body and html rules entirely (they would break global layout)
    css = re.sub(r'(?:body|html)\s*\{[^}]*\}', '', css, flags=re.IGNORECASE)
    # Remove min-height: 100vh rules (breaks container sizing)
    css = re.sub(r'min-height\s*:\s*100vh\s*;?', '', css)
    # Remove display:flex / align-items / justify-content from remaining top-level rules
    # (those were on body, now cleaned; leave them if they're in specific classes)
    return css.strip()


def _namespace_scene(html: str, css: str, scene_num: int) -> tuple:
    """Ensure all IDs in the scene body are unique and CSS selectors match them.

    Fixes two problems:
    1. Diff-patch renamed HTML id (e.g. scene-container → scene2-container) but left
       CSS selector as #scene-container — we detect orphaned CSS selectors and fix them.
    2. Multiple scenes sharing the same generic id — we add scene{n}- prefix.
    """
    prefix = f'scene{scene_num}-'

    def _fix_in_inline_styles(h, old_sel, new_sel):
        def replacer(m):
            return re.sub(rf'#{re.escape(old_sel)}\b', f'#{new_sel}', m.group(0))
        return re.sub(r'<style[^>]*>.*?</style>', replacer, h, flags=re.DOTALL | re.IGNORECASE)

    # Step 1: Fix orphaned CSS selectors (CSS references ids not present in HTML)
    ids_in_html = set(re.findall(r'id=["\']([^"\']+)["\']', html))

    # Extract CSS id selectors, excluding hex colors (#fff, #000000, etc.)
    css_selectors = set()
    for m in re.finditer(r'#([a-zA-Z][\w-]*)', css):
        css_selectors.add(m.group(1))

    for sel in list(css_selectors):
        if sel in ids_in_html:
            continue  # already matched, fine

        # Orphaned selector: try to find the renamed version in HTML
        # e.g. CSS: #scene-container → HTML: scene2-container
        # Strategy: look for an HTML id that ends with the selector's suffix,
        # or where the selector is a base name and HTML id is scene{n}-base
        matched = None

        # Check if scene{n}-{sel} exists in HTML
        prefixed = prefix + sel
        if prefixed in ids_in_html:
            matched = prefixed
        else:
            # Check if any HTML id ends with -{sel} or is {sel} with scene prefix injected
            for hid in ids_in_html:
                # e.g. sel="scene-container", hid="scene2-container"
                # strip "scene" prefix from sel and see if hid matches pattern
                if sel.startswith('scene-') and hid.startswith(f'scene{scene_num}-'):
                    sel_suffix = sel[len('scene-'):]  # "container"
                    hid_suffix = hid[len(f'scene{scene_num}-'):]  # "container"
                    if sel_suffix == hid_suffix:
                        matched = hid
                        break

        if matched:
            css = re.sub(rf'#{re.escape(sel)}\b', f'#{matched}', css)
            html = _fix_in_inline_styles(html, sel, matched)

    # Step 2: Add scene{n}- prefix to all ids that don't have it yet
    ids_in_html = set(re.findall(r'id=["\']([^"\']+)["\']', html))
    for orig_id in sorted(ids_in_html, key=len, reverse=True):
        if orig_id.startswith(prefix):
            continue
        new_id = prefix + orig_id

        html = html.replace(f'id="{orig_id}"', f'id="{new_id}"')
        html = html.replace(f"id='{orig_id}'", f"id='{new_id}'")
        html = html.replace(f'getElementById("{orig_id}")', f'getElementById("{new_id}")')
        html = html.replace(f"getElementById('{orig_id}')", f"getElementById('{new_id}')")

        css = re.sub(rf'#{re.escape(orig_id)}\b', f'#{new_id}', css)
        html = _fix_in_inline_styles(html, orig_id, new_id)

    return html, css


class HTMLRenderer:
    """Class for saving and combining HTML/CSS/JS educational diagram scenes."""

    def __init__(self, output_dir="output", print_response=False, use_visual_fix_code=False, scene_model=None):
        self.output_dir = output_dir
        self.print_response = print_response
        self.use_visual_fix_code = use_visual_fix_code
        self.scene_model = scene_model

    def save_scene_html(self, code: str, path: str) -> None:
        """Write HTML code directly to a file.

        Args:
            code (str): The complete HTML code for the scene.
            path (str): Absolute file path to write to.
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(code)

    def _extract_body_content(self, html: str) -> dict:
        """Extract the body content, style blocks, and script blocks from a standalone HTML file.

        Returns a dict with keys: 'styles', 'body', 'scripts'
        """
        # Extract <style> blocks inside <head>
        styles = re.findall(r'<style[^>]*>(.*?)</style>', html, re.DOTALL | re.IGNORECASE)

        # Extract <body> content (everything between <body> and </body>)
        body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
        body_content = body_match.group(1).strip() if body_match else html

        # Extract <script> blocks from within body (or anywhere after head)
        # We'll keep inline scripts as-is within body_content

        return {
            'styles': '\n'.join(styles),
            'body': body_content,
        }

    def _extract_cdn_links(self, html: str) -> List[str]:
        """Extract CDN <script> and <link> tags from <head>."""
        head_match = re.search(r'<head[^>]*>(.*?)</head>', html, re.DOTALL | re.IGNORECASE)
        if not head_match:
            return []
        head_content = head_match.group(1)
        # Find all script src and link href that look like CDN URLs
        scripts = re.findall(r'<script[^>]+src=["\']https?://[^"\']+["\'][^>]*(?:></script>|/>)', head_content, re.IGNORECASE)
        links = re.findall(r'<link[^>]+href=["\']https?://[^"\']+["\'][^>]*/>', head_content, re.IGNORECASE)
        return scripts + links

    def build_solution_html(self, topic: str, scene_html_files: Dict[int, str],
                             text_blocks: Dict[int, str], output_path: str) -> None:
        """Combine all scene HTML files and text blocks into a single solution.html.

        Each scene's <script> and <style> are inlined with namespacing to avoid conflicts.
        Text blocks are wrapped in <section class="text-block">.

        Args:
            topic (str): Topic title for the <h1> heading.
            scene_html_files (Dict[int, str]): Mapping of scene_number → path to scene HTML file.
            text_blocks (Dict[int, str]): Mapping of text_index → HTML/Markdown text content.
            output_path (str): Path to write solution.html.
        """
        # Collect all unique CDN links across all scenes
        all_cdn_links = []
        seen_cdns = set()
        for scene_num, html_path in sorted(scene_html_files.items()):
            if not os.path.exists(html_path):
                continue
            with open(html_path, 'r', encoding='utf-8') as f:
                html = f.read()
            for link in self._extract_cdn_links(html):
                # Deduplicate by src/href URL
                url_match = re.search(r'(?:src|href)=["\']([^"\']+)["\']', link, re.IGNORECASE)
                if url_match:
                    url = url_match.group(1)
                    if url not in seen_cdns:
                        seen_cdns.add(url)
                        all_cdn_links.append(link)

        # Always include MathJax if not already included
        mathjax_url = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"
        if mathjax_url not in seen_cdns:
            all_cdn_links.append(
                f'<script id="MathJax-script" async src="{mathjax_url}"></script>'
            )

        nav_items = ''.join(
            f' <a href="#scene{n}-container">Scene {n}</a> |'
            for n in sorted(scene_html_files.keys())
        ).rstrip('|')

        html_parts = [
            '<!DOCTYPE html>',
            '<html lang="zh">',
            '<head>',
            '    <meta charset="UTF-8">',
            '    <meta name="viewport" content="width=device-width, initial-scale=1.0">',
            f'    <title>{topic}</title>',
        ]
        for cdn in all_cdn_links:
            html_parts.append(f'    {cdn}')
        html_parts += [
            '    <style>',
            '        body { font-family: sans-serif; max-width: 960px; margin: 0 auto; padding: 20px; background: #fff; }',
            '        .scene-container { border: 1px solid #ddd; border-radius: 8px; margin: 24px 0; padding: 16px; background: #fff; overflow: auto; }',
            '        .text-block { line-height: 1.8; margin: 16px 0; }',
            '        nav { position: sticky; top: 0; background: white; padding: 8px 0; border-bottom: 1px solid #eee; z-index: 100; font-size: 14px; }',
            '        nav a { margin: 0 6px; text-decoration: none; color: #1565c0; }',
            '    </style>',
            '</head>',
            '<body>',
            f'    <h1>{topic}</h1>',
            f'    <nav>场景导航：{nav_items}</nav>',
        ]

        return html_parts, all_cdn_links, seen_cdns

    def build_solution_html_complete(self, topic: str, tokens: List[dict],
                                      scene_html_files: Dict[int, str],
                                      output_path: str) -> None:
        """Build solution.html from parsed outline tokens (TEXT + SCENE interleaved).

        Args:
            topic (str): Topic title.
            tokens (List[dict]): Parsed outline tokens, each with 'type' ('text'|'scene') and 'k' (index).
                                 Text tokens have 'content'; scene tokens have 'k' = scene number.
            scene_html_files (Dict[int, str]): Mapping of scene_number → path to scene HTML file.
            output_path (str): Output path for solution.html.
        """
        # Collect CDN links
        all_cdn_links = []
        seen_cdns = set()
        for scene_num, html_path in sorted(scene_html_files.items()):
            if not os.path.exists(html_path):
                continue
            with open(html_path, 'r', encoding='utf-8') as f:
                html = f.read()
            for link in self._extract_cdn_links(html):
                url_match = re.search(r'(?:src|href)=["\']([^"\']+)["\']', link, re.IGNORECASE)
                if url_match:
                    url = url_match.group(1)
                    if url not in seen_cdns:
                        seen_cdns.add(url)
                        all_cdn_links.append(link)

        mathjax_url = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"
        if mathjax_url not in seen_cdns:
            all_cdn_links.append(
                f'<script id="MathJax-script" async src="{mathjax_url}"></script>'
            )

        scene_numbers = sorted({t['k'] for t in tokens if t['type'] == 'scene'})
        nav_items = ' | '.join(f'<a href="#scene{n}-wrapper">Scene {n}</a>' for n in scene_numbers)

        lines = [
            '<!DOCTYPE html>',
            '<html lang="zh">',
            '<head>',
            '    <meta charset="UTF-8">',
            '    <meta name="viewport" content="width=device-width, initial-scale=1.0">',
            f'    <title>{topic}</title>',
            '    <!-- MathJax 配置：启用 $...$ 行内公式和 $$...$$ 块级公式 -->',
            '    <script>',
            '    MathJax = {',
            '      tex: { inlineMath: [["$","$"], ["\\\\(","\\\\)"]], displayMath: [["$$","$$"], ["\\\\[","\\\\]"]], processEscapes: true },',
            '      options: { skipHtmlTags: ["script","noscript","style","textarea","pre","code"] }',
            '    };',
            '    </script>',
            f'    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>',
        ]
        # Add remaining CDN links (skip MathJax, already added)
        for cdn in all_cdn_links:
            if 'mathjax' not in cdn.lower():
                lines.append(f'    {cdn}')
        lines += [
            '    <style>',
            '        body { font-family: "Segoe UI", Arial, sans-serif; max-width: 960px; margin: 0 auto; padding: 20px 32px; background: #fff; color: #222; }',
            '        h1 { font-size: 1.5em; border-bottom: 2px solid #eee; padding-bottom: 8px; }',
            '        .scene-container { border: 1px solid #ddd; border-radius: 8px; margin: 24px 0; padding: 16px; background: #fafafa; overflow: auto; }',
            '        .text-block { line-height: 1.9; margin: 16px 0; font-size: 1em; }',
            '        .text-block h1, .text-block h2, .text-block h3 { margin-top: 1em; }',
            '        .text-block ul, .text-block ol { padding-left: 1.8em; margin: 8px 0; }',
            '        .text-block li { margin: 4px 0; }',
            '        .text-block code { background: #f3f3f3; padding: 1px 5px; border-radius: 3px; font-size: 0.92em; }',
            '        .text-block strong { color: #111; }',
            '        .text-block hr { border: none; border-top: 1px solid #ddd; margin: 12px 0; }',
            '        nav { position: sticky; top: 0; background: white; padding: 8px 0; border-bottom: 1px solid #eee; z-index: 100; font-size: 14px; }',
            '        nav a { margin: 0 6px; text-decoration: none; color: #1565c0; }',
            '        nav a:hover { text-decoration: underline; }',
            '    </style>',
            '</head>',
            '<body>',
            f'    <h1>{topic}</h1>',
            f'    <nav>场景导航：{nav_items}</nav>',
        ]

        for token in tokens:
            if token['type'] == 'text':
                raw = token['content'].strip('\n')
                raw = '\n'.join(line.lstrip() for line in raw.splitlines()).strip()
                html_content = _markdown_to_html(raw)
                lines.append('    <section class="text-block">')
                lines.append(f'        {html_content}')
                lines.append('    </section>')
            else:
                scene_num = token['k']
                html_path = scene_html_files.get(scene_num)
                lines.append(f'    <section class="scene-container" id="scene{scene_num}-wrapper">')

                if html_path and os.path.exists(html_path):
                    with open(html_path, 'r', encoding='utf-8') as f:
                        scene_html = f.read()
                    extracted = self._extract_body_content(scene_html)

                    body_content = extracted['body']
                    styles = extracted['styles']

                    # Namespace all IDs to avoid conflicts with other scenes
                    body_content, styles = _namespace_scene(body_content, styles, scene_num)

                    # Scope and sanitize scene styles (remove body/html rules)
                    clean_styles = _scope_scene_styles(styles, scene_num)
                    if clean_styles:
                        lines.append(f'        <style>{clean_styles}</style>')

                    lines.append(f'        {body_content}')
                else:
                    lines.append(f'        <p><em>[Scene {scene_num} 渲染失败或文件缺失]</em></p>')

                lines.append('    </section>')

        lines += [
            '</body>',
            '</html>',
        ]

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print(f"✓ solution.html 生成完成：{output_path}")

    async def render_scene(self, code: str, file_prefix: str, curr_scene: int, curr_version: int,
                           code_dir: str, media_dir: str, max_visual_retries: int = 3,
                           use_visual_fix_code=False, visual_self_reflection_func=None,
                           banned_reasonings=None, scene_trace_id=None, topic=None,
                           session_id=None, implementation_plan: str = "",
                           problem_image=None):
        """Save HTML code to file (no rendering needed — HTML is directly usable).

        Returns:
            tuple: (code, curr_version, error_message) where error_message is None on success
        """
        try:
            file_path = os.path.join(code_dir, f"{file_prefix}_scene{curr_scene}_v{curr_version}.html")
            self.save_scene_html(code, file_path)
            print(f"✓ Scene {curr_scene} v{curr_version} HTML saved: {file_path}")

            # Mark success
            succ_marker_dir = os.path.join(self.output_dir, file_prefix, f"scene{curr_scene}")
            os.makedirs(succ_marker_dir, exist_ok=True)
            with open(os.path.join(succ_marker_dir, "succ_rendered.txt"), "w") as f:
                f.write(f"v{curr_version}")

            return code, curr_version, None

        except Exception as e:
            error_msg = str(e)
            error_log = os.path.join(code_dir, f"{file_prefix}_scene{curr_scene}_v{curr_version}_error.log")
            os.makedirs(code_dir, exist_ok=True)
            with open(error_log, "w") as f:
                f.write(f"Exception during save:\n{error_msg}\n")
            return code, curr_version, error_msg

    def export_scene_html_to_doc(self, file_prefix: str, scene_number: int,
                                  version_number: int) -> Optional[str]:
        """Copy the scene HTML into {output_dir}/{file_prefix}/doc for solution.html embedding.

        Returns the destination path, or None if not found.
        """
        code_dir = os.path.join(self.output_dir, file_prefix, f"scene{scene_number}", "code")
        src = os.path.join(code_dir, f"{file_prefix}_scene{scene_number}_v{version_number}.html")

        if not os.path.exists(src):
            # Find latest version
            if os.path.isdir(code_dir):
                htmls = [f for f in os.listdir(code_dir) if f.endswith('.html') and f'scene{scene_number}' in f]
                if htmls:
                    htmls.sort(
                        key=lambda x: int(re.search(r'_v(\d+)\.html$', x).group(1))
                        if re.search(r'_v(\d+)\.html$', x) else 0
                    )
                    src = os.path.join(code_dir, htmls[-1])
                else:
                    return None
            else:
                return None

        dst_dir = os.path.join(self.output_dir, file_prefix, "doc")
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, f"scene{scene_number}.html")

        with open(src, 'r', encoding='utf-8') as f:
            content = f.read()
        with open(dst, 'w', encoding='utf-8') as f:
            f.write(content)

        return dst


# Backwards-compatible alias
ExplanationRenderer = HTMLRenderer
