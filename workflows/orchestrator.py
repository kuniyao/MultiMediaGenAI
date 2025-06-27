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
            subtitle_track = SubtitleTrack(video_id=track_id, source_lang=source_lang, source_type=source_type)
            for i, seg_data in enumerate(segments):
                subtitle_track.segments.append(
                    SubtitleSegment(
                        id=f"seg_{i:04d}",
                        start=seg_data['start'],
                        end=seg_data.get('end', seg_data['start'] + seg_data.get('duration', 0)),
                        source_text=seg_data['text']
                    )
                )
            logger.info(f"Successfully created SubtitleTrack with {len(subtitle_track.segments)} segments.")

            # 3. Load prompts
            project_root = Path(__file__).resolve().parent.parent
            prompts_path = project_root / 'prompts.json'
            with open(prompts_path, 'r', encoding='utf-8') as f:
                prompts = json.load(f)

            # 4. Translate
            tasks = subtitle_track_to_html_tasks(subtitle_track, logger)
            results = await execute_translation_async(
                tasks_to_translate=tasks,
                source_lang_code=source_lang,
                target_lang=self.target_lang,
                video_specific_output_path=str(self.video_output_path),
                logger=logger,
                prompts=prompts
            )
            if not results:
                logger.error("Translation failed. Aborting.")
                return

            # 5. Update track from results
            for result in results:
                original_segments = result.get("source_data", {}).get("original_segments", [])
                update_track_from_html_response(
                    original_segments_in_batch=original_segments,
                    translated_html=result.get("translated_text", ""),
                    logger=logger
                )

            # 6. Save final SRT file
            srt_content = generate_post_processed_srt(subtitle_track, logger)
            file_basename = sanitize_filename(metadata.get("title", "translation"))
            srt_path = self.video_output_path / f"{file_basename}_{self.target_lang}.srt"
            save_to_file(srt_content, srt_path, logger)

            logger.info(f"--- Translation Workflow Finished Successfully ---")
            logger.info(f"Translated file saved to: {srt_path}")

        except Exception as e:
            self.task_logger.critical(f"An unexpected error terminated the workflow: {e}", exc_info=True)
