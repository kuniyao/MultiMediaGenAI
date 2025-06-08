# Placeholder for the YouTube translation workflow 

import argparse
import os
import logging
import logging.handlers
from datetime import datetime
from dotenv import load_dotenv
import sys # Add sys

# Determine project root and add to sys.path
# In this new structure, __file__ will refer to this workflow script's path.
script_path = os.path.abspath(__file__)
script_dir = os.path.dirname(script_path) # .../workflows
project_root_dir = os.path.dirname(script_dir) # This should be the project root
if project_root_dir not in sys.path:
    sys.path.insert(0, project_root_dir)

# Now, imports that rely on the project root being in sys.path should work
import config # Assuming config.py is in the project root or PYTHONPATH

# Import functions from our new modules
from common_utils.file_helpers import sanitize_filename, save_to_file
from common_utils.log_config import setup_task_logger
from format_converters import (
    transcript_to_markdown, 
    segments_to_srt_string,
    reconstruct_translated_markdown
)
from youtube_utils.data_fetcher import get_video_id, get_youtube_video_title, fetch_and_prepare_transcript
from llm_utils.translator import execute_translation
from common_utils.json_handler import create_pre_translate_json_objects, save_json_objects_to_jsonl, load_json_objects_from_jsonl

# Placeholder for the YouTube translation workflow

# --- Global Logger for general script messages (console output) ---
# This logger is now removed. All logging will be handled by the task_logger.
# --- End of Global Logger Setup ---

def _parse_args():
    """Parses command-line arguments for the YouTube translation workflow."""
    # Determine the script's directory and the desired default output directory
    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path) # .../workflows
    project_root_dir = os.path.dirname(script_dir) # This should be the project root
    
    parent_of_project_root = os.path.dirname(project_root_dir)
    default_parallel_output_folder_name = "GlobalWorkflowOutputs"
    default_base_output_dir_path = os.path.join(parent_of_project_root, default_parallel_output_folder_name)

    parser = argparse.ArgumentParser(description="Translate YouTube video subtitles.")
    parser.add_argument("video_url_or_id", help="The URL or ID of the YouTube video.")
    parser.add_argument("--output_basename", help="Basename for output files (e.g., 'my_video'). Overrides fetched video title for naming.", default=None)
    parser.add_argument("--target_lang", help="Target language for translation (e.g., 'zh-CN', 'zh-Hans').", default=config.DEFAULT_TARGET_TRANSLATION_LANGUAGE)
    parser.add_argument("--output_dir", 
                        help=f"Base directory for all output. Default: A folder named '{default_parallel_output_folder_name}' located parallel to the project directory (e.g., in '{parent_of_project_root}'). Video-specific subfolders will be created inside this directory.", 
                        default=default_base_output_dir_path)
    parser.add_argument("--log_level", help="Set the logging level for the video-specific log file (DEBUG, INFO, WARNING, ERROR, CRITICAL)", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])

    return parser.parse_args()

def _setup_environment_and_logging(args):
    """Sets up the environment, including directories, logging, and initial variables."""
    # Load .env file from project root
    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path)
    project_root_dir = os.path.dirname(script_dir)
    dotenv_path = os.path.join(project_root_dir, '.env')
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path=dotenv_path)
    else:
        load_dotenv() # Fallback to default search paths

    # --- Video and Path Setup ---
    video_id = get_video_id(args.video_url_or_id)
    video_title = get_youtube_video_title(args.video_url_or_id, logger=None) # Initial fetch without logger
    
    sanitized_title = sanitize_filename(video_title)
    specific_output_dir_name = sanitized_title if sanitized_title != video_id else video_id
    
    video_output_path = os.path.join(args.output_dir, specific_output_dir_name)
    os.makedirs(video_output_path, exist_ok=True)

    # --- Logger Setup ---
    log_file_name_base = sanitized_title if sanitized_title and sanitized_title != video_id else video_id
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_name = f"{sanitize_filename(log_file_name_base)}_{timestamp_str}.log"
    log_file_full_path = os.path.join(video_output_path, log_file_name)

    numeric_log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    task_logger_name = f"VideoTaskWorkflow.{sanitize_filename(log_file_name_base)}.{timestamp_str}"
    task_logger = setup_task_logger(task_logger_name, log_file_full_path, level=numeric_log_level)
    
    task_logger.info(f"Video-specific output directory created: {video_output_path}")
    task_logger.info(f"Task-specific logger initialized. Logging to file: {log_file_full_path}")
    
    # --- Filename Basename ---
    if video_title == video_id: 
        task_logger.warning(f"Could not fetch a distinct video title; using video ID '{video_id}' for directory and filenames.")
    
    file_basename_prefix = sanitize_filename(args.output_basename) if args.output_basename else specific_output_dir_name

    task_logger.info(f"Processing Video URL: {args.video_url_or_id}")
    task_logger.info(f"Video ID for transcript: {video_id}")
    task_logger.info(f"Fetched video title (used for naming): '{video_title}'")
    task_logger.info(f"Target language for translation: {args.target_lang}")
    task_logger.info(f"Output files will be prefixed with: '{file_basename_prefix}'")
    
    return {
        "task_logger": task_logger,
        "video_output_path": video_output_path,
        "file_basename_prefix": file_basename_prefix,
        "video_id": video_id,
        "video_title": video_title
    }

def _create_pre_translation_artifacts(transcript_data, lang_code, source_type, video_id, video_output_path, file_basename_prefix, logger):
    """Creates and saves artifacts required before translation, like original markdown and pre-translation JSONL."""
    # Save original transcript as Markdown
    original_md_filename = os.path.join(video_output_path, f"{file_basename_prefix}_original_merged_{lang_code}.md")
    original_md = transcript_to_markdown(transcript_data, lang_code, source_type, video_id, logger=logger)
    save_to_file(original_md, original_md_filename, logger=logger)
    
    # Create and Save Pre-Translate JSONL
    logger.info("Creating JSON objects for pre-translation enrichment and LLM input...")
    pre_translate_json_objects = create_pre_translate_json_objects(
        processed_segments=transcript_data,
        video_id=video_id,
        original_lang=lang_code,
        source_type=source_type,
        logger=logger
    )

    if not pre_translate_json_objects:
        logger.error("No JSON objects were created for pre-translation. Skipping translation.")
        return None

    pre_translate_jsonl_filename = os.path.join(video_output_path, f"{file_basename_prefix}_pre_translate_{lang_code}.jsonl")
    if not save_json_objects_to_jsonl(pre_translate_json_objects, pre_translate_jsonl_filename, logger=logger):
        logger.error(f"Failed to save pre-translate JSON objects to: {pre_translate_jsonl_filename}. Proceeding with in-memory data, but this may indicate a file system issue.")
    
    return pre_translate_json_objects

def _generate_output_files(translated_json_objects, target_lang, lang_code, source_type, video_id, video_output_path, file_basename_prefix, logger):
    """Generates and saves the final output files (SRT, Markdown)."""
    # (Optional) Save Post-Translate JSONL
    post_translate_jsonl_filename = os.path.join(video_output_path, f"{file_basename_prefix}_post_translate_{target_lang}.jsonl")
    if not save_json_objects_to_jsonl(translated_json_objects, post_translate_jsonl_filename, logger=logger):
        logger.warning(f"Failed to save post-translate JSON objects to: {post_translate_jsonl_filename}. This is not critical for SRT/MD generation if data is in memory.")

    # Generate translated Markdown
    translated_md_filename = os.path.join(video_output_path, f"{file_basename_prefix}_translated_{target_lang}.md")
    translated_md_content = reconstruct_translated_markdown(
        translated_json_objects,
        lang_code,
        source_type,
        target_lang,
        video_id,
        logger=logger
    )
    save_to_file(translated_md_content, translated_md_filename, logger=logger)

    # Generate translated SRT
    logger.info("Preparing segments for SRT generation...")
    segments_for_srt = []
    for item in translated_json_objects:
        try:
            start_time = item['source_data']['start_seconds']
            end_time = start_time + item['source_data']['duration_seconds']
            segments_for_srt.append({
                'start': start_time,
                'end': end_time,
                'translation': item['translated_text']
            })
        except KeyError as e:
            logger.error(f"Skipping SRT segment due to missing key {e} in item: {item}")
            continue

    translated_srt_filename = os.path.join(video_output_path, f"{file_basename_prefix}_translated_{target_lang}.srt")
    translated_srt_content = segments_to_srt_string(segments_for_srt)
    save_to_file(translated_srt_content, translated_srt_filename, logger=logger)

def _log_summary(video_output_path, file_basename_prefix, lang_code, target_lang, logger):
    """Logs a summary of all generated output files."""
    original_md_filename = os.path.join(video_output_path, f"{file_basename_prefix}_original_merged_{lang_code}.md")
    translated_md_filename = os.path.join(video_output_path, f"{file_basename_prefix}_translated_{target_lang}.md")
    translated_srt_filename = os.path.join(video_output_path, f"{file_basename_prefix}_translated_{target_lang}.srt")
    pre_translate_jsonl_filename = os.path.join(video_output_path, f"{file_basename_prefix}_pre_translate_{lang_code}.jsonl")
    post_translate_jsonl_filename = os.path.join(video_output_path, f"{file_basename_prefix}_post_translate_{target_lang}.jsonl")
    raw_llm_log_expected_filename = os.path.join(video_output_path, f"llm_raw_responses_{target_lang.lower().replace('-', '_')}.jsonl")
    
    # We need to find the actual log file path from the logger's handlers
    log_file_full_path = None
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            log_file_full_path = handler.baseFilename
            break

    logger.info("\n--- Summary of Output Files ---")
    if os.path.exists(original_md_filename):
        logger.info(f"Original transcript (MD): {original_md_filename}")
    if os.path.exists(translated_md_filename):
        logger.info(f"Translated transcript (MD): {translated_md_filename}")
    if os.path.exists(translated_srt_filename):
        logger.info(f"Translated transcript (SRT): {translated_srt_filename}")
    if os.path.exists(pre_translate_jsonl_filename):
        logger.info(f"Pre-translation data (JSONL): {pre_translate_jsonl_filename}")
    if os.path.exists(post_translate_jsonl_filename):
        logger.info(f"Post-translation data (JSONL): {post_translate_jsonl_filename}")
    if os.path.exists(raw_llm_log_expected_filename):
        logger.info(f"Raw LLM responses log: {raw_llm_log_expected_filename}")
    if log_file_full_path and os.path.exists(log_file_full_path):
        logger.info(f"Video processing log: {log_file_full_path}")


def main():
    """Main function to orchestrate the YouTube video translation workflow."""
    args = _parse_args()
    
    # Setup environment and get a logger. A dictionary is used for the results
    # to avoid a long list of return values and to make the code more readable.
    setup_results = _setup_environment_and_logging(args)
    task_logger = setup_results["task_logger"]
    
    try:
        task_logger.info(f"--- YouTube Translator workflow started for input: {args.video_url_or_id} ---")
        
        # 1. Fetch and process transcript
        merged_transcript_data, lang_code, source_type = fetch_and_prepare_transcript(
            video_id=setup_results['video_id'],
            logger=task_logger
        )
        if not merged_transcript_data:
            task_logger.error("Workflow terminated due to failure in transcript processing.")
            return

        # 2. Create pre-translation artifacts (original MD, pre-translate JSONL)
        pre_translate_json_objects = _create_pre_translation_artifacts(
            transcript_data=merged_transcript_data,
            lang_code=lang_code,
            source_type=source_type,
            video_id=setup_results['video_id'],
            video_output_path=setup_results['video_output_path'],
            file_basename_prefix=setup_results['file_basename_prefix'],
            logger=task_logger
        )
        if not pre_translate_json_objects:
            task_logger.error("Workflow terminated due to failure in pre-translation artifact creation.")
            return

        # 3. Run translation
        translated_json_objects = execute_translation(
            pre_translate_json_list=pre_translate_json_objects,
            source_lang_code=lang_code,
            target_lang=args.target_lang,
            video_specific_output_path=setup_results['video_output_path'],
            logger=task_logger
        )
        if not translated_json_objects:
            task_logger.error("Workflow terminated due to translation failure.")
            return

        # 4. Generate output files (translated MD, translated SRT, post-translate JSONL)
        _generate_output_files(
            translated_json_objects=translated_json_objects,
            target_lang=args.target_lang,
            lang_code=lang_code,
            source_type=source_type,
            video_id=setup_results['video_id'],
            video_output_path=setup_results['video_output_path'],
            file_basename_prefix=setup_results['file_basename_prefix'],
            logger=task_logger
        )

        # 5. Log summary of generated files
        _log_summary(
            video_output_path=setup_results['video_output_path'],
            file_basename_prefix=setup_results['file_basename_prefix'],
            lang_code=lang_code,
            target_lang=args.target_lang,
            logger=task_logger
        )

        task_logger.info("All tasks completed for this video!")
        task_logger.info(f"--- YouTube Translator workflow finished for input: {args.video_url_or_id} ---")

    except Exception as e:
        # A broad exception handler to log any unexpected errors during the workflow.
        task_logger.critical(f"An unexpected error terminated the workflow: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main() 