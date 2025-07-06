# 处理器3：准备翻译任务
from .base_processor import BaseProcessor
from workflows.dto import PipelineContext
from llm_utils.subtitle_processor import subtitle_track_to_html_tasks
import logging

class TranslationPrepProcessor(BaseProcessor):
    """
    处理器第三步：将 SubtitleTrack 对象转换为分批的、适合LLM翻译的HTML任务。
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def process(self, context: PipelineContext) -> PipelineContext:
        new_context = context.copy(deep=True)

        if not new_context.is_successful or not new_context.subtitle_track:
            return new_context

        self.logger.info("Preparing batched HTML tasks for the translator...")
        try:
            # 1. 从上下文中获取 SubtitleTrack 和元数据
            track = new_context.subtitle_track
            metadata = new_context.source_metadata
            track_id = metadata.get("video_id") or metadata.get("filename")

            # 2. 调用【现有】的功能函数
            tasks = subtitle_track_to_html_tasks(track, self.logger, base_id=track_id)
            
            # 3. 将结果存入上下文
            new_context.translation_tasks = tasks
            self.logger.info(f"Successfully created {len(tasks)} translation task(s).")

        except Exception as e:
            self.logger.error(f"Failed during translation task preparation: {e}", exc_info=True)
            new_context.is_successful = False
            new_context.error_message = f"Translation task preparation failed: {e}"
        
        return new_context