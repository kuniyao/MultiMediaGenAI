import argparse
import os
from pathlib import Path
import sys
import logging
from datetime import datetime
import asyncio
import json

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import config
from common_utils.file_helpers import sanitize_filename, save_to_file
from common_utils.log_config import setup_task_logger
from format_converters import (
    load_and_merge_srt_segments,
    generate_post_processed_srt
)
from format_converters.book_schema import SubtitleTrack, SubtitleSegment
from llm_utils.translator import execute_translation_async
from llm_utils.subtitle_processor import subtitle_track_to_html_tasks, update_track_from_html_response


def _parse_args():
    """Parses command-line arguments for the file translation workflow."""
    parser = argparse.ArgumentParser(description="Translate an SRT file.")
    parser.add_argument("file_path", help="The path to the SRT file.")
    parser.add_argument("--target_lang", help="Target language for translation.", default=config.DEFAULT_TARGET_TRANSLATION_LANGUAGE)
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
        return None, output_dir, task_logger

    return file_path, output_dir, task_logger

def _generate_final_srt(translated_track: SubtitleTrack, output_dir: Path, file_stem: str, target_lang: str, logger):
    """Generates and saves the final, post-processed SRT file from a SubtitleTrack."""
    # The centralized function now takes the SubtitleTrack object directly
    translated_srt_content = generate_post_processed_srt(
        subtitle_track=translated_track, 
        logger=logger
    )

    translated_srt_path = output_dir / f"{file_stem}_{target_lang}_translated.srt"
    
    logger.info(f"Saving translated SRT file to: {translated_srt_path}")
    save_to_file(translated_srt_content, translated_srt_path, logger=logger)

    logger.info(f"Translated SRT file saved to: {translated_srt_path}")

async def main():
    """
    Main async function to run the translation process for a local SRT file.
    """
    args = _parse_args()
    
    file_path, output_dir, task_logger = _setup_environment(args)
    if not file_path:
        return

    prompts = {}
    try:
        prompts_path = project_root / 'prompts.json'
        with open(prompts_path, 'r', encoding='utf-8') as f:
            prompts = json.load(f)
        task_logger.info(f"Successfully loaded prompts from {prompts_path}")
    except Exception as e:
        task_logger.error(f"FATAL: Failed to load or parse prompts.json: {e}", exc_info=True)
        return

    task_logger.info(f"--- File Translation workflow started for: {args.file_path} ---")

    # 1. Load and merge segments from the source SRT file
    prepared_segments = load_and_merge_srt_segments(file_path, logger=task_logger)
    if not prepared_segments:
        return

    # 2. Build the SubtitleTrack data object
    task_logger.info("Creating SubtitleTrack data model...")
    subtitle_track = SubtitleTrack(
        video_id=file_path.stem, # Use file stem as a unique identifier
        source_lang="auto", # Language will be detected by the translator
        source_type="local_srt_file"
    )
    for i, seg_data in enumerate(prepared_segments):
        subtitle_track.segments.append(
            SubtitleSegment(
                id=f"seg_{i:04d}",
                start=seg_data['start'],
                end=seg_data.get('end', seg_data['start'] + seg_data.get('duration', 0)),
                source_text=seg_data['text']
            )
        )
    task_logger.info(f"Successfully created SubtitleTrack with {len(subtitle_track.segments)} segments.")

    # 3. Create batched HTML tasks for the translator
    tasks_to_translate = subtitle_track_to_html_tasks(subtitle_track, logger=task_logger)
    
    # 4. Run the translation using the async executor
    task_logger.info(f"Starting translation to target language: {args.target_lang}")
    translation_results = await execute_translation_async(
        tasks_to_translate=tasks_to_translate,
        source_lang_code="auto", # Let the translator know to detect from text
        target_lang=args.target_lang,
        video_specific_output_path=str(output_dir), # For raw LLM response logs
        logger=task_logger,
        prompts=prompts
    )
    if not translation_results:
        task_logger.error("Translation process failed to return results.")
        return

    # 5. Apply results back to the SubtitleTrack object
    task_logger.info("Parsing all HTML batches from LLM response and updating subtitle track...")
    total_updated_count = 0
    for result in translation_results:
        translated_html = result.get("translated_text")
        task_id = result.get("llm_processing_id")
        if not translated_html:
            task_logger.warning(f"Translation result batch {task_id} is missing 'translated_text', skipping.")
            continue
        updated_in_batch = update_track_from_html_response(
            track=subtitle_track,
            translated_html=translated_html,
            logger=task_logger
        )
        total_updated_count += updated_in_batch
    
    final_segment_count = len(subtitle_track.segments)
    if total_updated_count != final_segment_count:
         task_logger.warning(f"Final updated segment count ({total_updated_count}) does not match original segment count ({final_segment_count}).")
    else:
         task_logger.info(f"Successfully updated all {total_updated_count}/{final_segment_count} segments.")

    # 6. Post-process and generate the final translated SRT file
    _generate_final_srt(subtitle_track, output_dir, file_path.stem, args.target_lang, logger=task_logger)

    task_logger.info("--- File Translation workflow finished successfully. ---")


if __name__ == "__main__":
    asyncio.run(main()) 