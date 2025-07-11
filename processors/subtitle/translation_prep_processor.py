# 处理器3：准备翻译任务
from ..base_processor import BaseProcessor
from workflows.dto import PipelineContext
from llm_utils.subtitle_processor import subtitle_track_to_json_tasks
import logging

class TranslationPrepProcessor(BaseProcessor):
    """
    处理器第三步：准备翻译任务。
    将 SubtitleTrack 转换为适合LLM的、分批的JSON任务。
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def process(self, context: PipelineContext) -> PipelineContext:
        if not context.is_successful:
            return context

        new_context = context.model_copy(deep=True)
        track = new_context.subtitle_track
        
        if not track or not track.segments:
            self.logger.warning("SubtitleTrack not found or is empty in context. Skipping translation preparation.")
            return new_context
        
        try:
            self.logger.info("Converting SubtitleTrack to batched JSON tasks for LLM...")
            # 【关键修复】将参数名从 'input_data' 改为 'segments'，
            # 以匹配 llm_utils/subtitle_processor.py 中更新后的函数签名。
            tasks = subtitle_track_to_json_tasks(
                segments=new_context.subtitle_track.segments,
                logger=self.logger,
                base_id=new_context.source_metadata.get("video_id") or new_context.source_metadata.get("filename")
            )
            new_context.translation_tasks = tasks
            new_context.is_successful = True
            self.logger.info(f"Successfully created {len(tasks)} batched JSON tasks.")

        except Exception as e:
            self.logger.error(f"Failed to prepare translation tasks: {e}", exc_info=True)
            new_context.is_successful = False
            new_context.error_message = f"Failed to prepare translation tasks: {e}"
        
        return new_context