import os
import re
import json
from typing import Union, List, Dict, Optional
from PIL import Image

from visual_solver.mllm_tools.utils import _prepare_text_inputs
from visual_solver.task_generator import (
    get_prompt_code_generation,
    get_banned_reasonings,
)


class CodeGenerator:
    """A class for generating and managing HTML/CSS/JS educational diagram code."""

    def __init__(self, scene_model, helper_model, output_dir="output", print_response=False,
                 use_rag=False, use_context_learning=False, context_learning_path="data/context_learning",
                 chroma_db_path="rag/chroma_db", manim_docs_path="rag/manim_docs",
                 embedding_model="azure/text-embedding-3-large", use_visual_fix_code=False,
                 use_langfuse=True, session_id=None, use_oah=False, oah_api_url=None, oah_model_ref=None):
        self.scene_model = scene_model
        self.helper_model = helper_model
        self.output_dir = output_dir
        self.print_response = print_response
        self.use_visual_fix_code = use_visual_fix_code
        self.banned_reasonings = get_banned_reasonings()
        self.session_id = session_id
        self.use_oah = use_oah
        self.oah_api_url = oah_api_url
        self.oah_model_ref = oah_model_ref
        self._oah_usage = {}  # scene_trace_id -> usage dict

    async def _extract_code_with_retries(self, response_text: str, pattern: str,
                                          generation_name: str = None, trace_id: str = None,
                                          session_id: str = None, max_retries: int = 10) -> str:
        """Extract code from response text with retry logic."""
        retry_prompt = (
            "Please extract the HTML code in the correct format using the pattern: {pattern}. "
            "You MUST NOT include any other text or comments. "
            "You MUST return the exact same code as in the previous response, NO CONTENT EDITING is allowed.\n"
            "Previous response:\n{response_text}"
        )

        for attempt in range(max_retries):
            code_match = re.search(pattern, response_text, re.DOTALL)
            if code_match:
                return code_match.group(1)

            if attempt < max_retries - 1:
                print(f"Attempt {attempt + 1}: Failed to extract code pattern. Retrying...")
                response_text = await self.scene_model(
                    _prepare_text_inputs(retry_prompt.format(pattern=pattern, response_text=response_text)),
                    metadata={
                        "generation_name": f"{generation_name}_format_retry_{attempt + 1}",
                        "trace_id": trace_id,
                        "session_id": session_id
                    }
                )

        raise ValueError(f"Failed to extract code pattern after {max_retries} attempts. Pattern: {pattern}")

    async def _generate_html_code_via_oah(self,
                                           topic: str,
                                           description: str,
                                           scene_implementation: str,
                                           scene_number: int,
                                           problem_image: Union[Image.Image, None] = None,
                                           file_prefix: str = None,
                                           scene_trace_id: str = None) -> tuple:
        """Generate HTML code via OAH workspace agent (runs in thread to avoid event loop conflicts)."""
        import asyncio
        from visual_solver.oah_client import OAHClient

        spec = {
            "topic": topic,
            "description": description,
            "scene_number": scene_number,
            "scene_implementation": scene_implementation,
            "output_file": f"scene{scene_number}.html",
        }

        print(f"[OAH] === Starting OAH generation for scene {scene_number} ===")

        def _sync_call():
            client = OAHClient(api_url=self.oah_api_url, model_ref=self.oah_model_ref)
            return client.generate_scene_html(
                spec=spec,
                output_file=spec["output_file"],
                problem_image=problem_image,
                delete_workspace_after=True,
            )

        try:
            result = await asyncio.to_thread(_sync_call)
        except Exception as e:
            print(f"[OAH] !!! OAH generation FAILED for scene {scene_number}: {e}")
            raise

        html = result["html"]
        usage = result.get("usage", {})
        if usage and scene_trace_id:
            self._oah_usage[scene_trace_id] = {
                "input_tokens": usage.get("inputTokens", 0),
                "output_tokens": usage.get("outputTokens", 0),
                "total_tokens": usage.get("totalTokens", 0),
            }
            print(f"[OAH] Token usage for scene {scene_number}: {usage.get('totalTokens',0)} (in={usage.get('inputTokens',0)}, out={usage.get('outputTokens',0)})")

        print(f"[OAH] === OAH generation complete for scene {scene_number}: {len(html)} chars ===")
        return html, html

    async def generate_html_code(self,
                                 topic: str,
                                 description: str,
                                 scene_outline: str,
                                 scene_implementation: str,
                                 scene_number: int,
                                 additional_context: Union[str, List[str]] = None,
                                 scene_trace_id: str = None,
                                 session_id: str = None,
                                 problem_image: Union[Image.Image, None] = None,
                                 file_prefix: str = None) -> tuple:
        """Generate HTML/CSS/JS code for a scene.

        Returns:
            Tuple[str, str]: Generated code and response text
        """
        # ── OAH branch ─────────────────────────────────────────────────────
        if self.use_oah:
            print(f"[OAH] Generating HTML code for scene {scene_number} via OAH agent")
            return await self._generate_html_code_via_oah(
                topic=topic,
                description=description,
                scene_implementation=scene_implementation,
                scene_number=scene_number,
                problem_image=problem_image,
                file_prefix=file_prefix,
                scene_trace_id=scene_trace_id,
            )

        # ── LiteLLM fallback (original path) ───────────────────────────────
        prompt = get_prompt_code_generation(
            scene_outline=scene_outline,
            scene_implementation=scene_implementation,
            topic=topic,
            description=description,
            scene_number=scene_number,
            additional_context=additional_context
        )

        if problem_image and scene_number == 1:
            messages = [
                {"type": "text", "content": prompt},
                {"type": "image", "content": problem_image}
            ]
            print(f"Including problem diagram in code generation for scene {scene_number}")
        else:
            messages = _prepare_text_inputs(prompt)

        response_text = await self.scene_model(
            messages,
            metadata={
                "generation_name": "code_generation",
                "trace_id": scene_trace_id,
                "tags": [topic, f"scene{scene_number}"],
                "session_id": session_id
            }
        )

        # Extract HTML from <CODE>...</CODE> block, then from ```html...``` fences
        code = None
        code_block_match = re.search(r'<CODE>(.*?)</CODE>', response_text, re.DOTALL)
        if code_block_match:
            inner = code_block_match.group(1)
            html_match = re.search(r'```html(.*?)```', inner, re.DOTALL)
            if html_match:
                code = html_match.group(1).strip()
            else:
                code = inner.strip()
        else:
            # Fallback: extract from ```html...``` anywhere in response
            try:
                code = await self._extract_code_with_retries(
                    response_text,
                    r'```html(.*?)```',
                    generation_name="code_generation",
                    trace_id=scene_trace_id,
                    session_id=session_id
                )
                code = code.strip()
            except ValueError:
                pass

        if not code:
            raise ValueError("Failed to extract HTML code from model response")

        return code, response_text

    # Keep old name as alias for compatibility during migration
    async def generate_manim_code(self, *args, **kwargs):
        return await self.generate_html_code(*args, **kwargs)
