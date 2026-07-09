import os
import json
import re
import argparse
import tempfile
import fcntl
import time
from typing import Dict, List, Union, Optional
from datetime import datetime
from multiprocessing import Pool, cpu_count

from dotenv import load_dotenv
from moviepy import VideoFileClip

from visual_solver.mllm_tools.litellm import LiteLLMWrapper
from visual_solver.mllm_tools.gemini import GeminiWrapper
from eval_suite.utils import calculate_geometric_mean
from eval_suite.text_utils import parse_srt_to_text, fix_transcript, evaluate_text
from eval_suite.explanation_utils import evaluate_explanation_chunk_new
from eval_suite.image_utils import evaluate_sampled_images
from eval_suite.doc_utils import evaluate_document

load_dotenv(override=True)  # 强制覆盖系统环境变量
print(f"[DEBUG] evaluate.py load_dotenv() in PID {os.getpid()}")
print(f"[DEBUG] Current working directory: {os.getcwd()}")
print(f"[DEBUG] .env file location: {os.path.abspath('.env')}")
print(f"[DEBUG] CUSTOM_API_BASE after load: {os.getenv('CUSTOM_API_BASE')}")

PROGRESS_FILE = "evaluation_progress.json"  # 进度文件名
LOCK_FILE = "evaluation.lock"  # 文件锁名

def load_existing_evaluation(output_folder: str, problem_name: str) -> Optional[Dict]:
    """
    Load existing evaluation result for a specific problem from individual problem file.

    Args:
        output_folder: Path to output folder containing evaluation files
        problem_name: Name of the problem (e.g., "problem_17_physics_g9")

    Returns:
        Dict: Existing evaluation result or None if not found
    """
    if not os.path.exists(output_folder):
        return None

    # Find individual problem evaluation files (e.g., evaluation_problem_98_math_g9_*.json)
    individual_files = []
    for filename in os.listdir(output_folder):
        if filename.startswith(f'evaluation_{problem_name}_') and filename.endswith('.json'):
            filepath = os.path.join(output_folder, filename)
            individual_files.append((filepath, os.path.getmtime(filepath)))

    if not individual_files:
        return None

    # Sort by modification time, newest first
    individual_files.sort(key=lambda x: x[1], reverse=True)
    latest_file = individual_files[0][0]

    try:
        with open(latest_file, 'r', encoding='utf-8') as f:
            result = json.load(f)

        print(f"  📂 Loaded existing evaluation for {problem_name} from {os.path.basename(latest_file)}")
        return result
    except Exception as e:
        print(f"  ⚠ Warning: Failed to load existing evaluation from {latest_file}: {e}")

    return None

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "utils", "allowed_models.json")) as f:
    ALLOWED_MODELS = json.load(f)["allowed_models"]


def parse_problem_name(problem_name: str) -> Optional[int]:
    """
    Parse problem directory name to extract index.

    Args:
        problem_name: Problem directory name (e.g., "problem_6_physics_g12")

    Returns:
        int: Problem index or None if parsing fails
    """
    # Pattern: problem_{index}_...
    pattern = r'problem_(\d+)_'
    match = re.match(pattern, problem_name)

    if match:
        return int(match.group(1))
    return None


def load_problem_data_from_file(problem_data_path: str, problem_index: int) -> Optional[Dict]:
    """
    Load specific problem data from JSON file by index.

    Args:
        problem_data_path: Path to the problem data JSON file
        problem_index: Index of the problem in the JSON array

    Returns:
        dict: Problem data or None if not found
    """
    if not problem_data_path or not os.path.exists(problem_data_path):
        return None

    try:
        with open(problem_data_path, 'r', encoding='utf-8') as f:
            problems = json.load(f)

        if 0 <= problem_index < len(problems):
            problem = problems[problem_index]
            print(f"Loaded problem data for index {problem_index} from {os.path.basename(problem_data_path)}")
            return problem
        else:
            print(f"Warning: Problem index {problem_index} out of range (total: {len(problems)})")
            return None
    except Exception as e:
        print(f"Warning: Failed to load problem data: {e}")
        return None


def load_progress(output_folder: str) -> Dict[str, bool]:
    """
    Load evaluation progress from file with file locking for concurrent access.

    Args:
        output_folder (str): Directory containing progress file.

    Returns:
        Dict[str, bool]: Dictionary of completed file names.
    """
    progress_path = os.path.join(output_folder, PROGRESS_FILE)
    lock_path = os.path.join(output_folder, LOCK_FILE)

    # Ensure lock file exists
    os.makedirs(output_folder, exist_ok=True)

    if not os.path.exists(progress_path):
        return {}

    try:
        # Acquire shared lock for reading
        with open(lock_path, 'a') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
            try:
                with open(progress_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        print(f"Warning: Could not load progress file: {e}")
        return {}


def save_progress(output_folder: str, completed: Dict[str, bool]) -> None:
    """
    Save evaluation progress to file with file locking for concurrent access.

    Args:
        output_folder (str): Directory to store progress file.
        completed (Dict[str, bool]): Dictionary of completed file names.

    Returns:
        None
    """
    progress_path = os.path.join(output_folder, PROGRESS_FILE)
    lock_path = os.path.join(output_folder, LOCK_FILE)

    # Ensure output folder exists
    os.makedirs(output_folder, exist_ok=True)

    try:
        # Acquire exclusive lock for writing
        with open(lock_path, 'a') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                with open(progress_path, 'w', encoding='utf-8') as f:
                    json.dump(completed, f, indent=4, ensure_ascii=False)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        print(f"Warning: Could not save progress: {e}")


def claim_task(output_folder: str, problem_name: str) -> bool:
    """
    Try to claim a task for evaluation. Returns True if successfully claimed, False if already claimed.
    Uses atomic file locking to prevent race conditions.

    Args:
        output_folder (str): Directory containing progress file.
        problem_name (str): Name of the problem to claim.

    Returns:
        bool: True if task was successfully claimed, False if already claimed.
    """
    lock_path = os.path.join(output_folder, LOCK_FILE)
    progress_path = os.path.join(output_folder, PROGRESS_FILE)

    # Ensure output folder exists
    os.makedirs(output_folder, exist_ok=True)

    try:
        # Acquire exclusive lock
        with open(lock_path, 'a') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                # Load current progress
                if os.path.exists(progress_path):
                    with open(progress_path, 'r', encoding='utf-8') as f:
                        completed = json.load(f)
                else:
                    completed = {}

                # Check if already completed
                if problem_name in completed:
                    return False

                # Claim the task by marking it as completed (in-progress)
                completed[problem_name] = True

                # Save updated progress
                with open(progress_path, 'w', encoding='utf-8') as f:
                    json.dump(completed, f, indent=4, ensure_ascii=False)

                return True
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        print(f"Warning: Could not claim task {problem_name}: {e}")
        return False


def load_existing_results(output_folder: str) -> Dict[str, Dict]:
    """
    Load all existing evaluation result files from output folder.
    For duplicate problem names, keeps only the newest file and deletes older ones.

    Args:
        output_folder (str): Directory containing result files.

    Returns:
        Dict[str, Dict]: Dictionary of existing results with problem names as keys.
    """
    results = {}
    problem_files = {}  # Track all files for each problem

    if not os.path.exists(output_folder):
        return results

    # First pass: collect all files for each problem
    for file in os.listdir(output_folder):
        if file.startswith("evaluation_") and file.endswith(".json") and file != PROGRESS_FILE:
            file_path = os.path.join(output_folder, file)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    result = json.load(f)

                    problem_name = None

                    # Extract from document path (for doc evaluation)
                    if "document" in result and isinstance(result["document"], str):
                        doc_path = result["document"]
                        # Extract problem name from path like "output/with_img_kimi/problem_6_physics_g12/doc/solution.md"
                        parts = doc_path.split('/')
                        for part in parts:
                            if part.startswith('problem_'):
                                problem_name = part
                                break  # Important: stop after finding the first problem_* part

                    # Fallback: Extract from filename (format: evaluation_{name}_{timestamp}.json)
                    if problem_name is None:
                        # Remove "evaluation_" prefix and "_{timestamp}.json" suffix
                        name_part = file.replace("evaluation_", "").rsplit("_", 2)[0]
                        # Only use if it looks like a problem name
                        if name_part.startswith('problem_'):
                            problem_name = name_part

                    # Only add if we found a valid problem name
                    if problem_name and problem_name.startswith('problem_'):
                        file_mtime = os.path.getmtime(file_path)

                        # Track all files for this problem
                        if problem_name not in problem_files:
                            problem_files[problem_name] = []

                        problem_files[problem_name].append({
                            'path': file_path,
                            'file': file,
                            'mtime': file_mtime,
                            'result': result
                        })

            except Exception as e:
                print(f"Warning: Could not load result file {file}: {e}")

    # Second pass: keep newest file for each problem and delete old ones
    for problem_name, files in problem_files.items():
        if len(files) > 1:
            # Sort by modification time, newest first
            files.sort(key=lambda x: x['mtime'], reverse=True)

            # Keep the newest
            newest = files[0]
            results[problem_name] = newest['result']

            # Delete older files
            for old_file in files[1:]:
                try:
                    os.remove(old_file['path'])
                    print(f"  🗑️  Deleted old evaluation file: {old_file['file']}")
                except Exception as e:
                    print(f"  ⚠️  Failed to delete {old_file['file']}: {e}")
        else:
            # Only one file, just use it
            results[problem_name] = files[0]['result']

    return results


def combine_results(output_folder: str, combined_file: str, results: Dict[str, Dict]) -> None:
    """
    Combine all evaluation results into a single file.

    Args:
        output_folder (str): Directory to store the combined file.
        combined_file (str): Name of the combined file.
        results (Dict[str, Dict]): Dictionary of evaluation results with file names as keys.

    Returns:
        None
    """
    combined_path = os.path.join(output_folder, combined_file)
    with open(combined_path, 'w', encoding='utf-8') as output_file:
        json.dump(results, output_file, indent=4, ensure_ascii=False)


def save_individual_result(output_folder: str, file_name: str, result: Dict) -> None:
    """
    Save individual evaluation result to a file.

    Args:
        output_folder (str): Directory to store the evaluation file.
        file_name (str): Name of the file.
        result (Dict): Evaluation result.

    Returns:
        None
    """
    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = f"evaluation_{file_name}_{current_time}.json"
    os.makedirs(output_folder, exist_ok=True)
    result_path = os.path.join(output_folder, result_file)
    with open(result_path, 'w', encoding='utf-8') as output_file:
        json.dump(result, output_file, indent=4, ensure_ascii=False)


def evaluate_text_file(model, transcript_path, retry_limit):
    """
    Evaluate a text file using the provided model.

    Args:
        model: The model to use for evaluation.
        transcript_path (str): Path to the transcript file (.srt or .txt).
        retry_limit (int): Number of retry attempts for evaluation.

    Returns:
        Dict or None: Evaluation results if successful, None if file format unsupported.
    """
    if not transcript_path.endswith(('.srt', '.txt')):
        print(f"Skipping {transcript_path}: Unsupported file format for text evaluation.")
        return None

    # Reset token counter before evaluation
    if hasattr(model, 'reset_token_usage'):
        model.reset_token_usage()

    if transcript_path.endswith(".srt"):
        transcript = parse_srt_to_text(transcript_path)
    elif transcript_path.endswith(".txt"):
        with open(transcript_path) as f:
            transcript = f.read().strip()
    else:
        raise ValueError("Unrecognized transcript file format.")

    capital_letter_proportion = sum(1 for c in transcript if c.isupper()) / sum(1 for c in transcript if c.isalpha())
    if capital_letter_proportion < 0.01:
        transcript = fix_transcript(model, transcript)

    print(f"Performing text evaluation: {os.path.basename(transcript_path)}")
    result = evaluate_text(model, transcript, retry_limit)

    # Add token usage to result
    if hasattr(model, 'get_token_usage'):
        token_usage = model.get_token_usage()
        result['token_usage'] = token_usage
        print(f"  Text evaluation tokens: {token_usage['total_tokens']} (in: {token_usage['input_tokens']}, out: {token_usage['output_tokens']})")

    return result


def evaluate_doc_file(model, doc_path, rubric_path, retry_limit, problem_data=None, existing_result=None):
    """
    Evaluate a markdown document file with images using the provided model.

    Args:
        model: The model to use for evaluation.
        doc_path (str): Path to the markdown document (.md).
        rubric_path (str): Path to the evaluation rubric JSON file.
        retry_limit (int): Number of retry attempts for evaluation.
        problem_data (dict, optional): Original problem data with img, img_caption, format_answer.
        existing_result (dict, optional): Existing evaluation result to check for zero scores.

    Returns:
        Dict or None: Evaluation results if successful, None if file format unsupported.
    """
    if not doc_path.endswith('.md'):
        print(f"Skipping {doc_path}: Unsupported file format for document evaluation.")
        return None

    # Check for rendering failure in the document (any scene number)
    with open(doc_path, 'r', encoding='utf-8') as f:
        doc_content = f.read()

    # Use regex to match "Scene X rendering failed" where X is any number
    rendering_failed_match = re.search(r'Scene \d+ rendering failed', doc_content)
    rendering_failed = rendering_failed_match is not None

    # Reset token counter before evaluation
    if hasattr(model, 'reset_token_usage'):
        model.reset_token_usage()

    print(f"Performing document evaluation: {os.path.basename(doc_path)}")
    result = evaluate_document(model, doc_path, rubric_path, retry_limit, problem_data, existing_result)

    # Add rendering failure flag to result
    if rendering_failed:
        result['rendering_failed'] = True
        print(f"  ⚠ Warning: Rendering failure detected - {rendering_failed_match.group()}")

    # Add token usage to result
    if hasattr(model, 'get_token_usage'):
        token_usage = model.get_token_usage()
        result['token_usage'] = token_usage
        print(f"  Document evaluation tokens: {token_usage['total_tokens']} (in: {token_usage['input_tokens']}, out: {token_usage['output_tokens']})")

    return result


def evaluate_explanation_file(model, explanation_path, transcript_path, description_path, target_fps=None, output_folder=None):
    """
    Evaluate a explanation file using the provided model.

    Args:
        model: The model to use for evaluation.
        explanation_path (str): Path to the explanation file.
        transcript_path (str): Path to the transcript file.
        description_path (str): Path to the description file.
        target_fps (int, optional): Target frames per second for explanation processing.
        output_folder (str, optional): Directory to store output files.

    Returns:
        Dict or None: Evaluation results if successful, None if file format unsupported.
    """
    if not explanation_path.endswith(('.mp4', '.mkv')):
        print(f"Skipping {explanation_path}: Unsupported file format for explanation evaluation.")
        return None

    moviepy_temp_dir = os.path.join(output_folder, "moviepy_temp")

    # Chunking
    num_chunks = 10
    with VideoFileClip(explanation_path) as clip:
        duration = clip.duration
        chunk_duration = duration / num_chunks
        results = []
        
        # Create a temporary directory in the output_folder
        temp_dir_parent = output_folder or os.getcwd()
        with tempfile.TemporaryDirectory(dir=temp_dir_parent) as temp_dir:
            for i in range(10):
                start = i * chunk_duration
                end = min(start + chunk_duration, duration)
                chunk = clip.subclipped(start, end)
                chunk_path = os.path.join(temp_dir, f"chunk_{i+1}.mp4")
                # Explicitly set the temp_audiofile path with matching codec
                temp_audiofile = os.path.join(moviepy_temp_dir, f"temp_audio_chunk_{i+1}.m4a")
                chunk.write_explanationfile(
                    chunk_path,
                    codec="libx264",
                    audio_codec="aac",
                    temp_audiofile=temp_audiofile,
                    audio_bitrate="192k",
                    preset="ultrafast",  # Speed up encoding
                    logger=None
                )
                # Create processed explanations folder inside output_folder
                processed_explanations_dir = os.path.join(output_folder, "processed_explanations")
                save_path = os.path.join(processed_explanations_dir, f"processed_chunk_{i+1}.mp4")
                result = evaluate_explanation_chunk_new(
                    model,
                    chunk_path,
                    transcript_path,
                    description_path,
                    target_fps=target_fps,
                    save_processed_explanation=save_path
                )
                results.append(result)

    score_dict = {}
    for key in results[0]["evaluation"].keys():
        score_dict[key] = []
        for result in results:
            score_dict[key].append(result["evaluation"][key]["score"])

    evaluation = {}
    for key, scores in score_dict.items():
        evaluation[key] = {"score": calculate_geometric_mean(scores)}

    result_json = {
        "evaluation": evaluation,
        "explanation_chunks": results
    }
    return result_json


def extract_scores(data: Union[Dict, List]) -> List[int]:
    """
    Extract all score values from a nested dictionary or list structure.

    Args:
        data (Union[Dict, List]): The data structure to extract scores from.

    Returns:
        List[int]: List of extracted score values.
    """
    scores = []
    if isinstance(data, dict):
        for key, value in data.items():
            if "chunks" in key:
                continue
            elif isinstance(value, dict) or isinstance(value, list):
                scores.extend(extract_scores(value))
            elif key == 'score':
                scores.append(value)
    elif isinstance(data, list):
        for item in data:
            scores.extend(extract_scores(item))
    return scores


def calculate_overall_score(result: Dict) -> float:
    """
    Calculate the overall score from evaluation results.

    Args:
        result (Dict): Dictionary containing evaluation results.

    Returns:
        float: The calculated overall score.
    """
    scores = extract_scores(result)
    overall_score = calculate_geometric_mean(scores)
    return overall_score


def process_topic_name(topic_name: str) -> str:
    """
    Process a topic name by capitalizing words and handling special characters.

    Args:
        topic_name (str): The topic name to process.

    Returns:
        str: The processed topic name.
    """
    words = topic_name.replace("_s_", "'s_").split("_")
    return " ".join([word.capitalize() for word in words])


def merge_dicts(dict1: dict, dict2: dict) -> dict:
    """
    Recursively merge two dictionaries.

    Args:
        dict1 (dict): First dictionary.
        dict2 (dict): Second dictionary.

    Returns:
        dict: Merged dictionary.
    """
    merged = dict1.copy()
    for key, value in dict2.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def process_theorem(models, file_path: str, eval_type: str, retry_limit: int,
                    target_fps: int = None, use_parent_folder_as_topic: bool = False,
                    output_folder: str = None, rubric_path: str = None,
                    problem_data_path: str = None, problem_data_cache: dict = None,
                    existing_result: dict = None) -> tuple[str, dict]:
    """
    Process a theorem file or directory for evaluation.

    Args:
        models: Dictionary of models for different evaluation types.
        file_path (str): Path to the file or directory to evaluate.
        eval_type (str): Type of evaluation to perform.
        retry_limit (int): Number of retry attempts.
        target_fps (int, optional): Target frames per second for explanation processing.
        use_parent_folder_as_topic (bool, optional): Use parent folder name as topic.
        output_folder (str, optional): Directory to store output files.
        rubric_path (str, optional): Path to evaluation rubric JSON file.
        problem_data_path (str, optional): Path to problem data JSON file.
        problem_data_cache (dict, optional): Cached problem data to avoid repeated loading.
        existing_result (dict, optional): Existing evaluation result to check for zero scores.

    Returns:
        tuple[str, dict]: Tuple of file name and evaluation results.
    """
    ext_map = {
        'text': ('.txt', '.srt'),
        'explanation': ('.mp4', '.mkv'),
        'doc': ('.md',)
    }

    # Handle single file evaluation
    if os.path.isfile(file_path):
        file_ext = os.path.splitext(file_path)[1].lower()
        file_name = os.path.basename(file_path)

        if eval_type == "text" and file_ext in ext_map['text']:
            return file_name, evaluate_text_file(models['text'], file_path, retry_limit)
        elif eval_type == "doc" and file_ext in ext_map['doc']:
            # For document evaluation, we need a rubric path
            if rubric_path is None:
                rubric_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_suite", "doc_evaluation_rubric.json")
            return file_name, evaluate_doc_file(models['doc'], file_path, rubric_path, retry_limit)
        elif eval_type == "explanation" and file_ext in ext_map['explanation']:
            if use_parent_folder_as_topic:
                topic_name = os.path.basename(os.path.dirname(file_path))
            else:
                topic_name = None
            topic_name = process_topic_name(topic_name)
            return file_name, evaluate_explanation_file(models['explanation'], file_path, None, topic_name, target_fps, output_folder)
        elif eval_type == "image" and file_ext in ext_map['explanation']:
            if use_parent_folder_as_topic:
                topic_name = os.path.basename(os.path.dirname(file_path))
            else:
                topic_name = None
            topic_name = process_topic_name(topic_name)
            return file_name, evaluate_sampled_images(models['image'], file_path, topic_name, num_chunks=10, output_folder=output_folder)
        elif eval_type == "all":
            raise ValueError("Evaluation type 'all' is not supported for a single file. Try passing a folder with both a explanation and a subtitle file.")
        else:
            raise ValueError(f"File type of {file_path} does not match evaluation type {eval_type!r}")

    # Handle directory evaluation
    theorem_dir = file_path
    all_files = os.listdir(theorem_dir)

    # Look for transcript files, prioritizing .srt over .txt if both exist
    transcript_file_candidates = [f for f in all_files if f.endswith(ext_map['text']) and not f.endswith('_scene_outline.txt')]
    srt_files = [f for f in transcript_file_candidates if f.endswith('.srt')]
    txt_files = [f for f in transcript_file_candidates if f.endswith('.txt')]

    transcript_path = None
    if srt_files:
        transcript_path = os.path.join(theorem_dir, srt_files[0])
    elif txt_files:
        transcript_path = os.path.join(theorem_dir, txt_files[0])

    explanation_file_candidates = [f for f in all_files if f.endswith(ext_map['explanation'])]
    explanation_path = os.path.join(theorem_dir, explanation_file_candidates[0]) if len(explanation_file_candidates) == 1 else None

    # Look for solution.md document (check both root and doc subdirectory)
    doc_path = None
    # First check for solution.md in root directory
    if 'solution.md' in all_files:
        doc_path = os.path.join(theorem_dir, 'solution.md')
    else:
        # Check in doc subdirectory
        doc_subdir = os.path.join(theorem_dir, 'doc')
        if os.path.isdir(doc_subdir):
            solution_path = os.path.join(doc_subdir, 'solution.md')
            if os.path.exists(solution_path):
                doc_path = solution_path

    topic_name = os.path.basename(theorem_dir)
    topic_name = process_topic_name(topic_name)

    # Load problem data if path is provided and we're evaluating documents
    problem_data = None
    if problem_data_path and (eval_type == "doc" or eval_type == "all"):
        # Extract problem index from directory name
        problem_name = os.path.basename(theorem_dir)
        problem_index = parse_problem_name(problem_name)

        if problem_index is not None:
            # Use cache if available
            if problem_data_cache is not None and problem_index in problem_data_cache:
                problem_data = problem_data_cache[problem_index]
            else:
                problem_data = load_problem_data_from_file(problem_data_path, problem_index)
                if problem_data_cache is not None:
                    problem_data_cache[problem_index] = problem_data

    # For doc-only evaluation, we don't need a explanation
    if eval_type == "doc":
        if doc_path is None:
            print(f"Skipping {theorem_dir}: No markdown document found")
            return None, None
        if rubric_path is None:
            rubric_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_suite", "doc_evaluation_rubric.json")
        result = evaluate_doc_file(models['doc'], doc_path, rubric_path, retry_limit, problem_data, existing_result)
        file_name = os.path.basename(theorem_dir)
        return file_name, result

    if not explanation_path:
        print(f"Skipping {theorem_dir}: No explanation file found")
        return None, None

    text_result = explanation_result = image_result = doc_result = None
    if eval_type == "text" or eval_type == "all":
        if transcript_path is None:
            print(f"Warning: No suitable transcript file found in {theorem_dir}")
        else:
            text_result = evaluate_text_file(models['text'], transcript_path, retry_limit)
    if eval_type == "explanation" or eval_type == "all":
        assert explanation_path is not None, f"Expected 1 explanation file, got {len(explanation_file_candidates)} for {theorem_dir}"
        explanation_result = evaluate_explanation_file(models['explanation'], explanation_path, transcript_path, topic_name, target_fps, output_folder)
    if eval_type == "image" or eval_type == "all":
        assert explanation_path is not None, f"Expected 1 explanation file, got {len(explanation_file_candidates)} for {theorem_dir}"
        image_result = evaluate_sampled_images(models['image'], explanation_path, topic_name, num_chunks=10, output_folder=output_folder)

    # Optionally evaluate document if present (for "all" type)
    if eval_type == "all" and doc_path is not None:
        if rubric_path is None:
            rubric_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_suite", "doc_evaluation_rubric.json")
        doc_result = evaluate_doc_file(models['doc'], doc_path, rubric_path, retry_limit, problem_data, existing_result)

    if eval_type == "all":
        result = {}
        if text_result:
            result = merge_dicts(result, text_result)
        if explanation_result:
            result = merge_dicts(result, explanation_result)
        if image_result:
            result = merge_dicts(result, image_result)
        if doc_result:
            result = merge_dicts(result, doc_result)
        if result:
            result["evaluation"]["overall_score"] = calculate_overall_score(result)

        # Aggregate token usage from all evaluation types
        total_token_usage = {
            "total_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0
        }
        token_by_type = {}

        if text_result and 'token_usage' in text_result:
            token_by_type['text'] = text_result['token_usage']
            total_token_usage['total_tokens'] += text_result['token_usage']['total_tokens']
            total_token_usage['input_tokens'] += text_result['token_usage']['input_tokens']
            total_token_usage['output_tokens'] += text_result['token_usage']['output_tokens']

        if doc_result and 'token_usage' in doc_result:
            token_by_type['doc'] = doc_result['token_usage']
            total_token_usage['total_tokens'] += doc_result['token_usage']['total_tokens']
            total_token_usage['input_tokens'] += doc_result['token_usage']['input_tokens']
            total_token_usage['output_tokens'] += doc_result['token_usage']['output_tokens']

        # Add aggregated token usage to result
        if token_by_type:
            result['token_usage'] = {
                **total_token_usage,
                'by_type': token_by_type
            }
            print(f"  Total token usage: {total_token_usage['total_tokens']} (in: {total_token_usage['input_tokens']}, out: {total_token_usage['output_tokens']})")

    else:
        result = text_result if eval_type == "text" else explanation_result if eval_type == "explanation" else image_result if eval_type == "image" else doc_result if eval_type == "doc" else None

    file_name = os.path.basename(theorem_dir)
    return file_name, result


def evaluate_single_dir_worker(args_tuple):
    """
    Worker function for parallel evaluation of a single directory.
    Uses task claiming mechanism to avoid duplicate work.

    Args:
        args_tuple: Tuple containing all necessary arguments

    Returns:
        Tuple of (problem_name, file_name, result) or (problem_name, None, None) if skipped
    """
    (theorem_dir, model_configs, eval_type, retry_limit, target_fps,
     use_parent_folder_as_topic, output_folder, rubric_path,
     problem_data_path, idx, total) = args_tuple

    problem_name = os.path.basename(theorem_dir)

    # Load existing evaluation result for this problem
    existing_result = load_existing_evaluation(output_folder, problem_name)
    if existing_result:
        print(f"  📂 Loaded existing evaluation for {problem_name}")
    else:
        print(f"  ℹ️  No existing evaluation found for {problem_name}")

    # Try to claim this task
    if not claim_task(output_folder, problem_name):
        print(f"[{idx}/{total}] Worker {os.getpid()}: Skipping {problem_name} (already claimed/completed)")
        return problem_name, None, None

    print(f"[{idx}/{total}] Worker {os.getpid()}: Evaluating {problem_name}...")

    try:
        # Initialize models in worker process
        models = {}
        if 'text' in model_configs:
            models['text'] = LiteLLMWrapper(model_name=model_configs['text'], print_cost=True)
        if 'explanation' in model_configs:
            models['explanation'] = GeminiWrapper(model_name=model_configs['explanation'])
        if 'image' in model_configs:
            models['image'] = LiteLLMWrapper(model_name=model_configs['image'], print_cost=True)
        if 'doc' in model_configs:
            models['doc'] = LiteLLMWrapper(model_name=model_configs['doc'], print_cost=True)

        # Create problem data cache for this worker
        problem_data_cache = {}

        file_name, result = process_theorem(
            models,
            theorem_dir,
            eval_type,
            retry_limit,
            target_fps,
            use_parent_folder_as_topic,
            output_folder,
            rubric_path,
            problem_data_path,
            problem_data_cache,
            existing_result
        )

        if result is not None:
            # Save individual result immediately
            save_individual_result(output_folder, file_name, result)
            print(f"  Worker {os.getpid()}: ✓ Completed and saved: {file_name}")
            return problem_name, file_name, result
        else:
            print(f"  Worker {os.getpid()}: ✗ Skipped: {problem_name}")
            return problem_name, None, None

    except Exception as e:
        print(f"  Worker {os.getpid()}: ✗ Error evaluating {problem_name}: {e}")
        import traceback
        traceback.print_exc()
        return problem_name, None, None


def main():
    """
    Main function to run the evaluation script.

    Parses command line arguments and orchestrates the evaluation process
    for text, explanation, and image content using specified AI models.
    """
    parser = argparse.ArgumentParser(description='Automatic evaluation of theorem explanation explanations with LLMs')
    parser.add_argument('--model_text', type=str, 
                       choices=ALLOWED_MODELS,
                       default='azure/gpt-4o',
                       help='Select the AI model to use for text evaluation')
    parser.add_argument('--model_explanation', type=str,
                       choices=['gemini/gemini-1.5-pro-002',
                                'gemini/gemini-2.0-flash-exp',
                                'gemini/gemini-2.0-pro-exp-02-05'],
                       default='gemini/gemini-1.5-pro-002',
                       help='Select the AI model to use for explanation evaluation')
    parser.add_argument('--model_image', type=str,
                       choices=ALLOWED_MODELS,
                       default='azure/gpt-4o',
                       help='Select the AI model to use for image evaluation')
    parser.add_argument('--model_doc', type=str,
                       choices=ALLOWED_MODELS,
                       default='Kimi-K25',
                       help='Select the AI model to use for document evaluation')
    parser.add_argument('--rubric_path', type=str,
                       default=None,
                       help='Path to evaluation rubric JSON file (default: eval_suite/doc_evaluation_rubric.json)')
    parser.add_argument('--problem_data_path', type=str,
                       default=None,
                       help='Path to problem data JSON file (e.g., data/science_problem/science-g12_samples.json)')
    parser.add_argument('--eval_type', type=str, choices=['text', 'explanation', 'image', 'doc', 'all'], default='all', help='Type of evaluation to perform')
    parser.add_argument('--file_path', type=str, help='Path to a file or a theorem folder', required=True)
    parser.add_argument('--output_folder', type=str, help='Directory to store the evaluation files', required=True)
    parser.add_argument('--retry_limit', type=int, default=3, help='Number of retry attempts for each inference')
    parser.add_argument('--combine', action='store_true', help='Combine all results into a single JSON file')
    parser.add_argument('--bulk_evaluate', action='store_true', help='Evaluate a folder of theorems together', default=False)
    parser.add_argument('--target_fps', type=int, help='Target FPS for explanation processing. If not set, original explanation FPS will be used', required=False)
    parser.add_argument('--use_parent_folder_as_topic', action='store_true', help='Use parent folder name as topic name for single file evaluation', default=True)
    parser.add_argument('--max_workers', type=int, default=4, help='Maximum number of concurrent workers for parallel processing')
    parser.add_argument('--reset_progress', action='store_true', help='Clear previous progress and start from beginning', default=False)

    args = parser.parse_args()

    # Clear progress if requested
    if args.reset_progress:
        progress_file = os.path.join(args.output_folder, PROGRESS_FILE)
        if os.path.exists(progress_file):
            os.remove(progress_file)
            print("Previous progress cleared. Starting fresh evaluation...")

    # Initialize models based on evaluation type
    models = {}

    if args.eval_type in ['text', 'all']:
        text_model = LiteLLMWrapper(
            model_name=args.model_text,
            temperature=0.0,
            print_cost=True,
        )
        models['text'] = text_model

    if args.eval_type in ['explanation', 'all']:
        explanation_model = GeminiWrapper(
            model_name=args.model_explanation,
            temperature=0.0,
        )
        models['explanation'] = explanation_model

    if args.eval_type in ['image', 'all']:
        image_model = LiteLLMWrapper(
            model_name=args.model_image,
            temperature=0.0,
            print_cost=True,
        )
        models['image'] = image_model

    if args.eval_type in ['doc', 'all']:
        doc_model = LiteLLMWrapper(
            model_name=args.model_doc,
            temperature=0.0,
            print_cost=True,
        )
        models['doc'] = doc_model

    # Set default rubric path if not provided
    if args.rubric_path is None:
        rubric_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_suite", "doc_evaluation_rubric.json")
    else:
        rubric_path = args.rubric_path

    theorem_dirs = []
    if args.bulk_evaluate:
        assert os.path.isdir(args.file_path), "File path must be a folder for --bulk_evaluate"
        for root, dirnames, _ in os.walk(args.file_path):
            # Skip the 'doc' subdirectory itself
            if os.path.basename(root) == 'doc':
                continue

            # For doc evaluation, check for solution.md file instead of .mp4
            if args.eval_type == "doc":
                # Check for solution.md in root or doc subdirectory
                has_solution = (
                    os.path.exists(os.path.join(root, 'solution.md')) or
                    (os.path.isdir(os.path.join(root, 'doc')) and
                     os.path.exists(os.path.join(root, 'doc', 'solution.md')))
                )
                if not has_solution:
                    continue
            else:
                if not any(f.endswith(".mp4") for f in os.listdir(root)):
                    continue

            theorem_dirs.append(root)
    elif os.path.isdir(args.file_path):
        if args.eval_type == "doc":
            # Check for solution.md in the directory or doc subdirectory
            has_solution = (
                os.path.exists(os.path.join(args.file_path, 'solution.md')) or
                (os.path.isdir(os.path.join(args.file_path, 'doc')) and
                 os.path.exists(os.path.join(args.file_path, 'doc', 'solution.md')))
            )
            assert has_solution, "The provided folder must contain a solution.md file (in root or doc/ subdirectory)"
        else:
            assert any(f.endswith(".mp4") for f in os.listdir(args.file_path)), "The provided folder must contain a explanation file"

        theorem_dirs.append(args.file_path)

    # Create output directory and its temp subdirectories if it doesn't exist
    os.makedirs(args.output_folder, exist_ok=True)

    # Load progress and existing results for resume capability
    completed_files = load_progress(args.output_folder)
    existing_results = load_existing_results(args.output_folder)

    if completed_files:
        print(f"Found {len(completed_files)} completed evaluations. Resuming from checkpoint...")
        for file_name in list(completed_files.keys())[:5]:  # Show first 5
            print(f"  - {file_name}")
        if len(completed_files) > 5:
            print(f"  ... and {len(completed_files) - 5} more")

    # Only create explanation processing directories for explanation/image/all evaluation types
    if args.eval_type in ['explanation', 'image', 'all']:
        moviepy_temp_dir = os.path.join(args.output_folder, "moviepy_temp")
        os.makedirs(moviepy_temp_dir, exist_ok=True)
        VideoFileClip.DEFAULT_TEMP_DIR = moviepy_temp_dir

        processed_explanations_dir = os.path.join(args.output_folder, "processed_explanations")
        os.makedirs(processed_explanations_dir, exist_ok=True)
    else:
        moviepy_temp_dir = None

    results = existing_results.copy()  # Start with existing results
    total_dirs = len(theorem_dirs) if theorem_dirs else 1
    processed_count = len(completed_files)

    # Create problem data cache to avoid repeated file loading
    problem_data_cache = {}

    if theorem_dirs:
        print(f"\nProcessing {total_dirs} directories (already completed: {processed_count})")

        # Determine number of parallel workers
        num_workers = args.max_workers
        if num_workers == 0:
            num_workers = cpu_count()

        # Use parallel processing if num_workers > 1
        if num_workers > 1 and len(theorem_dirs) > 1:
            print(f"Using {num_workers} parallel workers for evaluation")

            # Prepare model configurations (can't pickle model objects)
            model_configs = {}
            if 'text' in models:
                model_configs['text'] = args.model_text
            if 'explanation' in models:
                model_configs['explanation'] = args.model_explanation
            if 'image' in models:
                model_configs['image'] = args.model_image
            if 'doc' in models:
                model_configs['doc'] = args.model_doc

            # Prepare arguments for each worker
            worker_args = [
                (theorem_dir, model_configs, args.eval_type, args.retry_limit,
                 args.target_fps, args.use_parent_folder_as_topic, args.output_folder,
                 rubric_path, args.problem_data_path, idx, total_dirs)
                for idx, theorem_dir in enumerate(theorem_dirs, 1)
            ]

            # Run parallel evaluation
            with Pool(processes=num_workers) as pool:
                worker_results = pool.map(evaluate_single_dir_worker, worker_args)

            # Collect results
            for problem_name, file_name, result in worker_results:
                if result is not None and file_name is not None:
                    results[file_name] = result

            # Reload progress to get final state
            completed_files = load_progress(args.output_folder)

        else:
            # Sequential processing (original behavior)
            if num_workers > 1:
                print(f"Note: Parallel processing disabled (only 1 directory to process)")

            for idx, theorem_dir in enumerate(theorem_dirs, 1):
                # Extract problem name for progress tracking
                problem_name = os.path.basename(theorem_dir)

                # Load existing evaluation result for this problem
                existing_result = load_existing_evaluation(args.output_folder, problem_name)
                if existing_result:
                    print(f"  📂 Loaded existing evaluation for {problem_name}")
                else:
                    print(f"  ℹ️  No existing evaluation found for {problem_name}")

                # Check if already completed
                if problem_name in completed_files:
                    print(f"[{idx}/{total_dirs}] Skipping {problem_name} (already completed)")
                    continue

                print(f"[{idx}/{total_dirs}] Evaluating {problem_name}...")

                file_name, result = process_theorem(
                    models,
                    theorem_dir,
                    args.eval_type,
                    args.retry_limit,
                    args.target_fps,
                    args.use_parent_folder_as_topic,
                    args.output_folder,
                    rubric_path,
                    args.problem_data_path,
                    problem_data_cache,
                    existing_result
                )

                if result is not None:
                    results[file_name] = result

                    # Always save individual result immediately for checkpoint
                    save_individual_result(args.output_folder, file_name, result)

                    # Mark as completed and save progress
                    completed_files[problem_name] = True
                    save_progress(args.output_folder, completed_files)

                    print(f"  ✓ Completed and saved: {file_name}")
                else:
                    print(f"  ✗ Skipped: {problem_name}")
    else:
        file_name, result = process_theorem(
            models,
            args.file_path,
            args.eval_type,
            args.retry_limit,
            args.target_fps,
            args.use_parent_folder_as_topic,
            args.output_folder,
            rubric_path,
            args.problem_data_path,
            problem_data_cache
        )

        if result is not None:
            results[file_name] = result

            if not args.combine:
                save_individual_result(args.output_folder, file_name, result)

    if args.combine:
        if len(results) > 1:
            current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
            combined_file = f"evaluation_{current_time}.json"
            combine_results(args.output_folder, combined_file, results)
            print(f"\n✓ Combined {len(results)} results into: {combined_file}")
        else:
            for file_name, result in results.items():
                save_individual_result(args.output_folder, file_name, result)

    # Print summary
    print("\n" + "="*60)
    print("Evaluation Summary")
    print("="*60)
    print(f"Total processed: {len(results)}")
    if theorem_dirs:
        print(f"Total directories: {total_dirs}")
        print(f"Skipped (already done): {processed_count}")
        print(f"Newly evaluated: {len(results) - processed_count}")

    # Check for rendering failures in document evaluation
    if args.eval_type in ['doc', 'all']:
        failed_problems = []
        for file_name, result in results.items():
            if isinstance(result, dict) and result.get('rendering_failed', False):
                failed_problems.append(file_name)

        if failed_problems:
            print("\n" + "-"*60)
            print(f"Rendering Failures: {len(failed_problems)}")
            print("-"*60)
            for problem in failed_problems:
                print(f"  ✗ {problem}")
            print("-"*60)
        else:
            print("\nNo rendering failures detected.")

    print(f"Output folder: {args.output_folder}")
    print("="*60)

    # Clean up temporary directory only if it was created
    if moviepy_temp_dir is not None and os.path.exists(moviepy_temp_dir):
        try:
            os.rmdir(moviepy_temp_dir)
        except:
            pass  # Ignore if directory is not empty


if __name__ == "__main__":
    main()
