import argparse
import os
from pathlib import Path
import sys
import logging

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from common_utils.file_helpers import sanitize_filename
from format_converters import (
    merge_consecutive_segments, 
    srt_to_segments, 
    post_process_translated_segments,
    reconstruct_translated_srt,
    write_srt_file
)
from llm_utils.translator import execute_translation
from common_utils.json_handler import create_pre_translate_json_objects


def _parse_args():
    """Parses command-line arguments for the file translation workflow."""
    parser = argparse.ArgumentParser(description="Translate an SRT file.")
    parser.add_argument("file_path", help="The path to the SRT file.")
    parser.add_argument("--target_lang", help="Target language for translation.", default="zh-CN")
    parser.add_argument("--output_dir", default="outputs", help="The directory to save the translated files.")
    return parser.parse_args()

def _setup_environment(args):
    """Sets up logging and validates paths."""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    file_path = Path(args.file_path)
    if not file_path.is_file():
        logging.error(f"Error: File not found at {file_path}")
        return None, None

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    return file_path, output_dir

def _load_and_prepare_segments(file_path):
    """Loads segments from an SRT file and merges them for better translation context."""
    logging.info(f"Reading and formatting SRT file: {file_path}")
    raw_subtitle_segments = srt_to_segments(file_path)
    if not raw_subtitle_segments:
        logging.error("No segments found in the SRT file. Aborting.")
        return None
        
    logging.info(f"Loaded {len(raw_subtitle_segments)} raw segments from SRT file.")

    # Merge subtitles for better translation context
    formatted_subtitles, _ = merge_consecutive_segments(raw_subtitle_segments)
    logging.info(f"Merged into {len(formatted_subtitles)} segments for translation.")
    return formatted_subtitles

def _create_pre_translation_json(segments, file_stem):
    """Adapts segment data to the standard rich format for the translator."""
    logging.info("Adapting segment data to the standard rich format for translation.")
    pre_translate_json_objects = create_pre_translate_json_objects(
        processed_segments=segments,
        video_id=file_stem, # Use filename as a unique identifier
        original_lang="unknown", # Source lang is unknown from SRT, can be a param if needed
        source_type="local_srt_file"
    )
    return pre_translate_json_objects

def _generate_final_srt(translated_json_objects, output_dir, file_stem, target_lang):
    """Post-processes translated segments and writes the final SRT file."""
    # The translator returns rich objects. We must prepare them for the legacy post-processing function.
    final_segments_for_processing = []
    for item in translated_json_objects:
        # Reconstruct the object that post_process_translated_segments expects
        segment_data = item['source_data']
        segment_data['translation'] = item['translated_text']
        final_segments_for_processing.append(segment_data)

    logging.info("Post-processing translated segments for optimal formatting...")
    final_segments = post_process_translated_segments(final_segments_for_processing)

    translated_srt_path = output_dir / f"{file_stem}_{target_lang}_translated.srt"
    write_srt_file(final_segments, translated_srt_path)

    logging.info(f"Translated SRT file saved to: {translated_srt_path}")

def main():
    """
    Main function to run the translation process for a local SRT file.
    """
    args = _parse_args()
    
    file_path, output_dir = _setup_environment(args)
    if not file_path:
        return

    # 1. Load and prepare segments from the source SRT file
    prepared_segments = _load_and_prepare_segments(file_path)
    if not prepared_segments:
        return

    # 2. Convert segments to the standard pre-translation format
    pre_translate_json = _create_pre_translation_json(prepared_segments, file_path.stem)
    if not pre_translate_json:
        logging.error("Failed to create pre-translation data. Aborting.")
        return

    # 3. Run the translation
    translated_json = execute_translation(
        pre_translate_json_list=pre_translate_json,
        source_lang_code="auto", # Let the translator know to detect from text
        target_lang=args.target_lang,
        logger=logging
    )
    if not translated_json:
        return

    # 4. Post-process and generate the final translated SRT file
    _generate_final_srt(translated_json, output_dir, file_path.stem, args.target_lang)


if __name__ == "__main__":
    main() 