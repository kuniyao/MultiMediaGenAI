# 处理器2：数据建模
from .base_processor import BaseProcessor
from workflows.dto import PipelineContext
from format_converters.book_schema import SubtitleTrack
import logging

class ModelingProcessor(BaseProcessor):
    """
    处理器第二步：将原始片段数据建模为一个标准的 SubtitleTrack 对象。
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def process(self, context: PipelineContext) -> PipelineContext:
        """
        接收包含 raw_segments 的上下文，返回填充了 subtitle_track 的新上下文。
        """
        # 函数式风格：不修改输入的context，而是创建一个副本
        new_context = context.copy(deep=True)
        
        # 契约检查：如果前序步骤失败，或缺少必要数据，则直接返回
        if not new_context.is_successful or not new_context.raw_segments:
            # 如果 raw_segments 为空但流程是成功的，说明源文件可能为空，这也是一种有效情况
            if new_context.is_successful and not new_context.raw_segments:
                 self.logger.warning("No raw segments found to model. The source might be empty.")
                 new_context.is_successful = False # 标记为失败，以中止后续流程
                 new_context.error_message = "Source is empty or contains no valid segments."
            return new_context

        self.logger.info("Modeling raw segments into a SubtitleTrack object...")
        try:
            # 1. 从“货箱”中取出需要的原材料
            segments_data = new_context.raw_segments
            metadata = new_context.source_metadata
            source_lang = new_context.source_lang
            source_type = new_context.source_type
            
            # 从元数据中获取唯一的轨道ID
            track_id = metadata.get("video_id") or metadata.get("filename")

            # 2. 调用【现有】的核心逻辑：SubtitleTrack 的类方法
            subtitle_track = SubtitleTrack.from_segments(
                segments_data=segments_data,
                video_id=track_id,
                source_lang=source_lang,
                source_type=source_type
            )
            
            # 3. 将产出的新零件（subtitle_track）放回“货箱”
            new_context.subtitle_track = subtitle_track
            self.logger.info(f"Successfully created SubtitleTrack with {len(subtitle_track.segments)} segments.")

        except Exception as e:
            self.logger.error(f"Failed during modeling process: {e}", exc_info=True)
            new_context.is_successful = False
            new_context.error_message = f"Modeling failed: {e}"
            
        return new_context