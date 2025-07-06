import logging
import os
from pathlib import Path
from .base_processor import BaseProcessor
from workflows.dto import PipelineContext
# 导入你现有的、功能强大的核心函数
from format_converters.epub_writer import book_to_epub
from common_utils.output_manager import OutputManager
from common_utils.file_helpers import sanitize_filename

class EpubWritingProcessor(BaseProcessor):
    """
    处理器第六步（终点）：将最终翻译完成的 Book 对象写入一个新的 .epub 文件。
    它负责处理所有文件写入的副作用。
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def process(self, context: PipelineContext) -> PipelineContext:
        """
        接收包含 translated_book 的上下文，执行文件写入操作。
        """
        # 这是管道的终点，可以直接修改上下文，无需创建副本
        if not context.is_successful or not context.translated_book:
            self.logger.warning("Skipping EPUB writing because the pipeline failed or no translated book was produced.")
            return context

        self.logger.info("Writing final translated book to a new EPUB file...")
        try:
            # 1. 从“货箱”中取出最终的成品 Book 对象
            translated_book = context.translated_book
            
            # 2. 准备输出路径和文件名
            source_filename, source_ext = os.path.splitext(os.path.basename(context.source_input))
            lang_suffix = context.target_lang.replace('-', '_')
            output_filename = f"{source_filename}_{lang_suffix}{source_ext}"
            
            # 使用 OutputManager 来管理输出路径
            output_manager = OutputManager(context.output_dir, self.logger)
            output_path = output_manager.get_workflow_output_path("epub_translated", output_filename)
            
            self.logger.info(f"Final EPUB will be saved to: {output_path}")

            # 3. 调用【现有】的核心功能函数来完成所有复杂的文件写入和打包工作
            book_to_epub(translated_book, str(output_path))

            self.logger.info("Successfully wrote the new EPUB file.")

        except Exception as e:
            self.logger.error(f"EPUB file writing failed: {e}", exc_info=True)
            context.is_successful = False
            context.error_message = f"EPUB file writing failed: {e}"
            
        return context