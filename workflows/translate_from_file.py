import argparse
import os
from pathlib import Path
import sys
import logging
from datetime import datetime

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from common_utils.file_helpers import sanitize_filename, save_to_file
from common_utils.log_config import setup_task_logger
from format_converters import (
    load_and_merge_srt_segments,
    post_process_translated_segments,
    segments_to_srt_string
)
from llm_utils.translator import execute_translation
from common_utils.json_handler import create_pre_translate_json_objects


def _parse_args():
    """Parses command-line arguments for the file translation workflow."""
    parser = argparse.ArgumentParser(description="Translate an SRT file.")
    parser.add_argument("file_path", help="The path to the SRT file.")
    parser.add_argument("--target_lang", help="Target language for translation.", default="zh-CN")
    parser.add_argument("--output_dir", default="outputs", help="The directory to save the translated files.")
    parser.add_argument("--log_level", help="Set the logging level (e.g., INFO, DEBUG)", default="INFO")
    return parser.parse_args()

def _setup_environment(args):
    """Sets up logging and validates paths."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_path = output_dir / f"translate_file_workflow_{timestamp_str}.log"
    
    numeric_log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logger_name = f"FileTranslationTask.{timestamp_str}"
    task_logger = setup_task_logger(logger_name, log_file_path, level=numeric_log_level)

    file_path = Path(args.file_path)
    if not file_path.is_file():
        task_logger.error(f"Error: File not found at {file_path}")
        return None, None, None

    return file_path, output_dir, task_logger

def _create_pre_translation_json(segments, file_stem, logger):
    """Adapts segment data to the standard rich format for the translator."""
    logger.info("Adapting segment data to the standard rich format for translation.")
    pre_translate_json_objects = create_pre_translate_json_objects(
        processed_segments=segments,
        video_id=file_stem, # Use filename as a unique identifier
        original_lang="unknown", # Source lang is unknown from SRT, can be a param if needed
        source_type="local_srt_file"
    )
    return pre_translate_json_objects

def _generate_final_srt(translated_json_objects, output_dir, file_stem, target_lang, logger):
    """Post-processes translated segments and writes the final SRT file."""
    # The translator returns rich objects. We must prepare them for the legacy post-processing function.
    final_segments_for_processing = []
    for item in translated_json_objects:
        # Reconstruct the object that post_process_translated_segments expects
        segment_data = item['source_data']
        segment_data['translation'] = item['translated_text']
        final_segments_for_processing.append(segment_data)

    logger.info("Post-processing translated segments for optimal formatting...")
    final_segments = post_process_translated_segments(final_segments_for_processing)

    logger.info("Generating SRT content from final segments...")
    translated_srt_content = segments_to_srt_string(final_segments)

    translated_srt_path = output_dir / f"{file_stem}_{target_lang}_translated.srt"
    
    logger.info(f"Saving translated SRT file to: {translated_srt_path}")
    save_to_file(translated_srt_content, translated_srt_path)

    logger.info(f"Translated SRT file saved to: {translated_srt_path}")

def main():
    """
    Main function to run the translation process for a local SRT file.
    """
    args = _parse_args()
    
    file_path, output_dir, task_logger = _setup_environment(args)
    if not file_path:
        return

    task_logger.info(f"--- File Translation workflow started for: {args.file_path} ---")

    # 1. Load and prepare segments from the source SRT file
    prepared_segments = load_and_merge_srt_segments(file_path, logger=task_logger)
    if not prepared_segments:
        return

    # 2. Convert segments to the standard pre-translation format
    pre_translate_json = _create_pre_translation_json(prepared_segments, file_path.stem, logger=task_logger)
    if not pre_translate_json:
        task_logger.error("Failed to create pre-translation data. Aborting.")
        return

    # 3. Run the translation
    task_logger.info(f"Starting translation to target language: {args.target_lang}")
    translated_json = execute_translation(
        pre_translate_json_list=pre_translate_json,
        source_lang_code="auto", # Let the translator know to detect from text
        target_lang=args.target_lang,
        logger=task_logger
    )
    if not translated_json:
        task_logger.error("Translation process failed to return results.")
        return

    # 4. Post-process and generate the final translated SRT file
    _generate_final_srt(translated_json, output_dir, file_path.stem, args.target_lang, logger=task_logger)

    task_logger.info("--- File Translation workflow finished successfully. ---")


if __name__ == "__main__":
    main() 