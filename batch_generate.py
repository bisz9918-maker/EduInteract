#!/usr/bin/env python3
"""
批量处理 Zipped_Items 图片：OCR 识别 + 生成图示
用法: python3 batch_generate.py [--start 0] [--end 109] [--model Kimi-K25]
"""
import argparse
import asyncio
import base64
import io
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# ── 项目根目录 ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
if load_dotenv:
    load_dotenv(ROOT / ".env", override=True)

# VisualSolver 需要在 sys.path 上
_VS_ROOT = str(ROOT / "VisualSolver")
if _VS_ROOT not in sys.path:
    sys.path.insert(0, _VS_ROOT)

from PIL import Image

from visual_solver import ExplanationGenerator
from visual_solver.mllm_tools.litellm import LiteLLMWrapper
from visual_solver.src.utils.utils import parse_scene_outline_tokens

# 修复 LiteLLMWrapper.__init__ 属性初始化顺序
_orig_llm_init = LiteLLMWrapper.__init__
def _patched_llm_init(self, *args, **kwargs):
    self.custom_api_base = os.getenv("CUSTOM_API_BASE", None)
    self.custom_api_key = os.getenv("CUSTOM_API_KEY", "sk-none")
    _orig_llm_init(self, *args, **kwargs)
LiteLLMWrapper.__init__ = _patched_llm_init

# ── OCR ──────────────────────────────────────────────────────────────────────
def ocr_image(image: Image.Image) -> str:
    """调用 OCR API 识别图片文字。"""
    import ssl
    import urllib.request
    import urllib.error

    _ssl_ctx = ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE

    ocr_url = os.getenv("OCR_URL", "")
    ocr_key = os.getenv("OCR_KEY", "")
    ocr_mode = os.getenv("OCR_MODE", "openai")

    # 图片转 base64
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    if ocr_mode == "native":
        payload = json.dumps({"image_base64": b64}).encode()
        req = urllib.request.Request(
            ocr_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {ocr_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=60, context=_ssl_ctx) as resp:
            data = json.loads(resp.read())
        return data.get("result", "").strip()

    # openai mode (default)
    api_url = ocr_url.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": "ocr2.0",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": "请识别图片中的题目文字，完整输出，不要添加任何解释。"},
                ],
            }
        ],
    }).encode()
    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ocr_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=60, context=_ssl_ctx) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()


# ── 生成器工厂 ──────────────────────────────────────────────────────────────
def make_generator(model: str, output_dir: str) -> ExplanationGenerator:
    llm = LiteLLMWrapper(
        model_name=model,
        temperature=0.7,
        print_cost=True,
        verbose=False,
        use_langfuse=False,
    )
    return ExplanationGenerator(
        planner_model=llm,
        output_dir=output_dir,
        verbose=False,
        use_rag=False,
        use_context_learning=False,
        use_visual_fix_code=False,
        use_langfuse=False,
        max_scene_concurrency=3,
        use_oah=True,
    )


# ── 单题处理 ──────────────────────────────────────────────────────────────
async def process_one(image_path: Path, output_dir: str, model: str, skip_existing: bool = True) -> bool:
    stem = image_path.stem  # e.g. G7VH1T1
    file_prefix = re.sub(r'[^a-z0-9_]+', '_', stem.lower())
    scene_outline_path = Path(output_dir) / file_prefix / f"{file_prefix}_scene_outline.txt"

    if skip_existing and scene_outline_path.exists():
        # 检查所有 scene 是否都已渲染成功
        scene_dir = Path(output_dir) / file_prefix
        succ_files = list(scene_dir.glob("scene*/succ_rendered.txt"))
        if succ_files:
            outline_text = scene_outline_path.read_text()
            scene_count = len(re.findall(r'<SCENE_(\d+)>', outline_text))
            if len(succ_files) >= scene_count:
                print(f"  ⏩ {stem} 已完成，跳过")
                return True

    print(f"\n{'='*60}")
    print(f"📷 {stem}")
    print(f"{'='*60}")

    # 1. 加载图片
    try:
        image = Image.open(image_path)
    except Exception as e:
        print(f"  ❌ 无法打开图片: {e}")
        return False

    # 2. OCR
    print(f"  🔍 OCR 识别中...")
    try:
        text = ocr_image(image)
    except Exception as e:
        print(f"  ❌ OCR 失败: {e}")
        return False

    if not text:
        print(f"  ⚠️  OCR 结果为空，跳过")
        return False

    print(f"  ✅ OCR: {text[:100]}{'...' if len(text)>100 else ''}")

    # 3. 生成图示
    print(f"  🎨 生成图示中...")
    try:
        gen = make_generator(model, output_dir)
        await gen.generate_html_diagrams(
            topic=stem,
            description=text,
            max_retries=2,
            problem_image=image,
        )
    except Exception as e:
        print(f"  ❌ 生成失败: {e}")
        return False

    # 4. 验证结果
    scene_dir = Path(output_dir) / file_prefix
    succ_files = list(scene_dir.glob("scene*/succ_rendered.txt"))
    html_files = list(scene_dir.glob("scene*/code/*_v*.html"))
    print(f"  ✅ 完成: {len(succ_files)} scenes, {len(html_files)} HTML files")
    return True


# ── 主入口 ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="批量处理题目图片：OCR + 生成图示")
    parser.add_argument("--input-dir", default=str(ROOT / "data" / "Zipped_Items"))
    parser.add_argument("--output-dir", default=str(ROOT / "output" / "Zipped_Items"))
    parser.add_argument("--model", default=os.getenv("TEACHER_MODEL_DEFAULT", "Kimi-K25"))
    parser.add_argument("--start", type=int, default=0, help="起始索引 (含)")
    parser.add_argument("--end", type=int, default=-1, help="结束索引 (不含), -1 表示全部")
    parser.add_argument("--no-skip", action="store_true", help="不跳过已完成的题目")
    parser.add_argument("--concurrency", type=int, default=1, help="并发处理题目数 (默认1)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 收集图片（排序）
    images = sorted(
        [f for f in input_dir.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg")],
        key=lambda p: p.name,
    )

    if not images:
        print(f"未找到图片: {input_dir}")
        sys.exit(1)

    start = args.start
    end = len(images) if args.end < 0 else args.end
    batch = images[start:end]

    print(f"共 {len(images)} 张图片，处理 [{start}:{end}] = {len(batch)} 张")
    print(f"模型: {args.model}")
    print(f"输出目录: {output_dir}")

    success = 0
    failed = 0
    skipped = 0

    t0 = time.time()
    concurrency = args.concurrency

    async def run_all():
        nonlocal success, failed, skipped
        semaphore = asyncio.Semaphore(concurrency)

        async def limited_process(i, img_path):
            nonlocal success, failed, skipped
            idx = start + i
            async with semaphore:
                print(f"\n[{idx+1}/{len(images)}] 处理 {img_path.name}")
                result = await process_one(
                    img_path,
                    str(output_dir),
                    args.model,
                    skip_existing=not args.no_skip,
                )
                if result is True:
                    file_prefix = re.sub(r'[^a-z0-9_]+', '_', img_path.stem.lower())
                    outline = output_dir / file_prefix / f"{file_prefix}_scene_outline.txt"
                    if outline.exists():
                        succ = list((output_dir / file_prefix).glob("scene*/succ_rendered.txt"))
                        if succ:
                            success += 1
                        else:
                            skipped += 1
                    else:
                        skipped += 1
                else:
                    failed += 1

        await asyncio.gather(*(limited_process(i, p) for i, p in enumerate(batch)))

    asyncio.run(run_all())

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"完成！成功: {success}, 失败: {failed}, 跳过: {skipped}")
    print(f"耗时: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print(f"输出目录: {output_dir}")


if __name__ == "__main__":
    main()
