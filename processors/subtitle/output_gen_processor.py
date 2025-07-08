# 处理器5：生成最终内容
from ..base_processor import BaseProcessor
from workflows.dto import PipelineContext
from format_converters.postprocessing import generate_post_processed_srt
import logging

class OutputGenProcessor(BaseProcessor):
    """
    处理器第五步：对翻译完成的 SubtitleTrack 进行后处理，生成最终的SRT文件内容。
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def process(self, context: PipelineContext) -> PipelineContext:
        new_context = context.copy(deep=True)
        
        if not new_context.is_successful or not new_context.subtitle_track:
            return new_context

        self.logger.info("Generating final SRT content with post-processing...")
        try:
            # 1. 从上下文中取出最终翻译好的 SubtitleTrack
            track = new_context.subtitle_track
            
            # 2. 调用【现有】的核心后处理逻辑函数
            srt_content = generate_post_processed_srt(track, self.logger)
            
            # 3. 将最终的字符串内容放回上下文
            new_context.final_srt_content = srt_content
            self.logger.info("Final SRT content generated successfully.")

        except Exception as e:
            self.logger.error(f"Failed during output generation: {e}", exc_info=True)
            new_context.is_successful = False
            new_context.error_message = f"Output generation failed: {e}"
            
        return new_context