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


def main():
    """
    Main function to run the translation process for a local SRT file.
    """
    parser = argparse.ArgumentParser(description="Translate an SRT file.")
    parser.add_argument("file_path", help="The path to the SRT file.")
    parser.add_argument("--model_name", default=None, help="The model name to use for translation. Overrides the default in config.py.")
    parser.add_argument("--output_dir", default="outputs", help="The directory to save the translated files.")
    parser.add_argument("--proxy", help="Proxy server to use for translation.", default=None)

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    file_path = Path(args.file_path)
    if not file_path.is_file():
        print(f"Error: File not found at {file_path}")
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    video_title = file_path.stem
    
    # 1. Parse SRT file
    subtitle_segments = srt_to_segments(file_path)
    # --- Start Duration Check ---
    total_duration_before = sum(seg['end'] - seg['start'] for seg in subtitle_segments)
    logging.info(f"Original total duration: {total_duration_before:.3f} seconds.")

    # 2. Format subtitles for translation
    formatted_subtitles, total_words = format_subtitles(subtitle_segments)

    # --- Start Segment Count Check ---
    count_before_translation = len(formatted_subtitles)
    logging.info(f"Number of segments to be translated: {count_before_translation}")

    # 3. Translate in batches
    translator = Translator(model_name=args.model_name, proxy=args.proxy)
    translated_texts = translator.translate_text_batches(formatted_subtitles)

    # --- Final Segment Count Check ---
    count_after_translation = len(translated_texts)
    if count_before_translation == count_after_translation:
        logging.info(f"Segment count integrity check passed: {count_before_translation} segments sent, {count_after_translation} segments received.")
    else:
        logging.critical(f"SEGMENT COUNT MISMATCH! Sent {count_before_translation}, received {count_after_translation}. Aborting to prevent data corruption.")
        return # Abort the process

    for i, sub in enumerate(formatted_subtitles):
        sub["translation"] = translated_texts[i]

    # 4. Post-process translated subtitles
    final_segments = post_process_segments(formatted_subtitles)

    # --- Final Duration Check ---
    total_duration_after = sum(seg['end'] - seg['start'] for seg in final_segments)
    logging.info(f"Post-processed total duration: {total_duration_after:.3f} seconds.")

    duration_discrepancy = abs(total_duration_after - total_duration_before)
    if duration_discrepancy < 0.001:
        logging.info(f"Duration integrity check passed (Discrepancy: {duration_discrepancy:.6f}s).")
    else:
        logging.warning(f"DURATION MISMATCH! Discrepancy: {duration_discrepancy:.6f}s. The output file may have timing issues.")

    # 5. Write translated SRT file
    translated_srt_path = output_dir / f"{video_title}_translated.srt"
    write_srt_file(final_segments, translated_srt_path)

    print(f"Translated SRT file saved to: {translated_srt_path}")


if __name__ == "__main__":
    main() 