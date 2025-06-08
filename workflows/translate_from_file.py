import argparse
import os
from pathlib import Path
import sys
import logging

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from common_utils.file_helpers import write_srt_file
from format_converters.core import format_subtitles, srt_to_segments, post_process_segments
from llm_utils.translator import Translator
from common_utils.json_handler import create_pre_translate_json_objects


def main():
    """
    Main function to run the translation process for a local SRT file.
    """
    parser = argparse.ArgumentParser(description="Translate an SRT file.")
    parser.add_argument("file_path", help="The path to the SRT file.")
    parser.add_argument("--target_lang", help="Target language for translation.", default="zh-CN")
    parser.add_argument("--output_dir", default="outputs", help="The directory to save the translated files.")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    file_path = Path(args.file_path)
    if not file_path.is_file():
        logging.error(f"Error: File not found at {file_path}")
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Parse SRT file and format subtitles
    logging.info(f"Reading and formatting SRT file: {file_path}")
    raw_subtitle_segments = srt_to_segments(file_path)
    if not raw_subtitle_segments:
        logging.error("No segments found in the SRT file. Aborting.")
        return
        
    formatted_subtitles, _ = format_subtitles(raw_subtitle_segments)
    logging.info(f"Found {len(formatted_subtitles)} segments to translate after formatting.")

    # 2. NEW: Adapt data to the standard "rich format" for the translator
    logging.info("Adapting segment data to the standard rich format for translation.")
    pre_translate_json_objects = create_pre_translate_json_objects(
        processed_segments=formatted_subtitles,
        video_id=file_path.stem, # Use filename as a unique identifier
        original_lang="unknown", # Source lang is unknown from SRT, can be a param if needed
        source_type="local_srt_file"
    )

    # 3. UPDATED: Translate using the unified Translator
    logging.info(f"Initializing translator and starting translation to '{args.target_lang}'...")
    translator = Translator(logger=logging)
    # The new call using the core method
    translated_json_objects = translator.translate_segments(
        pre_translate_json_list=pre_translate_json_objects,
        source_lang_code="auto", # Let the translator know to detect from text
        target_lang=args.target_lang
    )

    if not translated_json_objects:
        logging.error("Translation failed or returned no segments. Aborting.")
        return
        
    # Integrity check
    if len(translated_json_objects) != len(pre_translate_json_objects):
        logging.critical(f"SEGMENT COUNT MISMATCH! Sent {len(pre_translate_json_objects)}, received {len(translated_json_objects)}. Aborting.")
        return
    logging.info("Segment count integrity check passed.")

    # 4. NEW: Prepare data for post-processing
    # The new translator returns rich objects. We need to prepare them for post-processing.
    final_segments_for_processing = []
    for item in translated_json_objects:
        # Reconstruct the object that post_process_segments expects
        segment_data = item['source_data']
        segment_data['translation'] = item['translated_text']
        final_segments_for_processing.append(segment_data)

    # 5. Post-process translated subtitles
    logging.info("Post-processing translated segments for optimal formatting...")
    final_segments = post_process_segments(final_segments_for_processing)

    # 6. Write translated SRT file
    translated_srt_path = output_dir / f"{file_path.stem}_{args.target_lang}_translated.srt"
    write_srt_file(final_segments, translated_srt_path)

    logging.info(f"Translated SRT file saved to: {translated_srt_path}")


if __name__ == "__main__":
    main() 