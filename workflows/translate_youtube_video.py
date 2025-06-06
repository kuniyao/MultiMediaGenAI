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
from format_converters.core import transcript_to_markdown, reconstruct_translated_srt, reconstruct_translated_markdown
from youtube_utils.data_fetcher import get_video_id, get_youtube_video_title, get_youtube_transcript, preprocess_and_merge_segments
from llm_utils.translator import translate_text_segments
from common_utils.json_handler import create_pre_translate_json_objects, save_json_objects_to_jsonl, load_json_objects_from_jsonl

# Placeholder for the YouTube translation workflow

# --- Global Logger for general script messages (console output) ---
global_logger = logging.getLogger("GlobalYoutubeTranslatorWorkflow") # Changed name slightly for clarity
global_logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - WORKFLOW - %(message)s') # Changed format slightly
console_handler.setFormatter(console_formatter)
if not global_logger.handlers:
    global_logger.addHandler(console_handler)
global_logger.propagate = False # Prevent messages from being passed to the root logger
# --- End of Global Logger Setup ---

def main():
    # Determine the script's directory and the desired default output directory
    # In this new structure, __file__ will refer to this workflow script's path.
    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path) # .../workflows
    project_root_dir = os.path.dirname(script_dir) # This should be the project root
    
    # NEW: Define default output directory parallel to the project root
    parent_of_project_root = os.path.dirname(project_root_dir)
    default_parallel_output_folder_name = "GlobalWorkflowOutputs" # You can change this name if needed
    # The new default base directory for all outputs, parallel to the project.
    default_base_output_dir_path = os.path.join(parent_of_project_root, default_parallel_output_folder_name)

    parser = argparse.ArgumentParser(description="Translate YouTube video subtitles.")
    parser.add_argument("video_url_or_id", help="The URL or ID of the YouTube video.")
    parser.add_argument("--output_basename", help="Basename for output files (e.g., 'my_video'). Overrides fetched video title for naming.", default=None)
    parser.add_argument("--target_lang", help="Target language for translation (e.g., 'zh-CN', 'zh-Hans').", default=config.DEFAULT_TARGET_TRANSLATION_LANGUAGE)
    parser.add_argument("--output_dir", 
                        help=f"Base directory for all output. Default: A folder named '{default_parallel_output_folder_name}' located parallel to the project directory (e.g., in '{parent_of_project_root}'). Video-specific subfolders will be created inside this directory.", 
                        default=default_base_output_dir_path)
    parser.add_argument("--log_level", help="Set the logging level for the video-specific log file (DEBUG, INFO, WARNING, ERROR, CRITICAL)", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])

    args = parser.parse_args()
    # It's good practice to load .env from the project root if this script is deep in a subdir.
    # Assuming .env is in project_root_dir for this workflow script.
    dotenv_path = os.path.join(project_root_dir, '.env')
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path=dotenv_path)
    else:
        load_dotenv() # Fallback to default search paths if .env isn't in project root

    # This basicConfig will affect the root logger, sending messages to console.
    # This might be redundant if global_logger is already set up and we don't want root logger interference.
    # For now, keeping it as it was, but consider if it's needed with dedicated global_logger.
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - CONSOLE_ROOT - %(message)s', force=True)

    global_logger.info(f"--- YouTube Translator workflow started for input: {args.video_url_or_id} ---")

    video_id_for_transcript = get_video_id(args.video_url_or_id)
    
    # The first call to get_youtube_video_title uses its own module logger if logger is None (as modified).
    # For initial user feedback, we can use global_logger here if desired, or rely on its internal logging.
    video_title = get_youtube_video_title(args.video_url_or_id, logger=global_logger) 
    sanitized_title = sanitize_filename(video_title)

    specific_output_dir_name = sanitized_title
    if video_title == video_id_for_transcript: 
        global_logger.warning(f"Could not fetch a distinct video title; using video ID '{video_id_for_transcript}' for directory and filenames.")

    file_basename_prefix = sanitize_filename(args.output_basename) if args.output_basename else specific_output_dir_name

    video_output_path = os.path.join(args.output_dir, specific_output_dir_name)
    try:
        os.makedirs(video_output_path, exist_ok=True)
        global_logger.info(f"Video-specific output directory: {video_output_path}")
    except OSError as e_mkdir:
        global_logger.critical(f"CRITICAL: Could not create video-specific output directory: {video_output_path}. Error: {e_mkdir}", exc_info=True)
        return 

    log_file_name_base = sanitized_title if sanitized_title and sanitized_title != video_id_for_transcript else video_id_for_transcript
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_name = f"{sanitize_filename(log_file_name_base)}_{timestamp_str}.log"
    log_file_full_path = os.path.join(video_output_path, log_file_name)

    numeric_log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    task_logger_name = f"VideoTaskWorkflow.{sanitize_filename(log_file_name_base)}.{timestamp_str}"
    task_logger = setup_task_logger(task_logger_name, log_file_full_path, level=numeric_log_level)
    
    task_logger.info(f"Task-specific logger initialized. Logging to file: {log_file_full_path}")
    task_logger.info(f"Processing Video URL: {args.video_url_or_id}")
    task_logger.info(f"Video ID for transcript: {video_id_for_transcript}")
    task_logger.info(f"Fetched video title (used for naming): '{video_title}'")
    task_logger.info(f"Target language for translation: {args.target_lang}")
    task_logger.info(f"Output files will be prefixed with: '{file_basename_prefix}'")
    
    raw_transcript_data, lang_code, source_type = get_youtube_transcript(video_id_for_transcript, logger=task_logger)

    if not raw_transcript_data:
        task_logger.error("Could not retrieve transcript. Exiting process for this video.")
        global_logger.error(f"Failed to retrieve transcript for {video_id_for_transcript}.") # Also inform global/console
        return
    global_logger.info(f"Successfully fetched {source_type} transcript in '{lang_code}'.")
    
    merged_transcript_data = preprocess_and_merge_segments(raw_transcript_data, logger=task_logger)

    if not merged_transcript_data:
        task_logger.error("Transcript data is empty after preprocessing and merging. Exiting process for this video.")
        global_logger.error(f"Preprocessing of transcript for {video_id_for_transcript} resulted in empty data.")
        return
    global_logger.info(f"Preprocessing complete. Merged into {len(merged_transcript_data)} segments.")
    transcript_data_for_processing = merged_transcript_data
    
    original_md_filename = os.path.join(video_output_path, f"{file_basename_prefix}_original_merged_{lang_code}.md")
    original_md = transcript_to_markdown(transcript_data_for_processing, lang_code, source_type, video_id_for_transcript, logger=task_logger)
    save_to_file(original_md, original_md_filename, logger=task_logger)
    
    # --- Create and Save Pre-Translate JSONL --- 
    task_logger.info("Creating JSON objects for pre-translation anrichment and LLM input...")
    pre_translate_json_objects = create_pre_translate_json_objects(
        processed_segments=transcript_data_for_processing, # This is merged_transcript_data
        video_id=video_id_for_transcript,
        original_lang=lang_code,
        source_type=source_type,
        logger=task_logger
    )

    if not pre_translate_json_objects:
        task_logger.error("No JSON objects were created for pre-translation. Skipping translation.")
        global_logger.error(f"Failed to create pre-translation JSON for {video_id_for_transcript}.")
        return

    pre_translate_jsonl_filename = os.path.join(video_output_path, f"{file_basename_prefix}_pre_translate_{lang_code}.jsonl")
    if save_json_objects_to_jsonl(pre_translate_json_objects, pre_translate_jsonl_filename, logger=task_logger):
        task_logger.info(f"Successfully saved pre-translate JSON objects to: {pre_translate_jsonl_filename}")
        global_logger.info(f"Pre-translation JSONL file saved: {pre_translate_jsonl_filename}")
    else:
        task_logger.error(f"Failed to save pre-translate JSON objects to: {pre_translate_jsonl_filename}. Proceeding with in-memory data for translation if available, but this indicates an issue.")
        # Depending on strictness, you might choose to return here if saving fails.
    
    global_logger.info(f"Starting translation from '{lang_code}' to '{args.target_lang}'...")
    # IMPORTANT: The first argument to translate_text_segments is now pre_translate_json_objects.
    # The translate_text_segments function itself will need to be updated in the next step
    # to correctly process this new list of rich JSON objects.
    translated_json_objects = translate_text_segments(
        pre_translate_json_objects, # CHANGED: Passing the list of rich JSON objects
        lang_code,                      
        args.target_lang,
        video_output_path, 
        logger=task_logger
    )

    if not translated_json_objects :
        task_logger.error("Translation failed or returned no segments. Exiting process for this video.")
        global_logger.error(f"Translation failed for {video_id_for_transcript}.")
        return
    global_logger.info("Translation processing complete.")

    # --- (Optional) Save Post-Translate JSONL --- 
    post_translate_jsonl_filename = os.path.join(video_output_path, f"{file_basename_prefix}_post_translate_{args.target_lang}.jsonl")
    if save_json_objects_to_jsonl(translated_json_objects, post_translate_jsonl_filename, logger=task_logger):
        task_logger.info(f"Successfully saved post-translate JSON objects to: {post_translate_jsonl_filename}")
        global_logger.info(f"Post-translation JSONL file saved: {post_translate_jsonl_filename}")
    else:
        task_logger.warning(f"Failed to save post-translate JSON objects to: {post_translate_jsonl_filename}. This is not critical for SRT/MD generation if data is in memory.")

    # Check if the number of translated segments matches the number of input segments
    # The pre_translate_json_objects is the list that went into the translator (after filtering valid items within translator)
    # The llm_utils.translator now internally creates llm_input_segments, so we compare against the final output of that.
    # For simplicity, we are comparing the length of the final list from the translator with the initial list fed to it.
    if len(translated_json_objects) != len(pre_translate_json_objects):
         task_logger.warning(f"Number of translated JSON objects ({len(translated_json_objects)}) does not match original pre-translate JSON objects ({len(pre_translate_json_objects)}). Results might be incomplete or misaligned.")

    # IMPORTANT: The following reconstruct functions will be updated in the next step
    # to correctly process translated_json_objects (list of rich JSON objects).
    translated_md_filename = os.path.join(video_output_path, f"{file_basename_prefix}_translated_{args.target_lang}.md")
    translated_md_content = reconstruct_translated_markdown(
        translated_json_objects, # CHANGED: Passing list of rich JSON objects
        lang_code, # original_lang still needed for header
        source_type, # source_type still needed for header
        args.target_lang, 
        video_id_for_transcript, 
        logger=task_logger
    )
    save_to_file(translated_md_content, translated_md_filename, logger=task_logger)

    translated_srt_filename = os.path.join(video_output_path, f"{file_basename_prefix}_translated_{args.target_lang}.srt")
    translated_srt_content = reconstruct_translated_srt(
        translated_json_objects, # CHANGED: Passing list of rich JSON objects
        logger=task_logger
    )
    save_to_file(translated_srt_content, translated_srt_filename, logger=task_logger)

    task_logger.info("All tasks completed for this video!")
    global_logger.info(f"--- YouTube Translator workflow finished for input: {args.video_url_or_id} ---")
    
    print("\nAll tasks completed!")
    print(f"Original transcript (MD): {original_md_filename}")
    print(f"Translated transcript (MD): {translated_md_filename}")
    print(f"Translated transcript (SRT): {translated_srt_filename}")
    if os.path.exists(pre_translate_jsonl_filename):
        print(f"Pre-translation data (JSONL): {pre_translate_jsonl_filename}")
    if os.path.exists(post_translate_jsonl_filename):
        print(f"Post-translation data (JSONL): {post_translate_jsonl_filename}")
    raw_llm_log_expected_filename = os.path.join(video_output_path, f"llm_raw_responses_{args.target_lang.lower().replace('-', '_')}.jsonl")
    if os.path.exists(raw_llm_log_expected_filename):
        print(f"Raw LLM responses log: {raw_llm_log_expected_filename}")
    if log_file_full_path and os.path.exists(log_file_full_path):
        print(f"Video processing log: {log_file_full_path}")

if __name__ == "__main__":
    main() 