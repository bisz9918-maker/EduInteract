#!/usr/bin/env python3
"""
Python 桥接脚本：从 stdin 读取 JSON 命令，调用 ExplanationGenerator，
通过 stdout 逐行输出 JSON 事件。

协议：
  输入 (stdin, 一行 JSON):
    {"action": "generate", "description": "...", "topic": "...", "model": "...", "image": "base64..."}
    {"action": "modify_scene", "topic": "...", "scene_number": 1, "user_request": "...", "model": "...", "use_oah": true}

  输出 (stdout, 每行一个 JSON):
    {"type": "progress", "message": "..."}
    {"type": "scene_ready", "scene": 1, "url": "doc/..."}
    {"type": "done", "scenes": [...], "texts": [...]}
    {"type": "error", "message": "..."}
"""
import asyncio
import base64
import datetime
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# 项目根目录 (worker.py 在 teacher_app/src/bridge/ 下，需要跳 4 级)
ROOT = Path(__file__).resolve().parent.parent.parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

from PIL import Image

# oah_client.py 在 VisualSolver 根目录而非 visual_solver 包内，
# 包内代码用 from oah_client import OAHClient，需要把根目录加入 sys.path
_VISUAL_SOLVER_ROOT = str(ROOT / "VisualSolver")
if _VISUAL_SOLVER_ROOT not in sys.path:
    sys.path.insert(0, _VISUAL_SOLVER_ROOT)

from visual_solver import ExplanationGenerator
from visual_solver.mllm_tools.litellm import LiteLLMWrapper
from visual_solver.src.utils.utils import parse_scene_outline_tokens, _extract_code, extract_xml
from visual_solver.mllm_tools.utils import _prepare_text_inputs

# Patch LiteLLMWrapper.__init__：远程包中 self.custom_api_base 在赋值前被引用，
# 此处修复属性初始化顺序（仅当 use_oah=True 时不实际调用 LLM，但初始化仍需通过）
_orig_llm_init = LiteLLMWrapper.__init__
def _patched_llm_init(self, *args, **kwargs):
    self.custom_api_base = os.getenv("CUSTOM_API_BASE", None)
    self.custom_api_key = os.getenv("CUSTOM_API_KEY", "sk-none")
    _orig_llm_init(self, *args, **kwargs)
LiteLLMWrapper.__init__ = _patched_llm_init

OUTPUT_DIR = str(ROOT / "output" / "teacher")

# 保存原始 stdout 用于 JSON 事件输出，然后将 sys.stdout 重定向到 stderr
# 这样所有 Python 模块的 print() 都不会污染 JSON 协议
_real_stdout = sys.__stdout__
_event_fd = os.fdopen(os.dup(sys.stdout.fileno()), 'w')
sys.stdout = sys.stderr


def emit(event_type: str, **kwargs):
    """输出一行 JSON 到原始 stdout，立即 flush。"""
    line = json.dumps({"type": event_type, **kwargs}, ensure_ascii=False)
    _event_fd.write(line + "\n")
    _event_fd.flush()


def _decode_image(image_b64: Optional[str]) -> Optional[Image.Image]:
    """将 base64 字符串解码为 PIL Image。"""
    if not image_b64:
        return None
    try:
        data = base64.b64decode(image_b64)
        return Image.open(io.BytesIO(data))
    except Exception:
        return None


def _make_generator(model: str) -> ExplanationGenerator:
    llm = LiteLLMWrapper(
        model_name=model,
        temperature=0.7,
        print_cost=True,
        verbose=False,
        use_langfuse=False,
    )
    return ExplanationGenerator(
        planner_model=llm,
        output_dir=OUTPUT_DIR,
        verbose=False,
        use_rag=False,
        use_context_learning=False,
        use_visual_fix_code=False,
        use_langfuse=False,
        max_scene_concurrency=3,
        use_oah=True,
    )


def _find_latest_scene_code(file_prefix: str, scene_number: int) -> Optional[str]:
    """查找指定 scene 的最新版本 HTML 代码。"""
    code_dir = Path(OUTPUT_DIR) / file_prefix / f"scene{scene_number}" / "code"
    if not code_dir.exists():
        return None

    versions = []
    for f in code_dir.iterdir():
        m = re.match(rf"{re.escape(file_prefix)}_scene{scene_number}_v(\d+)\.html$", f.name)
        if m:
            versions.append((int(m.group(1)), f))

    if not versions:
        return None

    versions.sort(key=lambda x: x[0])
    return versions[-1][1].read_text()


def _find_scene_html_url(file_prefix: str, scene_number: int) -> Optional[str]:
    """查找 scene 的 HTML 文件 URL。"""
    scene_dir = Path(OUTPUT_DIR) / file_prefix
    # 查找 scene HTML（code 目录中的最新版本）
    code_dir = scene_dir / f"scene{scene_number}" / "code"
    if code_dir.exists():
        candidates = sorted(code_dir.glob(f"{file_prefix}_scene{scene_number}_v*.html"))
        if candidates:
            rel = candidates[-1].relative_to(ROOT)
            return f"doc/{rel}"

    # fallback: 顶层目录
    candidates = list(scene_dir.glob(f"scene{scene_number}*.html"))
    if not candidates:
        candidates = list(scene_dir.glob(f"{file_prefix}_scene{scene_number}_*.html"))
    if candidates:
        rel = candidates[-1].relative_to(ROOT)
        return f"doc/{rel}"
    return None


async def run_generate(description: str, topic: str, model: str, image_b64: Optional[str] = None):
    emit("progress", message="正在初始化生成器…", percent=0)
    gen = _make_generator(model)
    problem_image = _decode_image(image_b64)

    if problem_image:
        emit("progress", message=f"检测到题目图片 ({problem_image.size[0]}x{problem_image.size[1]})", percent=2)

    file_prefix = re.sub(r'[^a-z0-9_]+', '_', topic.lower())
    scenes_done = 0
    total_scenes = [4]  # mutable default, updated lazily

    def _get_total_scenes():
        """Lazily read total scene count from outline file."""
        outline_path = Path(OUTPUT_DIR) / file_prefix / f"{file_prefix}_scene_outline.txt"
        if outline_path.exists():
            content = outline_path.read_text()
            count = len(re.findall(r'<SCENE_(\d+)>[^<]', content))
            if count > 0:
                total_scenes[0] = count
        return total_scenes[0]

    # ── monkey-patch: render_scene → emit scene_ready ──────────────────
    original_render = gen.explanation_renderer.render_scene

    async def patched_render(*args, **kwargs):
        nonlocal scenes_done
        result = await original_render(*args, **kwargs)
        curr_scene = None
        for i, a in enumerate(args):
            if isinstance(a, int) and i >= 2:
                curr_scene = a
                break
        if curr_scene is None:
            curr_scene = kwargs.get('curr_scene')
        if curr_scene is None:
            return result
        code_dir = Path(OUTPUT_DIR) / file_prefix / f"scene{curr_scene}" / "code"
        if code_dir.exists():
            html_candidates = sorted(code_dir.glob(f"{file_prefix}_scene{curr_scene}_v*.html"))
            if html_candidates:
                rel = html_candidates[-1].relative_to(ROOT)
                scenes_done += 1
                n = _get_total_scenes()
                pct = 30 + scenes_done * 60 // max(n, 1)
                emit("scene_ready", scene=curr_scene, url=f"doc/{rel}")
                emit("progress", message=f"Scene {curr_scene} 生成完成 ({scenes_done}/{n})", percent=min(pct, 90))
        return result

    gen.explanation_renderer.render_scene = patched_render

    # ── monkey-patch: process_scene → skip 已渲染 + emit scene_ready ──
    original_process_scene = gen.process_scene

    async def patched_process_scene(i, *args, **kwargs):
        curr_scene = i + 1
        scene_dir = Path(OUTPUT_DIR) / file_prefix / f"scene{curr_scene}"
        succ_path = scene_dir / "succ_rendered.txt"
        if succ_path.exists():
            code_dir = scene_dir / "code"
            if code_dir.exists():
                htmls = sorted(code_dir.glob(f"{file_prefix}_scene{curr_scene}_v*.html"))
                if htmls:
                    rel = htmls[-1].relative_to(ROOT)
                    scenes_done_local = sum(
                        1 for d in (Path(OUTPUT_DIR) / file_prefix).iterdir()
                        if d.is_dir() and re.match(r'scene\d+$', d.name) and (d / "succ_rendered.txt").exists()
                    )
                    n = _get_total_scenes()
                    pct = 30 + scenes_done_local * 60 // max(n, 1)
                    emit("scene_ready", scene=curr_scene, url=f"doc/{rel}")
                    emit("progress", message=f"Scene {curr_scene} 已完成 ({scenes_done_local}/{n})", percent=min(pct, 90))
            print(f"Scene {curr_scene} already successfully rendered, skipping")
            return
        return await original_process_scene(i, *args, **kwargs)

    gen.process_scene = patched_process_scene

    # ── monkey-patch: generate_html_code → emit progress during OAH ────
    original_generate_code = gen.code_generator.generate_html_code

    async def patched_generate_code(*args, **kwargs):
        scene_number = kwargs.get('scene_number') or (args[4] if len(args) > 4 else None)
        if scene_number and gen.code_generator.use_oah:
            n = _get_total_scenes()
            emit("progress", message=f"Scene {scene_number} 正在通过 OAH 生成代码…", percent=20 + (scene_number - 1) * 60 // max(n, 1))
        result = await original_generate_code(*args, **kwargs)
        return result

    gen.code_generator.generate_html_code = patched_generate_code

    # ── monkey-patch: planner OAH steps → emit progress ───────────────
    if hasattr(gen, 'explanation_planner'):
        original_generate_outline = gen.explanation_planner.generate_scene_outline
        original_generate_impl = gen.explanation_planner._generate_scene_implementation_single

        async def patched_generate_outline(*args, **kwargs):
            emit("progress", message="正在规划图示大纲…", percent=5)
            return await original_generate_outline(*args, **kwargs)

        async def patched_generate_impl(*args, **kwargs):
            scene_num = kwargs.get('scene_num') or (args[3] if len(args) > 3 else '?')
            if gen.explanation_planner.use_oah:
                n = _get_total_scenes()
                emit("progress", message=f"Scene {scene_num} 正在生成实现方案…", percent=10 + (scene_num - 1) * 5 // max(n, 1))
            return await original_generate_impl(*args, **kwargs)

        gen.explanation_planner.generate_scene_outline = patched_generate_outline
        gen.explanation_planner._generate_scene_implementation_single = patched_generate_impl

    emit("progress", message="正在规划图示大纲…", percent=5)

    try:
        await gen.generate_html_diagrams(
            topic=topic,
            description=description,
            max_retries=2,
            problem_image=problem_image,
        )
    except Exception as e:
        emit("error", message=str(e))
        return

    # 收集结果
    scene_dir = Path(OUTPUT_DIR) / file_prefix

    scenes = []
    # Scene HTML 存放在 scene{N}/code/ 子目录中
    for d in sorted(scene_dir.iterdir()):
        m = re.match(r'scene(\d+)$', d.name)
        if m and d.is_dir():
            scene_num = int(m.group(1))
            code_dir = d / "code"
            if code_dir.exists():
                htmls = sorted(code_dir.glob(f"{file_prefix}_scene{scene_num}_v*.html"))
                if htmls:
                    rel = htmls[-1].relative_to(ROOT)
                    scenes.append({"name": htmls[-1].stem, "url": f"doc/{rel}"})

    texts = []
    outline_path = scene_dir / f"{file_prefix}_scene_outline.txt"
    if outline_path.exists():
        tokens = parse_scene_outline_tokens(outline_path.read_text())
        texts = [t["content"] for t in tokens if t["type"] == "text"]

    emit("done", scenes=scenes, texts=texts)


async def run_modify_scene(topic: str, scene_number: int, user_request: str,
                           model: str, use_oah: bool = True,
                           problem_text: Optional[str] = None,
                           problem_image_b64: Optional[str] = None):
    """根据用户需求修改指定 scene 的 HTML 代码。"""
    file_prefix = re.sub(r'[^a-z0-9_]+', '_', topic.lower())

    emit("progress", message=f"正在读取 Scene {scene_number} 当前代码…")

    current_code = _find_latest_scene_code(file_prefix, scene_number)
    if not current_code:
        emit("error", message=f"未找到 Scene {scene_number} 的代码文件")
        return

    emit("progress", message="正在生成修改…")

    if use_oah:
        # ---- OAH 路径 ----
        from oah_client import OAHClient

        oah_url = os.getenv("OAH_API_URL", "")
        if not oah_url:
            emit("error", message="OAH_API_URL 未配置，无法使用 OAH 修改")
            return

        try:
            client = OAHClient(api_url=oah_url)
        except ValueError as e:
            emit("error", message=str(e))
            return

        spec = {
            "task": "modify_scene",
            "topic": topic,
            "scene_number": scene_number,
            "user_request": user_request,
            "problem_text": problem_text or "",
            "output_file": "modified_scene.html",
        }

        problem_image = _decode_image(problem_image_b64) if problem_image_b64 else None

        emit("progress", message="OAH 正在修改图示…", percent=10)

        try:
            new_code = await asyncio.to_thread(
                client.modify_scene_html,
                spec=spec,
                current_code=current_code,
                output_file="modified_scene.html",
                problem_image=problem_image,
            )
        except Exception as e:
            emit("error", message=f"OAH 修改失败: {e}")
            return
    else:
        # ---- LiteLLM 直调路径 ----
        gen = _make_generator(model)

        problem_context = f"\n题目原文：\n{problem_text}\n" if problem_text else ""

        prompt = f"""你是一个前端代码修改助手。{problem_context}
下面是当前 Scene {scene_number} 的完整 HTML/CSS/JS 代码：

```html
{current_code}
```

用户的修改需求：
{user_request}

请根据用户需求修改代码。输出修改后的完整 HTML 代码，用 <CODE> 标签包裹：

<CODE>
```html
（修改后的完整代码）
```
</CODE>

注意：
- 只修改用户要求的部分，保持其他部分不变
- 输出完整的 HTML 文件，不要省略任何部分
- 保持代码风格一致"""

        messages = _prepare_text_inputs(prompt)
        if problem_image_b64:
            try:
                problem_image = _decode_image(problem_image_b64)
                if problem_image:
                    messages.append({"type": "image", "content": problem_image})
            except Exception:
                pass

        try:
            response_text = await gen.code_generator.scene_model(
                messages,
                metadata={
                    "generation_name": "modify_scene",
                    "tags": [topic, f"scene{scene_number}", "modify"],
                }
            )
        except Exception as e:
            emit("error", message=f"LLM 调用失败: {e}")
            return

        # 提取代码
        new_code = None
        code_block_match = re.search(r'<CODE>(.*?)</CODE>', response_text, re.DOTALL)
        if code_block_match:
            inner = code_block_match.group(1)
            html_match = re.search(r'```html(.*?)```', inner, re.DOTALL)
            if html_match:
                new_code = html_match.group(1).strip()
            else:
                new_code = inner.strip()

        if not new_code:
            html_match = re.search(r'```html(.*?)```', response_text, re.DOTALL)
            if html_match:
                new_code = html_match.group(1).strip()

        if not new_code:
            emit("error", message="无法从 LLM 回复中提取 HTML 代码")
            return

    # 保存新版本
    code_dir = Path(OUTPUT_DIR) / file_prefix / f"scene{scene_number}" / "code"
    code_dir.mkdir(parents=True, exist_ok=True)

    # 找到当前最高版本号
    max_ver = 0
    for f in code_dir.iterdir():
        m = re.match(rf"{re.escape(file_prefix)}_scene{scene_number}_v(\d+)\.html$", f.name)
        if m:
            max_ver = max(max_ver, int(m.group(1)))

    new_ver = max_ver + 1
    new_path = code_dir / f"{file_prefix}_scene{scene_number}_v{new_ver}.html"
    new_path.write_text(new_code)

    emit("progress", message=f"Scene {scene_number} v{new_ver} 已保存")

    # 记录修改需求日志
    log_path = Path(OUTPUT_DIR) / file_prefix / "modify_log.json"
    try:
        log = json.loads(log_path.read_text()) if log_path.exists() else []
        log.append({
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "scene_number": scene_number,
            "version": f"v{new_ver}",
            "model": model,
            "user_request": user_request,
        })
        log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2))
    except Exception:
        pass

    # 更新 succ_rendered 标记
    succ_marker = Path(OUTPUT_DIR) / file_prefix / f"scene{scene_number}" / "succ_rendered.txt"
    succ_marker.write_text(f"v{new_ver}")

    # 输出 scene_ready
    rel = new_path.relative_to(ROOT)
    emit("scene_ready", scene=scene_number, url=f"doc/{rel}")
    emit("done", scenes=[{"name": new_path.stem, "url": f"doc/{rel}"}])


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError as e:
            emit("error", message=f"JSON parse error: {e}")
            continue

        action = cmd.get("action")
        if action == "generate":
            asyncio.run(run_generate(
                description=cmd.get("description", ""),
                topic=cmd.get("topic", ""),
                model=cmd.get("model", "Kimi-K25"),
                image_b64=cmd.get("image"),
            ))
        elif action == "modify_scene":
            asyncio.run(run_modify_scene(
                topic=cmd.get("topic", ""),
                scene_number=cmd.get("scene_number", 1),
                user_request=cmd.get("user_request", ""),
                model=cmd.get("model", "Kimi-K25"),
                use_oah=cmd.get("use_oah", True),
                problem_text=cmd.get("problem_text"),
                problem_image_b64=cmd.get("problem_image"),
            ))
        else:
            emit("error", message=f"Unknown action: {action}")

    _event_fd.close()


if __name__ == "__main__":
    main()
