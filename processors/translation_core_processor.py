from .base_processor import BaseProcessor
from workflows.dto import PipelineContext
from format_converters.book_schema import SubtitleTrack
from llm_utils.translator import execute_translation_async
from llm_utils.subtitle_processor import update_track_from_html_response, subtitle_track_to_html_tasks
import asyncio
import logging
import re

class TranslationCoreProcessor(BaseProcessor):
    """
    处理器第四步：执行核心翻译和智能重试逻辑。
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    # 【修正】: 我们只需要一个 async def process 方法。
    # 它直接包含了所有的异步逻辑。
    async def process(self, context: PipelineContext) -> PipelineContext:
        """
        这个方法是异步的，由 Pipeline 直接 await。
        """
        if not context.is_successful:
            return context

        new_context = context.model_copy(deep=True)
        track = new_context.subtitle_track
        
        if not track:
            new_context.is_successful = False
            new_context.error_message = "SubtitleTrack not found in context for translation."
            return new_context

        try:
            self.logger.info(f"Starting initial translation for {len(track.segments)} segments...")
            initial_results, initial_logs = await execute_translation_async(
                tasks_to_translate=new_context.translation_tasks,
                source_lang_code=new_context.source_lang,
                target_lang=new_context.target_lang,
                logger=self.logger
            )
            new_context.llm_logs.extend(initial_logs)
            
            if not initial_results:
                 raise RuntimeError("Initial translation returned no results.")

            for result in initial_results:
                update_track_from_html_response(track, result.get("translated_text", ""), self.logger)
            
            self.logger.info("Initial translation applied. Starting retry and validation process...")
            
            # 直接调用内部的异步重试逻辑
            retry_success, retry_logs = await self._handle_retries_internal(
                subtitle_track=track,
                source_lang=new_context.source_lang,
                target_lang=new_context.target_lang,
                track_id=new_context.source_metadata.get("video_id") or new_context.source_metadata.get("filename")
            )
            new_context.llm_logs.extend(retry_logs)
            
            if not retry_success:
                new_context.is_successful = False
                new_context.error_message = "Translation failed after all retry rounds."

        except Exception as e:
            self.logger.error(f"Translation core processor failed: {e}", exc_info=True)
            new_context.is_successful = False
            new_context.error_message = f"Translation core failed: {e}"

        # 将更新后的 track 对象放回 new_context
        new_context.subtitle_track = track
        return new_context
        
    async def _handle_retries_internal(self, subtitle_track: SubtitleTrack, source_lang: str, target_lang: str, track_id: str) -> tuple[bool, list]:
        """
        【已实现】将原来 orchestrator._handle_translation_retries 的代码移到这里。
        """
        MAX_RETRY_ROUNDS = 3
        RETRY_DELAY_SECONDS = 5
        all_logs = []

        for retry_round in range(MAX_RETRY_ROUNDS):
            soft_error_segments = []
            hard_error_segments = []

            for seg in subtitle_track.segments:
                if self._is_repeated_text(seg.translated_text):
                    hard_error_segments.append(seg)
                elif not seg.translated_text or seg.translated_text.startswith("[TRANSLATION_FAILED]"):
                    soft_error_segments.append(seg)
            
            if not soft_error_segments and not hard_error_segments:
                self.logger.info("No untranslated segments found. Retry mechanism complete.")
                return True, all_logs
            
            self.logger.info(f"--- Starting Retry Round {retry_round + 1}/{MAX_RETRY_ROUNDS} ---")
            
            if soft_error_segments:
                self.logger.warning(f"Found {len(soft_error_segments)} soft-error segments. Retrying as a batch...")
                tasks = subtitle_track_to_html_tasks(soft_error_segments, self.logger, base_id=track_id)
                if tasks:
                    results, logs = await execute_translation_async(tasks, source_lang, target_lang, self.logger)
                    all_logs.extend(logs)
                    if results:
                        for r in results:
                            update_track_from_html_response(subtitle_track, r.get("translated_text", ""), self.logger)

            if hard_error_segments:
                self.logger.warning(f"Found {len(hard_error_segments)} hard-error segments. Retrying individually...")
                for seg in hard_error_segments:
                    tasks = subtitle_track_to_html_tasks([seg], self.logger, base_id=track_id)
                    if tasks:
                        results, logs = await execute_translation_async(tasks, source_lang, target_lang, self.logger)
                        all_logs.extend(logs)
                        if results:
                            for r in results:
                                update_track_from_html_response(subtitle_track, r.get("translated_text", ""), self.logger)
            
            remaining = [s for s in subtitle_track.segments if not s.translated_text or s.translated_text.startswith("[TRANSLATION_FAILED]")]
            if not remaining:
                self.logger.info(f"All segments successfully translated after retry round {retry_round + 1}.")
                return True, all_logs
            
            if retry_round < MAX_RETRY_ROUNDS - 1:
                await asyncio.sleep(RETRY_DELAY_SECONDS)
        
        self.logger.error(f"Finished all retry rounds. {len(remaining)} segments remain untranslated.")
        return False, all_logs

    def _is_repeated_text(self, text: str) -> bool:
        # 将原来 orchestrator._is_repeated_text 的代码移到这里
        if not text: return False
        if re.search(r"(.)\1{4,}", text, re.DOTALL):
            self.logger.warning(f"Detected repeated text pattern in: '{text[:50]}...'")
            return True
        if text.strip().startswith('[') and text.strip().endswith(']'):
            self.logger.warning(f"Detected LLM-reported untranslatable text: '{text[:50]}...'")
            return True
        return False