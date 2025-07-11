from ..base_processor import BaseProcessor
from workflows.dto import PipelineContext
from format_converters.book_schema import SubtitleTrack
from llm_utils.translator import execute_translation_async
from llm_utils.subtitle_processor import update_track_from_json_response, subtitle_track_to_json_tasks
import asyncio
import logging
import re
import json

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
        
        # 修正1: 增加对关键上下文参数的检查
        if not track or not new_context.source_lang or not new_context.target_lang:
            new_context.is_successful = False
            new_context.error_message = "Missing SubtitleTrack, source_lang, or target_lang in context."
            self.logger.error(new_context.error_message)
            return new_context

        try:
            self.logger.info(f"Starting initial translation for {len(track.segments)} segments...")
            initial_results, initial_logs = await execute_translation_async(
                tasks_to_translate=new_context.translation_tasks,
                source_lang_code=new_context.source_lang,
                target_lang=new_context.target_lang,
                logger=self.logger
            )
            # 修正2: 将字典日志转换为JSON字符串
            new_context.llm_logs.extend([json.dumps(log, ensure_ascii=False) for log in initial_logs])
            
            if not initial_results:
                 raise RuntimeError("Initial translation returned no results.")

            # 【关键修改】现在 update_track_from_json_response 内部处理了解析错误，
            # 因此这里不再需要 try/except 块。函数会尽力解析，并静默地跳过无法解析的批次。
            # 后续的重试逻辑会自动捕获那些未被成功更新的片段。
            for result in initial_results:
                update_track_from_json_response(track, result.get("translated_text", ""), self.logger)
            
            self.logger.info("Initial translation batch applied. Starting retry and validation process...")
            
            # 修正3: 安全地获取元数据和 track_id
            source_metadata = new_context.source_metadata or {}
            track_id = str(source_metadata.get("video_id") or source_metadata.get("filename") or "unknown_track")

            # 直接调用内部的异步重试逻辑
            retry_success, retry_logs = await self._handle_retries_internal(
                track=track,
                source_lang=new_context.source_lang,
                target_lang=new_context.target_lang,
                track_id=track_id,
                context=new_context  # 传递整个上下文以便记录错误
            )
            # 修正4: 将字典日志转换为JSON字符串
            new_context.llm_logs.extend([json.dumps(log, ensure_ascii=False) for log in retry_logs])
            
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
        
    async def _handle_retries_internal(
        self, track: SubtitleTrack, source_lang: str, target_lang: str, track_id: str, context: PipelineContext
    ) -> tuple[bool, list]:
        """
        【已实现】将原来 orchestrator._handle_translation_retries 的代码移到这里。
        现在也负责将发现的错误记录到上下文中。
        """
        MAX_RETRY_ROUNDS = 3
        RETRY_DELAY_SECONDS = 5
        all_logs = []

        for retry_round in range(MAX_RETRY_ROUNDS):
            soft_error_segments = []
            hard_error_segments = []

            for seg in track.segments:
                if self._is_repeated_text(seg.translated_text):
                    hard_error_segments.append(seg)
                elif not seg.translated_text or seg.translated_text.startswith("[TRANSLATION_FAILED]"):
                    soft_error_segments.append(seg)
            
            # 只在第一轮（初始检测）时记录错误
            if retry_round == 0:
                if hard_error_segments:
                    context.translation_errors['hard_errors'] = [
                        {"id": seg.id, "source_text": seg.source_text, "translated_text": seg.translated_text}
                        for seg in hard_error_segments
                    ]
                if soft_error_segments:
                    context.translation_errors['soft_errors'] = [
                        {"id": seg.id, "source_text": seg.source_text}
                        for seg in soft_error_segments
                    ]
                
                # 添加唯一的、高级别的错误摘要日志
                error_summary = []
                if 'hard_errors' in context.translation_errors:
                    error_summary.append(f"{len(context.translation_errors['hard_errors'])} hard errors")
                if 'soft_errors' in context.translation_errors:
                    error_summary.append(f"{len(context.translation_errors['soft_errors'])} soft errors")
                
                if error_summary:
                    self.logger.warning(f"Initial translation check found {' and '.join(error_summary)}. Starting retry process. Details will be saved to 'translation_errors.json'.")


            if not soft_error_segments and not hard_error_segments:
                self.logger.info("No untranslated segments found. Retry mechanism complete.")
                return True, all_logs
            
            self.logger.info(f"--- Starting Retry Round {retry_round + 1}/{MAX_RETRY_ROUNDS} ---")
            
            if soft_error_segments:
                self.logger.debug(f"Found {len(soft_error_segments)} soft-error segments. Retrying as a batch...")
                tasks = subtitle_track_to_json_tasks(soft_error_segments, self.logger, base_id=track_id)
                if tasks:
                    results, logs = await execute_translation_async(tasks, source_lang, target_lang, self.logger)
                    all_logs.extend(logs)
                    if results:
                        for r in results:
                            update_track_from_json_response(track, r.get("translated_text", ""), self.logger)

            if hard_error_segments:
                self.logger.debug(f"Found {len(hard_error_segments)} hard-error segments. Retrying individually...")
                for seg in hard_error_segments:
                    # 【保持一致】这里的调用是位置参数，已经和新的签名匹配，无需修改
                    tasks = subtitle_track_to_json_tasks([seg], self.logger, base_id=track_id)
                    if tasks:
                        results, logs = await execute_translation_async(tasks, source_lang, target_lang, self.logger)
                        all_logs.extend(logs)
                        if results:
                            for r in results:
                                update_track_from_json_response(track, r.get("translated_text", ""), self.logger)
            
            remaining = [s for s in track.segments if not s.translated_text or s.translated_text.startswith("[TRANSLATION_FAILED]")]
            if not remaining:
                self.logger.info(f"All segments successfully translated after retry round {retry_round + 1}.")
                return True, all_logs
            
            if retry_round < MAX_RETRY_ROUNDS - 1:
                await asyncio.sleep(RETRY_DELAY_SECONDS)
        
        final_remaining_count = len([s for s in track.segments if not s.translated_text or s.translated_text.startswith("[TRANSLATION_FAILED]")])
        if final_remaining_count > 0:
            self.logger.error(f"Finished all retry rounds. {final_remaining_count} segments remain untranslated.")
            # 更新最终的软错误列表，以反映重试后的最终状态
            final_soft_errors = [s for s in track.segments if not s.translated_text or s.translated_text.startswith("[TRANSLATION_FAILED]")]
            context.translation_errors['soft_errors'] = [
                {"id": seg.id, "source_text": seg.source_text} for seg in final_soft_errors
            ]
            return False, all_logs

        return True, all_logs

    def _is_repeated_text(self, text: str) -> bool:
        # 将原来 orchestrator._is_repeated_text 的代码移到这里
        if not text or len(text) < 10:  # 短文本不太可能出现有意义的重复
            return False

        # 规则1: 检测单个字符的重复 (例如 "aaaaa" 或 "......")
        if re.search(r"(.)\1{4,}", text, re.DOTALL):
            self.logger.debug(f"Detected repeated single-character pattern in: '{text[:50]}...'")
            return True
        
        # 规则2: 【新增】检测词组的重复 (例如 "我认为，我认为，我认为，")
        # 查找任何长度至少为2的非贪婪匹配字符串，如果它连续出现4次或以上
        if re.search(r"(.{2,}?)\1{3,}", text, re.DOTALL):
            self.logger.debug(f"Detected repeated phrase pattern in: '{text[:50]}...'")
            return True

        # 规则3: 检测模型明确表示无法翻译的文本 (例如 "[无法翻译]")
        if text.strip().startswith('[') and text.strip().endswith(']'):
            self.logger.debug(f"Detected LLM-reported untranslatable text: '{text[:50]}...'")
            return True
            
        return False