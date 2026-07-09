import os
import re
import json
import asyncio
import base64
import tempfile
from typing import List, Dict, Union, Optional
from pathlib import Path

from visual_solver.mllm_tools.litellm import LiteLLMWrapper
from visual_solver.mllm_tools.gemini import GeminiWrapper
from visual_solver.mllm_tools.utils import _prepare_text_inputs, _prepare_text_image_inputs
from eval_suite.utils import extract_json, convert_score_fields, calculate_geometric_mean


def base64_to_temp_image(base64_str: str) -> Optional[str]:
    """
    Convert base64 encoded image string to a temporary image file.

    Args:
        base64_str: Base64 encoded image string (JPEG format)

    Returns:
        str: Path to temporary image file or None if conversion fails
    """
    if not base64_str:
        return None

    try:
        # Decode base64 string
        image_data = base64.b64decode(base64_str)

        # Create a temporary file
        fd, temp_path = tempfile.mkstemp(suffix='.jpg')

        # Write image data
        with os.fdopen(fd, 'wb') as f:
            f.write(image_data)

        return temp_path
    except Exception as e:
        print(f"Warning: Failed to convert base64 image: {e}")
        return None


def parse_markdown_with_images(md_path: str) -> tuple[str, List[str]]:
    """
    Parse a markdown file and extract text content and image paths.

    Args:
        md_path: Path to the markdown file.

    Returns:
        tuple: (text_content, list of image paths)
    """
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract image paths
    # Matches both ![alt](image.png) and ![](image.png)
    image_pattern = r'!\[.*?\]\((.*?)\)'
    image_refs = re.findall(image_pattern, content)

    # Convert relative paths to absolute paths
    md_dir = os.path.dirname(os.path.abspath(md_path))
    image_paths = []
    for img_ref in image_refs:
        # Handle absolute and relative paths
        if not os.path.isabs(img_ref):
            img_path = os.path.join(md_dir, img_ref)
        else:
            img_path = img_ref

        if os.path.exists(img_path):
            image_paths.append(img_path)
        else:
            print(f"Warning: Image not found: {img_path}")

    return content, image_paths


def load_rubric(rubric_path: str) -> Dict:
    """
    Load the evaluation rubric from a JSON file.

    Args:
        rubric_path: Path to the rubric JSON file.

    Returns:
        dict: The rubric dictionary.
    """
    with open(rubric_path, 'r', encoding='utf-8') as f:
        rubric = json.load(f)
    return rubric


def build_evaluation_prompt(dimension_name: str, dimension_data: Dict, content: str, problem_data: Optional[Dict] = None) -> str:
    """
    Build an evaluation prompt for a specific dimension.

    Args:
        dimension_name: Name of the dimension (e.g., "correctness_and_completeness")
        dimension_data: Dictionary containing dimension metadata and scoring criteria
        content: The content to evaluate (markdown text)
        problem_data: Optional original problem data with img_caption and format_answer

    Returns:
        str: The formatted evaluation prompt
    """
    prompt = f"""你是一名专业的K-12教育评估专家。请根据以下评分标准，对提供的解题文档进行评估。

评估维度：{dimension_data['name']}
维度描述：{dimension_data['description']}

评分标准：
"""

    # Add scoring criteria
    for score_key in sorted(dimension_data['scoring'].keys(), key=lambda x: int(x), reverse=True):
        score_data = dimension_data['scoring'][score_key]
        prompt += f"""
【{score_data['score']}分】
描述：{score_data['description']}
典型缺陷：{score_data['typical_defects']}
对学生的影响：{score_data['impact_on_students']}
"""

    # Add reference information if available
    if problem_data:
        prompt += "\n\n## 原题参考信息\n\n"

        # Add img_caption if available (for diagram_match dimension)
        if 'img_caption' in problem_data and problem_data['img_caption']:
            prompt += f"**原题示意图描述**：{problem_data['img_caption']}\n\n"

        # Add format_answer if available (for correctness_and_completeness dimension)
        if 'format_answer' in problem_data and problem_data['format_answer']:
            format_answer = problem_data['format_answer']
            if isinstance(format_answer, dict):
                if 'format_solution' in format_answer:
                    prompt += "**标准解题步骤**：\n"
                    for step in format_answer['format_solution']:
                        prompt += f"- {step}\n"
                    prompt += "\n"
                if 'ground_truth' in format_answer:
                    prompt += f"**标准答案**：{', '.join(str(x) for x in format_answer['ground_truth'])}\n\n"

    prompt += f"""
请仔细阅读以下文档内容，并根据上述评分标准进行评估：

{content}

请以JSON格式返回评估结果，格式如下：
{{
    "dimension": "{dimension_name}",
    "score": <0-5之间的整数分数>,
    "justification": "<详细的评分理由，说明为什么给出这个分数>",
    "identified_issues": ["<识别出的问题1>", "<识别出的问题2>", ...]
}}
"""

    return prompt


def evaluate_dimension_text_only(
    model: Union[LiteLLMWrapper, GeminiWrapper],
    dimension_name: str,
    dimension_data: Dict,
    text_content: str,
    retry_limit: int = 3,
    problem_data: Optional[Dict] = None
) -> Dict:
    """
    Evaluate a dimension using text-only content.

    Args:
        model: The LLM model to use for evaluation
        dimension_name: Name of the dimension
        dimension_data: Dimension metadata and scoring criteria
        text_content: The markdown text content
        retry_limit: Number of retry attempts
        problem_data: Optional original problem data

    Returns:
        dict: Evaluation result with score and justification
    """
    prompt = build_evaluation_prompt(dimension_name, dimension_data, text_content, problem_data)

    for attempt in range(retry_limit):
        try:
            response_coro = model(_prepare_text_inputs(prompt))
            # Handle async call - check if we're in an event loop
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context, can't use asyncio.run()
                # Create a new thread to run the coroutine
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, response_coro)
                    response = future.result()
            except RuntimeError:
                # No event loop running, safe to use asyncio.run()
                response = asyncio.run(response_coro)

            result = extract_json(response)
            result = convert_score_fields(result)
            return result
        except Exception as e:
            print(f"Attempt {attempt + 1} failed for dimension {dimension_name}: {e.__class__.__name__}: {e}")
            if attempt + 1 == retry_limit:
                print(f"Warning: Failed to evaluate dimension {dimension_name} after {retry_limit} attempts")
                return {
                    "dimension": dimension_name,
                    "score": 0,
                    "justification": f"Evaluation failed: {str(e)}",
                    "identified_issues": ["Evaluation error"]
                }


def evaluate_single_scene_with_original(
    model: Union[LiteLLMWrapper, GeminiWrapper],
    dimension_name: str,
    dimension_data: Dict,
    text_content: str,
    scene_path: str,
    scene_index: int,
    original_image_path: Optional[str],
    retry_limit: int = 3,
    problem_data: Optional[Dict] = None
) -> Dict:
    """
    Evaluate a single scene image against the original problem image.

    Args:
        model: The LLM model to use for evaluation
        dimension_name: Name of the dimension
        dimension_data: Dimension metadata and scoring criteria
        text_content: The markdown text content
        scene_path: Path to the scene image
        scene_index: Index of the scene (1-based)
        original_image_path: Path to original problem image
        retry_limit: Number of retry attempts
        problem_data: Optional original problem data

    Returns:
        dict: Evaluation result with score and justification
    """
    # Build prompt with scene-specific instructions
    base_prompt = build_evaluation_prompt(dimension_name, dimension_data, text_content, problem_data)

    # Add scene-specific instructions
    scene_instruction = f"""

## 当前评估的图片

**正在评估：Scene {scene_index}**

图片说明：
- 第1张图片：生成的Scene {scene_index}（待评估）
- 第2张图片：原题示意图

请仔细对比这两张图片，评估生成的Scene {scene_index}与原题示意图的匹配程度。
"""

    prompt = base_prompt + scene_instruction

    for attempt in range(retry_limit):
        try:
            # Prepare images: [original_image, scene_image]
            images_to_evaluate = []
            images_to_evaluate.append(scene_path)
            if original_image_path:
                images_to_evaluate.append(original_image_path)

            if images_to_evaluate:
                inputs = _prepare_text_image_inputs(prompt, images_to_evaluate)
            else:
                inputs = _prepare_text_inputs(prompt)

            response_coro = model(inputs)
            # Handle async call
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, response_coro)
                    response = future.result()
            except RuntimeError:
                response = asyncio.run(response_coro)

            result = extract_json(response)
            result = convert_score_fields(result)
            return result
        except Exception as e:
            print(f"Attempt {attempt + 1} failed for scene {scene_index}: {e.__class__.__name__}: {e}")
            if attempt + 1 == retry_limit:
                print(f"Warning: Failed to evaluate scene {scene_index} after {retry_limit} attempts")
                return {
                    "dimension": dimension_name,
                    "score": 0,
                    "justification": f"Evaluation failed: {str(e)}",
                    "identified_issues": ["Evaluation error"]
                }


def evaluate_single_diagram(
    model: Union[LiteLLMWrapper, GeminiWrapper],
    dimension_name: str,
    dimension_data: Dict,
    image_path: str,
    image_index: int,
    retry_limit: int = 3,
    problem_data: Optional[Dict] = None
) -> Dict:
    """
    Evaluate a single diagram image independently (for type='diagram').

    Args:
        model: The LLM model to use for evaluation
        dimension_name: Name of the dimension
        dimension_data: Dimension metadata and scoring criteria
        image_path: Path to the image
        image_index: Index of the image (1-based)
        retry_limit: Number of retry attempts
        problem_data: Optional original problem data

    Returns:
        dict: Evaluation result with score and justification
    """
    # Build prompt without text content
    prompt = f"""你是一名专业的K-12教育评估专家。请根据以下评分标准，对提供的图片进行评估。

评估维度：{dimension_data['name']}
维度描述：{dimension_data['description']}

评分标准：
"""

    # Add scoring criteria
    for score_key in sorted(dimension_data['scoring'].keys(), key=lambda x: int(x), reverse=True):
        score_data = dimension_data['scoring'][score_key]
        prompt += f"""
【{score_data['score']}分】
描述：{score_data['description']}
典型缺陷：{score_data['typical_defects']}
对学生的影响：{score_data['impact_on_students']}
"""

    prompt += f"""

请仔细分析提供的图片，并根据上述评分标准进行评估。

请以JSON格式返回评估结果，格式如下：
{{
    "dimension": "{dimension_name}",
    "score": <0-5之间的整数分数>,
    "justification": "<详细的评分理由，说明为什么给出这个分数>",
    "identified_issues": ["<识别出的问题1>", "<识别出的问题2>", ...]
}}
"""

    for attempt in range(retry_limit):
        try:
            inputs = _prepare_text_image_inputs(prompt, [image_path])
            response_coro = model(inputs)

            # Handle async call
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, response_coro)
                    response = future.result()
            except RuntimeError:
                response = asyncio.run(response_coro)

            result = extract_json(response)
            result = convert_score_fields(result)
            return result
        except Exception as e:
            print(f"Attempt {attempt + 1} failed for image {image_index}: {e.__class__.__name__}: {e}")
            if attempt + 1 == retry_limit:
                print(f"Warning: Failed to evaluate image {image_index} after {retry_limit} attempts")
                return {
                    "dimension": dimension_name,
                    "score": 0,
                    "justification": f"Evaluation failed: {str(e)}",
                    "identified_issues": ["Evaluation error"]
                }


def evaluate_diagram_vs_reference(
    model: Union[LiteLLMWrapper, GeminiWrapper],
    dimension_name: str,
    dimension_data: Dict,
    image_path: str,
    reference_image_path: str,
    image_index: int,
    retry_limit: int = 3,
    problem_data: Optional[Dict] = None
) -> Dict:
    """
    Evaluate a diagram image against a reference image (for type='diagram_aa').

    Args:
        model: The LLM model to use for evaluation
        dimension_name: Name of the dimension
        dimension_data: Dimension metadata and scoring criteria
        image_path: Path to the image to evaluate
        reference_image_path: Path to the reference image (first image)
        image_index: Index of the image (1-based)
        retry_limit: Number of retry attempts
        problem_data: Optional original problem data

    Returns:
        dict: Evaluation result with score and justification
    """
    # Build prompt without text content
    prompt = f"""你是一名专业的K-12教育评估专家。请根据以下评分标准，评估两张图片的一致性。

评估维度：{dimension_data['name']}
维度描述：{dimension_data['description']}

评分标准：
"""

    # Add scoring criteria
    for score_key in sorted(dimension_data['scoring'].keys(), key=lambda x: int(x), reverse=True):
        score_data = dimension_data['scoring'][score_key]
        prompt += f"""
【{score_data['score']}分】
描述：{score_data['description']}
典型缺陷：{score_data['typical_defects']}
对学生的影响：{score_data['impact_on_students']}
"""

    prompt += f"""

## 当前评估的图片

图片说明：
- 第1张图片：参考图片（第一张图片，作为视觉风格的基准）
- 第2张图片：待评估图片（图片 {image_index}）

请仔细对比这两张图片的视觉风格一致性，包括绘图风格、配色方案、符号系统和排版规范等方面。

请以JSON格式返回评估结果，格式如下：
{{
    "dimension": "{dimension_name}",
    "score": <0-5之间的整数分数>,
    "justification": "<详细的评分理由，说明为什么给出这个分数>",
    "identified_issues": ["<识别出的问题1>", "<识别出的问题2>", ...]
}}
"""

    for attempt in range(retry_limit):
        try:
            # First image is reference, second is the one being evaluated
            inputs = _prepare_text_image_inputs(prompt, [reference_image_path, image_path])
            response_coro = model(inputs)

            # Handle async call
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, response_coro)
                    response = future.result()
            except RuntimeError:
                response = asyncio.run(response_coro)

            result = extract_json(response)
            result = convert_score_fields(result)
            return result
        except Exception as e:
            print(f"Attempt {attempt + 1} failed for image {image_index}: {e.__class__.__name__}: {e}")
            if attempt + 1 == retry_limit:
                print(f"Warning: Failed to evaluate image {image_index} after {retry_limit} attempts")
                return {
                    "dimension": dimension_name,
                    "score": 0,
                    "justification": f"Evaluation failed: {str(e)}",
                    "identified_issues": ["Evaluation error"]
                }


def evaluate_dimension_diagram_only(
    model: Union[LiteLLMWrapper, GeminiWrapper],
    dimension_name: str,
    dimension_data: Dict,
    image_paths: List[str],
    retry_limit: int = 3,
    problem_data: Optional[Dict] = None
) -> Dict:
    """
    Evaluate a dimension using only images (type='diagram').
    Each image is evaluated independently, and scores are combined using geometric mean.

    Args:
        model: The LLM model to use for evaluation (must support vision)
        dimension_name: Name of the dimension
        dimension_data: Dimension metadata and scoring criteria
        image_paths: List of paths to images from the solution document
        retry_limit: Number of retry attempts
        problem_data: Optional original problem data

    Returns:
        dict: Evaluation result with score and justification
    """
    if not image_paths:
        print(f"No images found for dimension {dimension_name}")
        return {
            "dimension": dimension_name,
            "score": 0,
            "justification": "No images available for evaluation",
            "identified_issues": ["No images found"]
        }

    # Evaluate each image independently
    image_results = []
    image_scores = []

    MAX_IMAGE_RETRIES = 2  # Maximum retries for image-level score 0

    for idx, image_path in enumerate(image_paths, 1):
        print(f"  Evaluating Image {idx}/{len(image_paths)}: {os.path.basename(image_path)}")

        image_result = evaluate_single_diagram(
            model, dimension_name, dimension_data, image_path, idx, retry_limit, problem_data
        )

        # Retry if image scored 0
        retry_count = 0
        image_score = image_result.get('score', 0)

        while image_score == 0 and retry_count < MAX_IMAGE_RETRIES:
            retry_count += 1
            print(f"    ⚠ Image {idx} scored 0, retrying ({retry_count}/{MAX_IMAGE_RETRIES})...")

            image_result = evaluate_single_diagram(
                model, dimension_name, dimension_data, image_path, idx, retry_limit, problem_data
            )

            image_score = image_result.get('score', 0)

            if image_score > 0:
                print(f"    ✓ Retry successful! New score: {image_score}")
            else:
                print(f"    ✗ Retry {retry_count} still scored 0")

        image_results.append({
            "image_index": idx,
            "image_path": image_path,
            "result": image_result
        })

        image_scores.append(image_score)

    # Calculate geometric mean of all image scores
    if image_scores:
        final_score = calculate_geometric_mean(image_scores)
    else:
        final_score = 0

    # Aggregate justifications and issues
    all_justifications = []
    all_issues = []

    for img_res in image_results:
        img_idx = img_res["image_index"]
        result = img_res["result"]
        all_justifications.append(f"Image {img_idx} (得分: {result.get('score', 0)}): {result.get('justification', '')}")
        all_issues.extend([f"Image {img_idx}: {issue}" for issue in result.get('identified_issues', [])])

    # Return aggregated result
    return {
        "dimension": dimension_name,
        "score": final_score,
        "justification": "\n\n".join(all_justifications),
        "identified_issues": all_issues,
        "image_details": image_results,
        "image_scores": image_scores
    }


def evaluate_dimension_diagram_consistency(
    model: Union[LiteLLMWrapper, GeminiWrapper],
    dimension_name: str,
    dimension_data: Dict,
    image_paths: List[str],
    retry_limit: int = 3,
    problem_data: Optional[Dict] = None
) -> Dict:
    """
    Evaluate a dimension by comparing all images against the first image (type='diagram_aa').
    Each image is compared to the first image for consistency, and scores are combined using geometric mean.

    Args:
        model: The LLM model to use for evaluation (must support vision)
        dimension_name: Name of the dimension
        dimension_data: Dimension metadata and scoring criteria
        image_paths: List of paths to images from the solution document
        retry_limit: Number of retry attempts
        problem_data: Optional original problem data

    Returns:
        dict: Evaluation result with score and justification
    """
    if not image_paths:
        print(f"No images found for dimension {dimension_name}")
        return {
            "dimension": dimension_name,
            "score": 0,
            "justification": "No images available for evaluation",
            "identified_issues": ["No images found"]
        }

    if len(image_paths) == 1:
        # Only one image, perfect consistency by definition
        print(f"  Only one image found, assigning perfect consistency score")
        return {
            "dimension": dimension_name,
            "score": 5,
            "justification": "只有一张图片，不存在视觉一致性问题",
            "identified_issues": [],
            "image_details": [{
                "image_index": 1,
                "image_path": image_paths[0],
                "result": {
                    "dimension": dimension_name,
                    "score": 5,
                    "justification": "单张图片，无需对比",
                    "identified_issues": []
                }
            }],
            "image_scores": [5]
        }

    # First image is the reference
    reference_image_path = image_paths[0]
    print(f"  Using Image 1 as reference: {os.path.basename(reference_image_path)}")

    # Evaluate each subsequent image against the reference
    image_results = []
    image_scores = []

    MAX_IMAGE_RETRIES = 2  # Maximum retries for image-level score 0

    # Add perfect score for the reference image itself
    image_results.append({
        "image_index": 1,
        "image_path": reference_image_path,
        "result": {
            "dimension": dimension_name,
            "score": 5,
            "justification": "参考图片（基准）",
            "identified_issues": []
        }
    })
    image_scores.append(5)

    for idx, image_path in enumerate(image_paths[1:], 2):
        print(f"  Evaluating Image {idx}/{len(image_paths)} vs Reference: {os.path.basename(image_path)}")

        image_result = evaluate_diagram_vs_reference(
            model, dimension_name, dimension_data, image_path, reference_image_path, idx, retry_limit, problem_data
        )

        # Retry if image scored 0
        retry_count = 0
        image_score = image_result.get('score', 0)

        while image_score == 0 and retry_count < MAX_IMAGE_RETRIES:
            retry_count += 1
            print(f"    ⚠ Image {idx} scored 0, retrying ({retry_count}/{MAX_IMAGE_RETRIES})...")

            image_result = evaluate_diagram_vs_reference(
                model, dimension_name, dimension_data, image_path, reference_image_path, idx, retry_limit, problem_data
            )

            image_score = image_result.get('score', 0)

            if image_score > 0:
                print(f"    ✓ Retry successful! New score: {image_score}")
            else:
                print(f"    ✗ Retry {retry_count} still scored 0")

        image_results.append({
            "image_index": idx,
            "image_path": image_path,
            "result": image_result
        })

        image_scores.append(image_score)

    # Calculate geometric mean of all image scores
    if image_scores:
        final_score = calculate_geometric_mean(image_scores)
    else:
        final_score = 0

    # Aggregate justifications and issues
    all_justifications = []
    all_issues = []

    for img_res in image_results:
        img_idx = img_res["image_index"]
        result = img_res["result"]
        all_justifications.append(f"Image {img_idx} (得分: {result.get('score', 0)}): {result.get('justification', '')}")
        all_issues.extend([f"Image {img_idx}: {issue}" for issue in result.get('identified_issues', [])])

    # Return aggregated result
    return {
        "dimension": dimension_name,
        "score": final_score,
        "justification": "\n\n".join(all_justifications),
        "identified_issues": all_issues,
        "image_details": image_results,
        "image_scores": image_scores
    }


def evaluate_dimension_with_images(
    model: Union[LiteLLMWrapper, GeminiWrapper],
    dimension_name: str,
    dimension_data: Dict,
    text_content: str,
    image_paths: List[str],
    retry_limit: int = 3,
    problem_data: Optional[Dict] = None,
    original_image_path: Optional[str] = None
) -> Dict:
    """
    Evaluate a dimension using both text and images.
    Each scene is evaluated separately against the original image,
    and scores are combined using geometric mean.

    Args:
        model: The LLM model to use for evaluation (must support vision)
        dimension_name: Name of the dimension
        dimension_data: Dimension metadata and scoring criteria
        text_content: The markdown text content
        image_paths: List of paths to images from the solution document
        retry_limit: Number of retry attempts
        problem_data: Optional original problem data
        original_image_path: Optional path to original problem image

    Returns:
        dict: Evaluation result with score and justification
    """
    if not image_paths:
        # No images to evaluate, fallback to text-only
        print(f"No images found for dimension {dimension_name}, using text-only evaluation")
        return evaluate_dimension_text_only(model, dimension_name, dimension_data, text_content, retry_limit, problem_data)

    # Evaluate each scene separately
    scene_results = []
    scene_scores = []

    MAX_SCENE_RETRIES = 2  # Maximum retries for scene-level score 0

    for idx, scene_path in enumerate(image_paths, 1):
        print(f"  Evaluating Scene {idx}/{len(image_paths)}: {os.path.basename(scene_path)}")

        scene_result = evaluate_single_scene_with_original(
            model, dimension_name, dimension_data, text_content,
            scene_path, idx, original_image_path, retry_limit, problem_data
        )

        # Retry if scene scored 0
        retry_count = 0
        scene_score = scene_result.get('score', 0)

        while scene_score == 0 and retry_count < MAX_SCENE_RETRIES:
            retry_count += 1
            print(f"    ⚠ Scene {idx} scored 0, retrying ({retry_count}/{MAX_SCENE_RETRIES})...")

            scene_result = evaluate_single_scene_with_original(
                model, dimension_name, dimension_data, text_content,
                scene_path, idx, original_image_path, retry_limit, problem_data
            )

            scene_score = scene_result.get('score', 0)

            if scene_score > 0:
                print(f"    ✓ Retry successful! New score: {scene_score}")
            else:
                print(f"    ✗ Retry {retry_count} still scored 0")

        scene_results.append({
            "scene_index": idx,
            "scene_path": scene_path,
            "result": scene_result
        })

        scene_scores.append(scene_score)

    # Calculate geometric mean of all scene scores
    if scene_scores:
        final_score = calculate_geometric_mean(scene_scores)
    else:
        final_score = 0

    # Aggregate justifications and issues
    all_justifications = []
    all_issues = []

    for scene_res in scene_results:
        scene_idx = scene_res["scene_index"]
        result = scene_res["result"]
        all_justifications.append(f"Scene {scene_idx} (得分: {result.get('score', 0)}): {result.get('justification', '')}")
        all_issues.extend([f"Scene {scene_idx}: {issue}" for issue in result.get('identified_issues', [])])

    # Return aggregated result
    return {
        "dimension": dimension_name,
        "score": final_score,
        "justification": "\n\n".join(all_justifications),
        "identified_issues": all_issues,
        "scene_details": scene_results,
        "scene_scores": scene_scores
    }


def evaluate_single_scene_without_original(
    model: Union[LiteLLMWrapper, GeminiWrapper],
    dimension_name: str,
    dimension_data: Dict,
    text_content: str,
    scene_path: str,
    scene_index: int,
    retry_limit: int = 3
) -> Dict:
    """
    Evaluate a single scene image with text content but without original problem image.
    Used for type='text_diagram_aa'.

    Args:
        model: The LLM model to use for evaluation
        dimension_name: Name of the dimension
        dimension_data: Dimension metadata and scoring criteria
        text_content: The markdown text content
        scene_path: Path to the scene image
        scene_index: Index of the scene (1-based)
        retry_limit: Number of retry attempts

    Returns:
        dict: Evaluation result with score and justification
    """
    # Build prompt without problem_data (no reference info)
    prompt = f"""你是一名专业的K-12教育评估专家。请根据以下评分标准，对提供的解题文档进行评估。

评估维度：{dimension_data['name']}
维度描述：{dimension_data['description']}

评分标准：
"""

    # Add scoring criteria
    for score_key in sorted(dimension_data['scoring'].keys(), key=lambda x: int(x), reverse=True):
        score_data = dimension_data['scoring'][score_key]
        prompt += f"""
【{score_data['score']}分】
描述：{score_data['description']}
典型缺陷：{score_data['typical_defects']}
对学生的影响：{score_data['impact_on_students']}
"""

    prompt += f"""

请仔细阅读以下文档内容，并根据上述评分标准进行评估：

{text_content}

## 当前评估的图片

**正在评估：Scene {scene_index}**

请结合文档内容和图片，评估该scene的质量。

请以JSON格式返回评估结果，格式如下：
{{
    "dimension": "{dimension_name}",
    "score": <0-5之间的整数分数>,
    "justification": "<详细的评分理由，说明为什么给出这个分数>",
    "identified_issues": ["<识别出的问题1>", "<识别出的问题2>", ...]
}}
"""

    for attempt in range(retry_limit):
        try:
            # Prepare inputs with text and image
            inputs = _prepare_text_image_inputs(prompt, [scene_path])
            response_coro = model(inputs)

            # Handle async call
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, response_coro)
                    response = future.result()
            except RuntimeError:
                response = asyncio.run(response_coro)

            result = extract_json(response)
            result = convert_score_fields(result)
            return result
        except Exception as e:
            print(f"Attempt {attempt + 1} failed for scene {scene_index}: {e.__class__.__name__}: {e}")
            if attempt + 1 == retry_limit:
                print(f"Warning: Failed to evaluate scene {scene_index} after {retry_limit} attempts")
                return {
                    "dimension": dimension_name,
                    "score": 0,
                    "justification": f"Evaluation failed: {str(e)}",
                    "identified_issues": ["Evaluation error"]
                }


def evaluate_dimension_text_diagram_aa(
    model: Union[LiteLLMWrapper, GeminiWrapper],
    dimension_name: str,
    dimension_data: Dict,
    text_content: str,
    image_paths: List[str],
    retry_limit: int = 3
) -> Dict:
    """
    Evaluate a dimension using text and images without original problem reference.
    Each scene is evaluated with text content, and scores are combined using geometric mean.
    Does NOT use problem_data or original_image_path.

    Args:
        model: The LLM model to use for evaluation (must support vision)
        dimension_name: Name of the dimension
        dimension_data: Dimension metadata and scoring criteria
        text_content: The markdown text content
        image_paths: List of paths to images from the solution document
        retry_limit: Number of retry attempts

    Returns:
        dict: Evaluation result with score and justification
    """
    if not image_paths:
        # No images to evaluate, fallback to text-only
        print(f"No images found for dimension {dimension_name}, using text-only evaluation")
        return evaluate_dimension_text_only(model, dimension_name, dimension_data, text_content, retry_limit, problem_data=None)

    # Evaluate each scene separately
    scene_results = []
    scene_scores = []

    MAX_SCENE_RETRIES = 2  # Maximum retries for scene-level score 0

    for idx, scene_path in enumerate(image_paths, 1):
        print(f"  Evaluating Scene {idx}/{len(image_paths)}: {os.path.basename(scene_path)}")

        scene_result = evaluate_single_scene_without_original(
            model, dimension_name, dimension_data, text_content,
            scene_path, idx, retry_limit
        )

        # Retry if scene scored 0
        retry_count = 0
        scene_score = scene_result.get('score', 0)

        while scene_score == 0 and retry_count < MAX_SCENE_RETRIES:
            retry_count += 1
            print(f"    ⚠ Scene {idx} scored 0, retrying ({retry_count}/{MAX_SCENE_RETRIES})...")

            scene_result = evaluate_single_scene_without_original(
                model, dimension_name, dimension_data, text_content,
                scene_path, idx, retry_limit
            )

            scene_score = scene_result.get('score', 0)

            if scene_score > 0:
                print(f"    ✓ Retry successful! New score: {scene_score}")
            else:
                print(f"    ✗ Retry {retry_count} still scored 0")

        scene_results.append({
            "scene_index": idx,
            "scene_path": scene_path,
            "result": scene_result
        })

        scene_scores.append(scene_score)

    # Calculate geometric mean of all scene scores
    if scene_scores:
        final_score = calculate_geometric_mean(scene_scores)
    else:
        final_score = 0

    # Aggregate justifications and issues
    all_justifications = []
    all_issues = []

    for scene_res in scene_results:
        scene_idx = scene_res["scene_index"]
        result = scene_res["result"]
        all_justifications.append(f"Scene {scene_idx} (得分: {result.get('score', 0)}): {result.get('justification', '')}")
        all_issues.extend([f"Scene {scene_idx}: {issue}" for issue in result.get('identified_issues', [])])

    # Return aggregated result
    return {
        "dimension": dimension_name,
        "score": final_score,
        "justification": "\n\n".join(all_justifications),
        "identified_issues": all_issues,
        "scene_details": scene_results,
        "scene_scores": scene_scores
    }


def evaluate_document(
    model: Union[LiteLLMWrapper, GeminiWrapper],
    doc_path: str,
    rubric_path: str,
    retry_limit: int = 3,
    problem_data: Optional[Dict] = None,
    existing_result: Optional[Dict] = None
) -> Dict:
    """
    Evaluate a markdown document with images against a rubric.

    Args:
        model: The LLM model to use for evaluation
        doc_path: Path to the markdown document
        rubric_path: Path to the evaluation rubric JSON
        retry_limit: Number of retry attempts per dimension
        problem_data: Optional original problem data with img, img_caption, format_answer
        existing_result: Optional existing evaluation result to check for zero scores

    Returns:
        dict: Complete evaluation results with scores for all dimensions
    """
    # Parse document
    text_content, image_paths = parse_markdown_with_images(doc_path)
    print(f"Loaded document: {doc_path}")
    print(f"Found {len(image_paths)} images in solution document")

    # Load rubric
    rubric = load_rubric(rubric_path)
    dimensions = rubric.get('dimensions', {})

    # Convert original problem image from base64 if available
    original_image_path = None
    temp_image_cleanup = []  # Track temp files for cleanup

    if problem_data and 'img' in problem_data and problem_data['img']:
        original_image_path = base64_to_temp_image(problem_data['img'])
        if original_image_path:
            temp_image_cleanup.append(original_image_path)
            print(f"Loaded original problem image for reference")

    # Check if we have existing results to reuse
    dimensions_to_evaluate = []
    existing_dimension_details = {}

    if existing_result and 'dimension_details' in existing_result:
        print(f"Found existing evaluation results, checking for zero scores...")
        existing_dimension_details = existing_result['dimension_details']

        for dim_name in dimensions.keys():
            if dim_name in existing_dimension_details:
                existing_dim = existing_dimension_details[dim_name]
                score = existing_dim.get('score', 0)

                # Check if dimension or any of its scenes/images scored 0
                needs_reevaluation = score == 0

                if not needs_reevaluation and 'scene_details' in existing_dim:
                    for scene in existing_dim['scene_details']:
                        if scene['result'].get('score', 1) == 0:
                            needs_reevaluation = True
                            break

                if not needs_reevaluation and 'image_details' in existing_dim:
                    for image in existing_dim['image_details']:
                        if image['result'].get('score', 1) == 0:
                            needs_reevaluation = True
                            break

                if needs_reevaluation:
                    print(f"  ⚠ Dimension {dim_name} has zero scores, will re-evaluate")
                    dimensions_to_evaluate.append(dim_name)
                else:
                    print(f"  ✓ Dimension {dim_name} (score: {score:.2f}) - reusing existing result")
            else:
                # Dimension not in existing results, need to evaluate
                dimensions_to_evaluate.append(dim_name)
    else:
        # No existing results, evaluate all dimensions
        dimensions_to_evaluate = list(dimensions.keys())
        print(f"No existing results found, evaluating all dimensions")

    # Evaluate each dimension
    results = {
        "document": doc_path,
        "evaluation": {},
        "dimension_details": {}
    }

    scores = []

    try:
        for dim_name, dim_data in dimensions.items():
            # Check if we should evaluate this dimension or reuse existing result
            if dim_name not in dimensions_to_evaluate:
                # Reuse existing result
                existing_dim = existing_dimension_details[dim_name]
                score = existing_dim.get('score', 0)
                scores.append(score)

                results['evaluation'][dim_name] = {
                    "score": score,
                    "name": dim_data['name']
                }
                results['dimension_details'][dim_name] = existing_dim
                continue

            print(f"Evaluating dimension: {dim_data['name']} ({dim_name})")

            eval_type = dim_data.get('type', 'text')

            # Evaluation function mapping
            def evaluate_dimension_by_type():
                if eval_type == 'text':
                    # Text-only evaluation
                    return evaluate_dimension_text_only(
                        model, dim_name, dim_data, text_content, retry_limit, problem_data
                    )
                elif eval_type == 'text_diagram':
                    # Text + image evaluation (include original problem image if available)
                    return evaluate_dimension_with_images(
                        model, dim_name, dim_data, text_content, image_paths, retry_limit,
                        problem_data, original_image_path
                    )
                elif eval_type == 'text_diagram_aa':
                    # Text + image evaluation WITHOUT original problem reference
                    return evaluate_dimension_text_diagram_aa(
                        model, dim_name, dim_data, text_content, image_paths, retry_limit
                    )
                elif eval_type == 'diagram':
                    # Diagram-only evaluation (each image evaluated independently)
                    return evaluate_dimension_diagram_only(
                        model, dim_name, dim_data, image_paths, retry_limit, problem_data
                    )
                elif eval_type == 'diagram_aa':
                    # Diagram consistency evaluation (all images compared to first image)
                    return evaluate_dimension_diagram_consistency(
                        model, dim_name, dim_data, image_paths, retry_limit, problem_data
                    )
                else:
                    print(f"Warning: Unknown evaluation type '{eval_type}' for dimension {dim_name}")
                    return None

            # Initial evaluation
            dim_result = evaluate_dimension_by_type()

            if dim_result is None:
                continue

            # Retry logic for score 0
            MAX_DIMENSION_RETRIES = 2  # Maximum number of retries for dimension-level score 0
            retry_count = 0
            score = dim_result.get('score', 0)

            while score == 0 and retry_count < MAX_DIMENSION_RETRIES:
                retry_count += 1
                print(f"  ⚠ Dimension {dim_name} scored 0, retrying ({retry_count}/{MAX_DIMENSION_RETRIES})...")

                dim_result = evaluate_dimension_by_type()

                if dim_result is None:
                    break

                score = dim_result.get('score', 0)

                if score > 0:
                    print(f"  ✓ Retry successful! New score: {score}")
                else:
                    print(f"  ✗ Retry {retry_count} still scored 0")

            # Store results
            scores.append(score)

            results['evaluation'][dim_name] = {
                "score": score,
                "name": dim_data['name']
            }
            results['dimension_details'][dim_name] = dim_result

        # Calculate geometric mean of all dimension scores
        if scores:
            overall_score = calculate_geometric_mean(scores)
            results['evaluation']['overall_score'] = {
                "score": overall_score,
                "name": "综合得分"
            }

    finally:
        # Clean up temporary image files
        for temp_file in temp_image_cleanup:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception as e:
                print(f"Warning: Failed to clean up temporary file {temp_file}: {e}")

    return results
