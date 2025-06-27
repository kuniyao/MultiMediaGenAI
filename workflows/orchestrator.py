import os
import logging
from datetime import datetime
import json
from pathlib import Path

import config
from data_sources.base_source import DataSource
from common_utils.file_helpers import sanitize_filename, save_to_file
from common_utils.log_config import setup_task_logger
from format_converters import generate_post_processed_srt
from format_converters.book_schema import SubtitleTrack, SubtitleSegment
from llm_utils.translator import execute_translation_async
from llm_utils.subtitle_processor import subtitle_track_to_html_tasks, update_track_from_html_response

class TranslationOrchestrator:
    """
    Orchestrates the entire translation workflow, from data fetching to file saving.
    """
    def __init__(self, data_source: DataSource, target_lang: str, output_dir: str, log_level: str = "INFO"):
        self.data_source = data_source
        self.target_lang = target_lang
        self.base_output_dir = Path(output_dir)
        self.log_level = log_level
        self.task_logger = None
        self.video_output_path = None

    def _setup_environment(self):
        """Sets up the output directories and logging for the task."""
        metadata = self.data_source.get_metadata()
        sanitized_title = sanitize_filename(metadata.get("title", "untitled"))
        
        self.video_output_path = self.base_output_dir / sanitized_title
        self.video_output_path.mkdir(parents=True, exist_ok=True)

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_name = f"{sanitized_title}_{timestamp_str}.log"
        log_file_full_path = self.video_output_path / log_file_name

        numeric_log_level = getattr(logging, self.log_level.upper(), logging.INFO)
        logger_name = f"TaskWorkflow.{sanitized_title}.{timestamp_str}"
        self.task_logger = setup_task_logger(logger_name, log_file_full_path, level=numeric_log_level)
        self.task_logger.info(f"Task-specific output directory: {self.video_output_path}")

    async def run(self):
        """Executes the full translation workflow."""
        self._setup_environment()
        logger = self.task_logger

        try:
            logger.info("--- Translation Workflow Started ---")
            
            # 1. Get segments from the data source
            segments, source_lang, source_type = self.data_source.get_segments()
            if not segments:
                logger.error("No segments returned from data source. Aborting.")
                return

            # 2. Create SubtitleTrack object
            metadata = self.data_source.get_metadata()
            track_id = metadata.get("video_id") or metadata.get("filename")
            subtitle_track = SubtitleTrack.from_segments(
                segments_data=segments,
                video_id=track_id,
                source_lang=source_lang,
                source_type=source_type
            )
            logger.info(f"Successfully created SubtitleTrack with {len(subtitle_track.segments)} segments.")

            # 3. Prompts are now loaded within the Translator class

            # 4. Initial Translation
            tasks_to_translate = subtitle_track_to_html_tasks(subtitle_track, logger, base_id=track_id)
            initial_results = await execute_translation_async(
                tasks_to_translate=tasks_to_translate,
                source_lang_code=source_lang,
                target_lang=self.target_lang,
                raw_llm_log_dir=str(self.video_output_path),
                logger=logger
            )
            if not initial_results:
                logger.error("Initial translation failed or returned no results. Aborting.")
                return

            # 5. Update track from initial results
            for result in initial_results:
                update_track_from_html_response(
                    subtitle_track=subtitle_track,
                    translated_html=result.get("translated_text", ""),
                    logger=logger
                )

            # 6. Retry mechanism for untranslated segments
            MAX_RETRY_ROUNDS = 3
            RETRY_DELAY_SECONDS = 5
            
            for retry_round in range(MAX_RETRY_ROUNDS):
                untranslated_segments = [
                    seg for seg in subtitle_track.segments
                    if not seg.translated_text or seg.translated_text.startswith("[TRANSLATION_FAILED]")
                ]

                if not untranslated_segments:
                    logger.info(f"All segments translated after {retry_round + 1} rounds.")
                    break
                
                logger.warning(f"Found {len(untranslated_segments)} untranslated segments after round {retry_round + 1}. Retrying...")

                # Create new tasks only for untranslated segments
                retry_tasks = subtitle_track_to_html_tasks(untranslated_segments, logger, base_id=track_id) 
                
                if not retry_tasks:
                    logger.warning("No retry tasks could be generated for untranslated segments. Aborting retry.")
                    break

                retry_results = await execute_translation_async(
                    tasks_to_translate=retry_tasks,
                    source_lang_code=source_lang,
                    target_lang=self.target_lang,
                    raw_llm_log_dir=str(self.video_output_path),
                    logger=logger
                )

                if retry_results:
                    for result in retry_results:
                        update_track_from_html_response(
                            subtitle_track=subtitle_track,
                            translated_html=result.get("translated_text", ""),
                            logger=logger
                        )
                else:
                    logger.warning(f"Retry round {retry_round + 1} yielded no new translations.")

                if retry_round < MAX_RETRY_ROUNDS - 1:
                    logger.info(f"Waiting {RETRY_DELAY_SECONDS} seconds before next retry round...")
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
            else:
                final_untranslated_count = len([
                    seg for seg in subtitle_track.segments
                    if not seg.translated_text or seg.translated_text.startswith("[TRANSLATION_FAILED]")
                ])
                if final_untranslated_count > 0:
                    logger.error(f"Finished all {MAX_RETRY_ROUNDS} retry rounds. {final_untranslated_count} segments remain untranslated.")
                else:
                    logger.info("All segments translated after all retry rounds.")

            # 7. Save final SRT file (original step 6)
            srt_content = generate_post_processed_srt(subtitle_track, logger)
            file_basename = sanitize_filename(metadata.get("title", "translation"))
            srt_path = self.video_output_path / f"{file_basename}_{self.target_lang}.srt"
            save_to_file(srt_content, srt_path, logger)

            logger.info(f"--- Translation Workflow Finished Successfully ---")
            logger.info(f"Translated file saved to: {srt_path}")

        except Exception as e:
            self.task_logger.critical(f"An unexpected error terminated the workflow: {e}", exc_info=True)
