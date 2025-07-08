# 处理器1：获取数据
# processors/data_fetch_processor.py

from ..base_processor import BaseProcessor
from workflows.dto import PipelineContext
from data_sources.local_file_source import LocalFileSource
from data_sources.youtube_source import YouTubeSource
import os
import logging

class DataFetchProcessor(BaseProcessor):
    """
    处理器第一步：根据输入源获取原始数据。
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def process(self, context: PipelineContext) -> PipelineContext:
        # 【修正1】: 使用 .model_copy() 代替 .copy()
        new_context = context.model_copy(deep=True)
        
        self.logger.info(f"Starting data fetch for input: {new_context.source_input}")
        try:
            data_source = None
            if os.path.isfile(new_context.source_input):
                # 【修正2】: 使用 self.logger
                data_source = LocalFileSource(new_context.source_input, self.logger)
            # 你原来的代码中包含 is_youtube_url 函数，这里为了简化直接使用字符串检查
            elif "youtube.com/" in new_context.source_input or "youtu.be/" in new_context.source_input:
                # 【修正2】: 使用 self.logger
                data_source = YouTubeSource(new_context.source_input, self.logger)
            else:
                raise ValueError(f"Invalid input source: {new_context.source_input}")

            segments, lang, type = data_source.get_segments()
            metadata = data_source.get_metadata()
            
            new_context.raw_segments = segments
            new_context.source_lang = lang
            new_context.source_type = type
            new_context.source_metadata = metadata
            self.logger.info(f"Successfully fetched {len(segments)} raw segments.")
            
        except Exception as e:
            self.logger.error(f"Data fetching failed: {e}", exc_info=True)
            new_context.is_successful = False
            new_context.error_message = f"Data fetching failed: {e}"
        
        return new_context