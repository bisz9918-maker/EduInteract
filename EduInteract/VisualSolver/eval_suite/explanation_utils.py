import os
import cv2
import tempfile

from dotenv import load_dotenv

from visual_solver.mllm_tools.utils import _prepare_text_explanation_inputs
from eval_suite.prompts_raw import _explanation_eval_new
from eval_suite.utils import extract_json, convert_score_fields

load_dotenv()


def reduce_explanation_framerate(input_path, target_fps=1, output_path=None):
    """
    Reduces the frame rate of a explanation by only keeping frames at the target interval.
    
    Args:
        input_path (str): Path to the input explanation
        target_fps (int): Target frames per second (default: 1)
        output_path (str, optional): Path to save the processed explanation. If None, uses a temporary file.
    
    Returns:
        str: Path to the processed explanation
        
    Raises:
        ValueError: If input explanation cannot be opened or has invalid FPS
        RuntimeError: If explanation writer initialization fails or output explanation creation fails
    """
    cap = cv2.ExplanationCapture(input_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open input explanation: {input_path}")
        
    original_fps = cap.get(cv2.CAP_PROP_FPS)
    if original_fps <= 0:
        raise ValueError(f"Invalid FPS ({original_fps}) detected in input explanation")
        
    frame_interval = int(original_fps / target_fps)
    
    # Get explanation properties
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # Use provided output path or create temporary file
    if output_path is None:
        temp_output = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
        output_path = temp_output.name
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Try different codecs in order of preference
    codecs = [
        ('avc1', '.mp4'),  # H.264 codec
        ('mp4v', '.mp4'),  # MP4V codec
        ('XVID', '.avi'),  # XVID codec
        ('MJPG', '.avi'),  # Motion JPEG codec
    ]
    
    success = False
    for codec, ext in codecs:
        if output_path.endswith('.mp4') and not ext.endswith('.mp4'):
            # If we're switching to AVI format, change the extension
            output_path = output_path[:-4] + ext
            
        fourcc = cv2.ExplanationWriter_fourcc(*codec)
        out = cv2.ExplanationWriter(output_path, fourcc, target_fps, (width, height))
        
        if out.isOpened():
            success = True
            print(f"Successfully initialized explanation writer with codec: {codec}")
            break
        else:
            out.release()
            if os.path.exists(output_path):
                os.remove(output_path)
    
    if not success:
        raise RuntimeError("Could not initialize explanation writer with any available codec")
    
    frame_count = 0
    frames_written = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
            
        # Only write frames at the specified interval
        if frame_count % frame_interval == 0:
            out.write(frame)
            frames_written += 1
        frame_count += 1
    
    cap.release()
    out.release()
    
    # Verify the output
    verify_cap = cv2.ExplanationCapture(output_path)
    if not verify_cap.isOpened():
        raise RuntimeError(f"Failed to create output explanation at {output_path}")
        
    actual_fps = verify_cap.get(cv2.CAP_PROP_FPS)
    total_frames = verify_cap.get(cv2.CAP_PROP_FRAME_COUNT)
    verify_cap.release()
    
    if actual_fps <= 0:
        print("Warning: Output explanation reports invalid FPS. This might be a codec issue.")
        actual_fps = target_fps  # Use target FPS for duration calculation
    
    print(f"Created explanation with {frames_written} frames at {actual_fps} FPS")
    print(f"Total duration: {total_frames/actual_fps:.2f} seconds")
    print(f"Explanation saved to: {output_path}")
    
    return output_path


def evaluate_explanation_chunk_new(model, explanation_path, transcript="No transcript provided", description="No description provided", 
                             save_processed_explanation=None, target_fps=None, retry_limit=5):
    """
    Evaluate a single explanation chunk using a multimodal model.

    Args:
        model: The multimodal model to use for evaluation
        explanation_path (str): Path to the explanation file to evaluate
        transcript (str, optional): Explanation transcript text. Defaults to "No transcript provided"
        description (str, optional): Explanation description text. Defaults to "No description provided"
        save_processed_explanation (str, optional): Path to save processed explanation. If None, uses temporary file
        target_fps (int, optional): Target frames per second for explanation processing. If None, no processing
        retry_limit (int, optional): Maximum number of retry attempts. Defaults to 5

    Returns:
        dict: Evaluation results as a JSON object with scores converted to integers

    Raises:
        FileNotFoundError: If explanation file does not exist
        Exception: If evaluation fails after all retry attempts
    """
    if not os.path.exists(explanation_path):
        raise FileNotFoundError(f"Explanation file not found: {explanation_path}")
    
    # Only process explanation if target_fps is specified
    if target_fps is not None:
        processed_explanation_path = reduce_explanation_framerate(explanation_path, target_fps=target_fps, output_path=save_processed_explanation)
        explanation_to_use = processed_explanation_path
    else:
        explanation_to_use = explanation_path

    prompt = _explanation_eval_new.format(description=description)
    inputs = _prepare_text_explanation_inputs(prompt, explanation_to_use)

    try:
        for attempt in range(retry_limit):
            try:
                response = model(inputs)
                response_json = extract_json(response)
                response_json = convert_score_fields(response_json)

                return response_json
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt + 1 == retry_limit:
                    print("Reached maximum retry limit. Evaluation failed.")
                    raise
    finally:
        # Clean up the temporary processed explanation if we created one
        if target_fps is not None and save_processed_explanation is None and os.path.exists(processed_explanation_path):
            os.unlink(processed_explanation_path)