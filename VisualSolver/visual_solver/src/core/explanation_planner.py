import os
import re
import json
import glob
from typing import List, Optional, TYPE_CHECKING
import uuid
import asyncio
from PIL import Image

from visual_solver.mllm_tools.utils import _prepare_text_inputs
from visual_solver.src.utils.utils import extract_xml
from visual_solver.task_generator import (
    get_prompt_scene_plan,
    get_prompt_scene_vision_storyboard,
    get_prompt_scene_technical_implementation,
    get_prompt_scene_animation_narration,
    get_prompt_context_learning_scene_plan,
    get_prompt_context_learning_vision_storyboard,
    get_prompt_context_learning_technical_implementation,
    get_prompt_context_learning_animation_narration,
    get_prompt_context_learning_code,
    get_prompt_scene_design_and_implementation  # Add new import
)

if TYPE_CHECKING:
    from visual_solver.src.rag.rag_integration import RAGIntegration

class ExplanationPlanner:
    """A class for planning and generating explanation content.

    This class handles the planning and generation of explanation content including scene outlines,
    vision storyboards, technical implementations, and animation narrations.

    Args:
        planner_model: The model used for planning tasks
        helper_model: Optional helper model, defaults to planner_model if None
        output_dir (str): Directory for output files. Defaults to "output"
        print_response (bool): Whether to print model responses. Defaults to False
        use_context_learning (bool): Whether to use context learning. Defaults to False
        context_learning_path (str): Path to context learning examples. Defaults to "data/context_learning"
        use_rag (bool): Whether to use RAG. Defaults to False
        session_id (str): Session identifier. Defaults to None
        chroma_db_path (str): Path to ChromaDB. Defaults to "data/rag/chroma_db"
        manim_docs_path (str): Path to Manim docs. Defaults to "data/rag/manim_docs"
        embedding_model (str): Name of embedding model. Defaults to "text-embedding-ada-002"
        use_langfuse (bool): Whether to use Langfuse logging. Defaults to True
    """

    def __init__(self, planner_model, helper_model=None, output_dir="output", print_response=False, use_context_learning=False, context_learning_path="data/context_learning", use_rag=False, session_id=None, chroma_db_path="data/rag/chroma_db", manim_docs_path="data/rag/manim_docs", embedding_model="text-embedding-ada-002", use_langfuse=True, use_oah=False, oah_api_url=None, oah_model_ref=None, oah_token=None, trace_dir=None):
        self.planner_model = planner_model
        self.helper_model = helper_model if helper_model is not None else planner_model
        self.output_dir = output_dir
        self.print_response = print_response
        self.use_context_learning = use_context_learning
        self.use_oah = use_oah
        self.oah_api_url = oah_api_url
        self.oah_model_ref = oah_model_ref
        self.oah_token = oah_token
        self.trace_dir = trace_dir
        self._oah_usage = {}  # stage -> usage dict
        self.context_learning_path = context_learning_path
        # Initialize different types of context examples
        self.scene_plan_examples = self._load_context_examples('scene_plan') if use_context_learning else None
        self.vision_storyboard_examples = self._load_context_examples('scene_vision_storyboard') if use_context_learning else None
        self.technical_implementation_examples = self._load_context_examples('technical_implementation') if use_context_learning else None
        self.animation_narration_examples = self._load_context_examples('scene_animation_narration') if use_context_learning else None
        self.code_examples = self._load_context_examples('code') if use_context_learning else None
        self.use_rag = use_rag
        self.rag_integration = None
        if use_rag:
            from visual_solver.src.rag.rag_integration import RAGIntegration
            self.rag_integration = RAGIntegration(
                helper_model=helper_model,
                output_dir=output_dir,
                chroma_db_path=chroma_db_path,
                manim_docs_path=manim_docs_path,
                embedding_model=embedding_model,
                use_langfuse=use_langfuse,
                session_id=session_id
            )
        self.relevant_plugins = []  # Initialize as an empty list

    def _load_context_examples(self, example_type: str) -> str:
        """Load context learning examples of a specific type from files.

        Args:
            example_type (str): Type of examples to load ('scene_plan', 'scene_vision_storyboard', etc.)

        Returns:
            str: Formatted string containing the loaded examples, or None if no examples found
        """
        examples = []
        
        # Define file patterns for different types
        file_patterns = {
            'scene_plan': '*_scene_plan.txt',
            'scene_vision_storyboard': '*_scene_vision_storyboard.txt',
            'technical_implementation': '*_technical_implementation.txt',
            'scene_animation_narration': '*_scene_animation_narration.txt',
            'code': '*.py'
        }
        
        pattern = file_patterns.get(example_type)
        if not pattern:
            return None

        # Search in subdirectories of context_learning_path
        for root, _, _ in os.walk(self.context_learning_path):
            for example_file in glob.glob(os.path.join(root, pattern)):
                with open(example_file, 'r') as f:
                    content = f.read()
                    if example_type == 'code':
                        examples.append(f"# Example from {os.path.basename(example_file)}\n{content}\n")
                    else:
                        examples.append(f"# Example from {os.path.basename(example_file)}\n{content}\n")

        # Format examples using appropriate template
        if examples:
            formatted_examples = self._format_examples(example_type, examples)
            return formatted_examples
        return None

    async def _format_examples(self, example_type: str, examples: List[str]) -> str:
        """Format examples using the appropriate template based on their type.

        Args:
            example_type (str): Type of examples to format
            examples (List[str]): List of example strings to format

        Returns:
            str: Formatted examples string, or None if no template found
        """
        templates = {
            'scene_plan': get_prompt_context_learning_scene_plan,
            'scene_vision_storyboard': get_prompt_context_learning_vision_storyboard,
            'technical_implementation': get_prompt_context_learning_technical_implementation,
            'scene_animation_narration': get_prompt_context_learning_animation_narration,
            'code': get_prompt_context_learning_code
        }
        
        template = templates.get(example_type)
        if template:
            return template(examples="\n".join(examples))
        return None

    async def generate_scene_outline(self,
                            topic: str,
                            description: str,
                            session_id: str,
                            problem_image: Optional[Image.Image] = None,
                            trace_name: Optional[str] = None) -> str:
        """Generate a scene outline based on the topic and description.

        Args:
            topic (str): The topic of the explanation
            description (str): Description of the explanation content
            session_id (str): Session identifier
            problem_image: Optional problem diagram image

        Returns:
            str: Generated scene outline
        """
        # replace all spaces and special characters with underscores for file path compatibility
        file_prefix = topic.lower()
        file_prefix = re.sub(r'[^a-z0-9_]+', '_', file_prefix)

        # ── OAH branch ─────────────────────────────────────────────────────
        if self.use_oah:
            print(f"[OAH] Generating scene outline via OAH outline agent")
            scene_outline = await self._generate_outline_via_oah(
                topic=topic,
                description=description,
                problem_image=problem_image,
                trace_name=trace_name,
            )

            # Save plan to file
            os.makedirs(os.path.join(self.output_dir, file_prefix), exist_ok=True)
            with open(os.path.join(self.output_dir, file_prefix, f"{file_prefix}_scene_outline.txt"), "w") as f:
                f.write(scene_outline)
            print(f"✓ Scene Outline (OAH) saved to {file_prefix}_scene_outline.txt")

            # Save token usage from OAH
            token_file = os.path.join(self.output_dir, file_prefix, f"{file_prefix}_scene_outline_tokens.json")
            outline_usage = self._oah_usage.get("scene_outline", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
            with open(token_file, "w") as f:
                json.dump(outline_usage, f, indent=2)
            print(f"[OAH] Scene outline token usage saved to {token_file}")

            return scene_outline

        # ── LiteLLM fallback (original path) ───────────────────────────────

        # Detect relevant plugins upfront if RAG is enabled
        if self.use_rag:
            self.relevant_plugins = self.rag_integration.detect_relevant_plugins(topic, description) or []
            self.rag_integration.set_relevant_plugins(self.relevant_plugins)
            print(f"Detected relevant plugins: {self.relevant_plugins}")

        prompt = get_prompt_scene_plan(topic, description)

        if self.use_context_learning and self.scene_plan_examples:
            prompt += f"\n\nHere are some example scene plans for reference:\n{self.scene_plan_examples}"

        # Prepare input with image if available
        if problem_image:
            messages = [
                {"type": "text", "content": prompt},
                {"type": "image", "content": problem_image}
            ]
            print(f"Including problem diagram in scene outline generation")
        else:
            messages = _prepare_text_inputs(prompt)

        # Generate plan using planner model
        response_text = await self.planner_model(
            messages,
            metadata={"generation_name": "scene_outline", "trace_id": topic, "tags": [topic, "scene-outline"], "session_id": session_id}
        )

        # Read per-trace token usage (safe under concurrency)
        outline_tokens = dict(self.planner_model._trace_tokens.get(topic, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}))
        print(f"Scene outline generation token usage: {outline_tokens['total_tokens']} tokens (Input: {outline_tokens['input_tokens']}, Output: {outline_tokens['output_tokens']})")
        # extract scene outline <SCENE_OUTLINE> ... </SCENE_OUTLINE>
        scene_outline_match = re.search(r'(<SCENE_OUTLINE>.*?</SCENE_OUTLINE>)', response_text, re.DOTALL)
        scene_outline = scene_outline_match.group(1) if scene_outline_match else response_text

        # save plan to file
        os.makedirs(os.path.join(self.output_dir, file_prefix), exist_ok=True)
        with open(os.path.join(self.output_dir, file_prefix, f"{file_prefix}_scene_outline.txt"), "w") as f:
            f.write(scene_outline)
        print(f"Plan saved to {file_prefix}_scene_outline.txt")

        # Save scene outline token usage to file
        token_file = os.path.join(self.output_dir, file_prefix, f"{file_prefix}_scene_outline_tokens.json")
        with open(token_file, "w") as f:
            json.dump(outline_tokens, f, indent=2)
        print(f"Scene outline token usage saved to {token_file}")

        return scene_outline

    async def _generate_outline_via_oah(self,
                                         topic: str,
                                         description: str,
                                         problem_image: Optional[Image.Image] = None,
                                         trace_name: Optional[str] = None) -> str:
        """Generate scene outline via OAH workspace outline agent."""
        from visual_solver.oah_client import OAHClient

        spec = {
            "topic": topic,
            "description": description,
        }

        print(f"[OAH] === Starting OAH outline generation ===")

        def _sync_call():
            client = OAHClient(api_url=self.oah_api_url, model_ref=self.oah_model_ref, token=self.oah_token,
                               trace_dir=self.trace_dir, trace_name=trace_name)
            return client.generate_scene_outline(
                spec=spec,
                problem_image=problem_image,
            )

        try:
            result = await asyncio.to_thread(_sync_call)
        except Exception as e:
            print(f"[OAH] !!! OAH outline generation FAILED: {e}")
            raise

        outline = result["outline"]
        usage = result.get("usage", {})
        if usage:
            self._oah_usage["scene_outline"] = {
                "input_tokens": usage.get("inputTokens", 0),
                "output_tokens": usage.get("outputTokens", 0),
                "total_tokens": usage.get("totalTokens", 0),
            }
            print(f"[OAH] Outline token usage: {usage.get('totalTokens',0)} (in={usage.get('inputTokens',0)}, out={usage.get('outputTokens',0)})")

        # Extract from XML tags if present
        outline_match = re.search(r'(<SCENE_OUTLINE>.*?</SCENE_OUTLINE>)', outline, re.DOTALL)
        if outline_match:
            outline = outline_match.group(1)

        print(f"[OAH] === OAH outline generation complete: {len(outline)} chars ===")
        return outline

    async def _generate_scene_implementation_single(self, topic: str, description: str, scene_outline_i: str, i: int, file_prefix: str, session_id: str, scene_trace_id: str, problem_image: Optional[Image.Image] = None, trace_name: Optional[str] = None) -> str:
        """Generate implementation plan for a single scene using unified prompt.

        Args:
            topic (str): The topic of the explanation
            description (str): Description of the explanation content
            scene_outline_i (str): Outline for this specific scene
            i (int): Scene number
            file_prefix (str): Prefix for output files
            session_id (str): Session identifier
            scene_trace_id (str): Unique trace ID for this scene
            problem_image: Optional problem diagram image

        Returns:
            str: Generated implementation plan for the scene
        """
        scene_dir = os.path.join(self.output_dir, file_prefix, f"scene{i}")
        subplan_dir = os.path.join(scene_dir, "subplans")
        os.makedirs(scene_dir, exist_ok=True)
        os.makedirs(subplan_dir, exist_ok=True)

        # Save scene_trace_id to file
        trace_id_file = os.path.join(subplan_dir, "scene_trace_id.txt")
        with open(trace_id_file, 'w') as f:
            f.write(scene_trace_id)
        print(f"Scene trace ID saved to {trace_id_file}")

        # ===== Generate Scene Design and Implementation Plan (Unified) =====
        # ===================================================================

        # ── OAH branch ─────────────────────────────────────────────────────
        if self.use_oah:
            print(f"[OAH] Generating implementation plan for scene {i} via OAH planner agent")
            implementation_plan = await self._generate_implementation_via_oah(
                topic=topic,
                description=description,
                scene_outline_i=scene_outline_i,
                scene_number=i,
                problem_image=problem_image,
                trace_name=trace_name,
            )

            # Save the implementation plan (keep existing file naming)
            plan_file = os.path.join(scene_dir, f"{file_prefix}_scene{i}_implementation_plan.txt")
            with open(plan_file, "w") as f:
                f.write(f"# Scene {i} Implementation Plan\n\n")
                f.write(implementation_plan)
            print(f"✓ Scene {i} Implementation Plan (OAH) saved to {plan_file}")

            # Save token usage from OAH
            token_file = os.path.join(subplan_dir, f"scene{i}_implementation_tokens.json")
            impl_usage = self._oah_usage.get(f"scene_{i}_implementation", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
            with open(token_file, "w") as f:
                json.dump(impl_usage, f, indent=2)
            print(f"[OAH] Scene {i} implementation token usage saved to {token_file}")

            return implementation_plan

        # ── LiteLLM fallback (original path) ───────────────────────────────
        prompt = get_prompt_scene_design_and_implementation(
            scene_number=i,
            description=description,
            scene_outline=scene_outline_i
        )

        # Add context learning examples if available
        if self.use_context_learning:
            if self.vision_storyboard_examples:
                prompt += f"\n\n{self.vision_storyboard_examples}"
            if self.technical_implementation_examples:
                prompt += f"\n\n{self.technical_implementation_examples}"

        # Add RAG documentation if enabled
        if self.rag_integration:
            # Generate RAG queries for the unified plan
            rag_queries = self.rag_integration._generate_rag_queries_storyboard(
                scene_plan=scene_outline_i,
                scene_trace_id=scene_trace_id,
                topic=topic,
                scene_number=i,
                session_id=session_id,
                relevant_plugins=self.relevant_plugins
            )

            retrieved_docs = self.rag_integration.get_relevant_docs(
                rag_queries=rag_queries,
                scene_trace_id=scene_trace_id,
                topic=topic,
                scene_number=i
            )

            prompt += f"\n\n{retrieved_docs}"

        # Prepare input with image if available
        if problem_image:
            messages = [
                {"type": "text", "content": prompt},
                {"type": "image", "content": problem_image}
            ]
            print(f"Including problem diagram in scene {i} design and implementation generation")
        else:
            messages = _prepare_text_inputs(prompt)

        # Generate unified design and implementation plan
        implementation_plan = await self.planner_model(
            messages,
            metadata={"generation_name": "scene_design_and_implementation", "trace_id": scene_trace_id, "tags": [topic, f"scene{i}"], "session_id": session_id}
        )

        # Read per-trace token usage (safe under concurrency)
        implementation_tokens = dict(self.planner_model._trace_tokens.get(scene_trace_id, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}))
        print(f"Scene {i} implementation plan token usage: {implementation_tokens['total_tokens']} tokens (Input: {implementation_tokens['input_tokens']}, Output: {implementation_tokens['output_tokens']})")

        # Extract the plan from XML tags (aligned with prompt output format)
        plan_match = re.search(r'(<SCENE_VISION_STORYBOARD_AND_TECHNICAL_PLAN>.*?</SCENE_VISION_STORYBOARD_AND_TECHNICAL_PLAN>)', implementation_plan, re.DOTALL)
        implementation_plan = plan_match.group(1) if plan_match else implementation_plan

        # Save the implementation plan
        plan_file = os.path.join(scene_dir, f"{file_prefix}_scene{i}_implementation_plan.txt")
        with open(plan_file, "w") as f:
            f.write(f"# Scene {i} Implementation Plan\n\n")
            f.write(implementation_plan)
        print(f"✓ Scene {i} Implementation Plan saved to {plan_file}")

        # Save implementation plan token usage to file
        token_file = os.path.join(subplan_dir, f"scene{i}_implementation_tokens.json")
        with open(token_file, "w") as f:
            json.dump(implementation_tokens, f, indent=2)
        print(f"Scene {i} implementation token usage saved to {token_file}")

        return implementation_plan

    async def _generate_implementation_via_oah(self,
                                                topic: str,
                                                description: str,
                                                scene_outline_i: str,
                                                scene_number: int,
                                                problem_image: Optional[Image.Image] = None,
                                                trace_name: Optional[str] = None) -> str:
        """Generate implementation plan via OAH workspace planner agent."""
        from visual_solver.oah_client import OAHClient

        spec = {
            "topic": topic,
            "description": description,
            "scene_number": scene_number,
            "scene_outline": scene_outline_i,
        }

        print(f"[OAH] === Starting OAH planning for scene {scene_number} ===")

        def _sync_call():
            client = OAHClient(api_url=self.oah_api_url, model_ref=self.oah_model_ref, token=self.oah_token,
                               trace_dir=self.trace_dir, trace_name=trace_name)
            return client.generate_implementation_plan(
                spec=spec,
                problem_image=problem_image,
            )

        try:
            result = await asyncio.to_thread(_sync_call)
        except Exception as e:
            print(f"[OAH] !!! OAH planning FAILED for scene {scene_number}: {e}")
            raise

        plan = result["plan"]
        usage = result.get("usage", {})
        if usage:
            self._oah_usage[f"scene_{scene_number}_implementation"] = {
                "input_tokens": usage.get("inputTokens", 0),
                "output_tokens": usage.get("outputTokens", 0),
                "total_tokens": usage.get("totalTokens", 0),
            }
            print(f"[OAH] Planning token usage for scene {scene_number}: {usage.get('totalTokens',0)} (in={usage.get('inputTokens',0)}, out={usage.get('outputTokens',0)})")

        # Extract from XML tags if present
        plan_match = re.search(r'(<SCENE_VISION_STORYBOARD_AND_TECHNICAL_PLAN>.*?</SCENE_VISION_STORYBOARD_AND_TECHNICAL_PLAN>)', plan, re.DOTALL)
        if plan_match:
            plan = plan_match.group(1)

        print(f"[OAH] === OAH planning complete for scene {scene_number}: {len(plan)} chars ===")
        return plan

    async def generate_scene_implementation(self,
                                      topic: str,
                                      description: str,
                                      plan: str,
                                      session_id: str) -> List[str]:
        """Generate detailed implementation plans for all scenes.

        Args:
            topic (str): The topic of the explanation
            description (str): Description of the explanation content
            plan (str): Overall scene plan
            session_id (str): Session identifier

        Returns:
            List[str]: List of implementation plans for each scene
        """
        # extract scene outline <SCENE_OUTLINE> ... </SCENE_OUTLINE>
        scene_outline = re.search(r'(<SCENE_OUTLINE>.*?</SCENE_OUTLINE>)', plan, re.DOTALL).group(1)
        # check the number of scenes in the outline
        scene_number = len(re.findall(r'<SCENE_(\d+)>[^<]', scene_outline))
        # replace all spaces and special characters with underscores for file path compatibility
        file_prefix = topic.lower()
        file_prefix = re.sub(r'[^a-z0-9_]+', '_', file_prefix)
        # generate implementation plan for each scene
        all_scene_implementation_plans = []

        tasks = []
        for i in range(1, scene_number):
            print(f"Generating implementation plan for scene {i} in topic {topic}")
            scene_outline_i = re.search(r'(<SCENE_{i}>.*?</SCENE_{i}>)'.format(i=i), scene_outline, re.DOTALL).group(1)
            scene_trace_id = str(uuid.uuid4())
            task = asyncio.create_task(self._generate_scene_implementation_single(topic, description, scene_outline_i, i, file_prefix, session_id, scene_trace_id))
            tasks.append(task)

        all_scene_implementation_plans = await asyncio.gather(*tasks)
        return all_scene_implementation_plans

    async def generate_scene_implementation_concurrently(self,
                                              topic: str,
                                              description: str,
                                              plan: str,
                                              session_id: str,
                                              scene_semaphore,
                                              trace_prefix: Optional[str] = None) -> List[str]:
        """Generate detailed implementation plans for all scenes concurrently with controlled concurrency.

        Args:
            topic (str): The topic of the explanation
            description (str): Description of the explanation content
            plan (str): Overall scene plan
            session_id (str): Session identifier
            scene_semaphore: Semaphore to control concurrent scene generation

        Returns:
            List[str]: List of implementation plans for each scene
        """
        scene_outline = extract_xml(plan)
        scene_number = len(re.findall(r'<SCENE_(\d+)>[^<]', scene_outline))
        file_prefix = re.sub(r'[^a-z0-9_]+', '_', topic.lower())
        all_scene_implementation_plans = []

        async def generate_single_scene_implementation(i):
            async with scene_semaphore:  # controls parallelism
                print(f"Generating implementation plan for scene {i} in topic {topic}")
                scene_outline_i = re.search(r'(<SCENE_{i}>.*?</SCENE_{i}>)'.format(i=i), scene_outline, re.DOTALL).group(1)
                scene_trace_id = str(uuid.uuid4())  # Generate UUID here
                stage_name = f"scene{i}_plan" if trace_prefix else None
                tn = f"{trace_prefix}_{stage_name}" if trace_prefix and stage_name else None
                return await self._generate_scene_implementation_single(topic, description, scene_outline_i, i, file_prefix, session_id, scene_trace_id, trace_name=tn)

        tasks = [generate_single_scene_implementation(i + 1) for i in range(scene_number)]
        all_scene_implementation_plans = await asyncio.gather(*tasks)
        return all_scene_implementation_plans 