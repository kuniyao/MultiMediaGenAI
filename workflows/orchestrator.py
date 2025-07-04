import os
import sys
import logging
from datetime import datetime
import json
from pathlib import Path
import asyncio
import re

import config
from data_sources.base_source import SegmentedDataSource
from common_utils.file_helpers import sanitize_filename
from common_utils.log_config import setup_task_logger
from common_utils.output_manager import OutputManager
from format_converters import generate_post_processed_srt
from format_converters.book_schema import SubtitleTrack, SubtitleSegment
from format_converters.srt_handler import segments_to_srt_string
from llm_utils.translator import execute_translation_async
from llm_utils.subtitle_processor import subtitle_track_to_html_tasks, update_track_from_html_response

class TranslationOrchestrator:
    """
    Orchestrates the entire translation workflow, from data fetching to file saving.
    """
    def __init__(self, data_source: SegmentedDataSource, target_lang: str, output_dir: str, log_level: str = "INFO", save_llm_logs: bool = False):
        self.data_source = data_source
        self.target_lang = target_lang
        self.log_level = log_level
        self.save_llm_logs = save_llm_logs
        
        # Setup task-specific logger and output manager
        metadata = self.data_source.get_metadata()
        sanitized_title = sanitize_filename(metadata.get("title", "untitled"))
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        logger_name = f"TaskWorkflow.{sanitized_title}.{timestamp_str}"
        log_file_name = f"{sanitized_title}_{timestamp_str}.log"
        
        # The base_output_dir for OutputManager will be the task-specific directory
        self.task_output_dir = Path(output_dir) / sanitized_title
        self.task_output_dir.mkdir(parents=True, exist_ok=True) # Ensure the task-specific directory exists
        
        log_file_full_path = self.task_output_dir / log_file_name
        numeric_log_level = getattr(logging, self.log_level.upper(), logging.INFO)
        self.task_logger = setup_task_logger(logger_name, log_file_full_path, level=numeric_log_level)
        self.task_logger.info(f"Task-specific output directory: {self.task_output_dir}")

        self.output_manager = OutputManager(str(self.task_output_dir), self.task_logger)
        self._collected_llm_logs = [] # Initialize list to collect LLM logs

    async def run(self):
        """Executes the full translation workflow."""
        logger = self.task_logger

        try:
            translation_successful = True # Initialize to True, set to False on failure conditions
            logger.info("--- Translation Workflow Started ---")
            
            # 1. Get segments from the data source
            segments, source_lang, source_type = self.data_source.get_segments()
            if not segments:
                logger.error("No segments returned from data source. Aborting.")
                return

            # Save the original, unprocessed segments for reference
            metadata = self.data_source.get_metadata()
            file_basename_for_source = sanitize_filename(metadata.get("title", "source"))
            try:
                original_srt_content = segments_to_srt_string(segments)
                original_srt_path = self.output_manager.get_workflow_output_path(
                    "source", f"{file_basename_for_source}_original_{source_lang}.srt"
                )
                self.output_manager.save_file(original_srt_path, original_srt_content)
                logger.info(f"Saved original source subtitle to: {original_srt_path}")
            except Exception as e:
                logger.warning(f"Could not save the original source SRT file: {e}", exc_info=True)

            # 2. Create SubtitleTrack object
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
            initial_results, initial_llm_logs = await execute_translation_async(
                tasks_to_translate=tasks_to_translate,
                source_lang_code=source_lang,
                target_lang=self.target_lang,
                logger=logger
            )
            self._collected_llm_logs.extend(initial_llm_logs)

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

            # 6. Handle retries for untranslated segments
            retry_success, retry_llm_logs = await self._handle_translation_retries(
                subtitle_track=subtitle_track,
                source_lang=source_lang,
                logger=logger,
                track_id=track_id
            )
            self._collected_llm_logs.extend(retry_llm_logs)
            translation_successful = retry_success # Update overall success based on retry outcome

            # 7. Save final SRT file (original step 6)
            srt_content = generate_post_processed_srt(subtitle_track, logger)
            file_basename = sanitize_filename(metadata.get("title", "translation"))
            srt_path = self.output_manager.get_workflow_output_path("subtitle", f"{file_basename}_{self.target_lang}.srt")
            self.output_manager.save_file(srt_path, srt_content)

            logger.info(f"--- Translation Workflow Finished Successfully ---")
            logger.info(f"Translated file saved to: {srt_path}")

            # Save LLM logs based on success/failure and save_llm_logs flag
            if not translation_successful or self.save_llm_logs:
                self._save_llm_logs_to_file(self._collected_llm_logs, self.target_lang)

        except Exception as e:
            self.task_logger.critical(f"An unexpected error terminated the workflow: {e}", exc_info=True)
            # Always save LLM logs on unexpected errors
            self._save_llm_logs_to_file(self._collected_llm_logs, self.target_lang)

    async def _handle_translation_retries(self, subtitle_track: SubtitleTrack, source_lang: str, logger: logging.Logger, track_id: str) -> tuple[bool, list]:
        """
        Handles retries for untranslated segments with a tiered strategy.
        - Soft Errors (likely collateral damage from a failed batch) are retried in batches.
        - Hard Errors (e.g., detected repeated text, likely a "poison pill") are retried individually to isolate the problem.
        """
        MAX_RETRY_ROUNDS = 3
        RETRY_DELAY_SECONDS = 5
        translation_successful_in_retry = True
        collected_llm_logs_in_retry = []

        for retry_round in range(MAX_RETRY_ROUNDS):
            soft_error_segments = []
            hard_error_segments = []

            for seg in subtitle_track.segments:
                # Prioritize checking for hard errors, even in already "translated" text
                if self._is_repeated_text(seg.translated_text):
                    hard_error_segments.append(seg)
                # Then check for soft errors (untranslated or explicitly failed)
                elif not seg.translated_text or seg.translated_text.startswith("[TRANSLATION_FAILED]"):
                    soft_error_segments.append(seg)
            
            if not soft_error_segments and not hard_error_segments:
                logger.info("No untranslated segments found. Retry mechanism complete.")
                break
            
            logger.info(f"--- Starting Retry Round {retry_round + 1}/{MAX_RETRY_ROUNDS} ---")
            
            # Process soft error segments first (batch translation)
            if soft_error_segments:
                logger.warning(f"Found {len(soft_error_segments)} soft-error segments. Retrying as a batch...")
                soft_retry_tasks = subtitle_track_to_html_tasks(soft_error_segments, logger, base_id=track_id)
                if soft_retry_tasks:
                    soft_retry_results, soft_retry_llm_logs = await execute_translation_async(
                        tasks_to_translate=soft_retry_tasks,
                        source_lang_code=source_lang,
                        target_lang=self.target_lang,
                        logger=logger
                    )
                    collected_llm_logs_in_retry.extend(soft_retry_llm_logs)
                    if soft_retry_results:
                        for result in soft_retry_results:
                            update_track_from_html_response(
                                subtitle_track=subtitle_track,
                                translated_html=result.get("translated_text", ""),
                                logger=logger
                            )
                    else:
                        logger.warning(f"Soft-error retry round {retry_round + 1} yielded no new translations.")
                else:
                    logger.warning("No soft-error retry tasks could be generated.")

            # Process hard error segments (individual translation to isolate poison pills)
            if hard_error_segments:
                logger.warning(f"Found {len(hard_error_segments)} hard-error segments. Retrying individually...")
                for seg in hard_error_segments:
                    logger.info(f"Attempting individual retry for segment {seg.id}...")
                    hard_retry_tasks = subtitle_track_to_html_tasks([seg], logger, base_id=track_id) # Send individually
                    if hard_retry_tasks:
                        hard_retry_results, hard_retry_llm_logs = await execute_translation_async(
                            tasks_to_translate=hard_retry_tasks,
                            source_lang_code=source_lang,
                            target_lang=self.target_lang,
                            logger=logger
                        )
                        collected_llm_logs_in_retry.extend(hard_retry_llm_logs)
                        if hard_retry_results:
                            for result in hard_retry_results:
                                update_track_from_html_response(
                                    subtitle_track=subtitle_track,
                                    translated_html=result.get("translated_text", ""),
                                    logger=logger
                                )
                        else:
                            logger.warning(f"Hard-error retry for segment {seg.id} yielded no new translation.")
                    else:
                        logger.warning(f"No hard-error retry task could be generated for segment {seg.id}.")
            
            # Re-check untranslated segments after processing both types of errors
            remaining_untranslated = [
                seg for seg in subtitle_track.segments
                if not seg.translated_text or seg.translated_text.startswith("[TRANSLATION_FAILED]")
            ]

            if not remaining_untranslated:
                logger.info(f"All segments successfully translated after retry round {retry_round + 1}.")
                translation_successful_in_retry = True
                break # All translated, exit retry loop
            
            if retry_round < MAX_RETRY_ROUNDS - 1:
                logger.info(f"Waiting {RETRY_DELAY_SECONDS} seconds before next retry round...")
                await asyncio.sleep(RETRY_DELAY_SECONDS)
            else:
                # If loop finishes and there are still untranslated segments
                logger.error(f"Finished all {MAX_RETRY_ROUNDS} retry rounds. {len(remaining_untranslated)} segments remain untranslated.")
                translation_successful_in_retry = False
        
        return translation_successful_in_retry, collected_llm_logs_in_retry

    def _is_repeated_text(self, text: str) -> bool:
        # Detects if a character is repeated 5 or more times consecutively,
        # or if the text is in the format `[original text]`, indicating a translation failure by the LLM.
        if not text:
            return False
        
        # Regex to find any character (including Chinese characters) repeated 5 or more times
        # The `.` matches any character except newline. `一-龥` matches Chinese characters.
        # We use re.DOTALL to make '.' match newlines as well, in case the repeated text spans lines.
        if re.search(r"(.)\1{4,}", text, re.DOTALL):
            self.task_logger.warning(f"Detected repeated text pattern in: '{text[:50]}...'")
            return True
        
        # Check for the new safety format e.g., `[some original text]`
        if text.strip().startswith('[') and text.strip().endswith(']'):
            self.task_logger.warning(f"Detected LLM-reported untranslatable text: '{text[:50]}...'")
            return True
            
        return False

    def _save_llm_logs_to_file(self, llm_logs: list[str], target_lang: str):
        if not llm_logs:
            self.task_logger.info("No LLM logs collected to save.")
            return

        log_file_name = f"llm_raw_responses_{target_lang.lower().replace('-','').replace('_','')}.jsonl"
        log_file_path = self.output_manager.get_workflow_output_path("llm_logs", log_file_name)
        
        try:
            with open(log_file_path, 'w', encoding='utf-8') as f:
                for log_entry in llm_logs:
                    f.write(log_entry + '\n')
            self.task_logger.info(f"LLM raw response logs saved to: {log_file_path}")
        except Exception as e:
            self.task_logger.error(f"Failed to save LLM raw response logs to {log_file_path}: {e}", exc_info=True)