import logging
from ..base_processor import BaseProcessor
from workflows.dto import PipelineContext
# 导入你现有的、功能强大的核心函数
from llm_utils.book_processor import extract_translatable_chapters

class ChapterExtractionProcessor(BaseProcessor):
    """
    处理器第二步：从 Book 对象中提取可翻译的内容，并智能打包成翻译任务。
    它封装了拆分大章节和批处理小章节的复杂逻辑。
    """
    def __init__(self, logger: logging.Logger, max_chapters: int = None):
        self.logger = logger
        self.max_chapters = max_chapters # 用于测试时限制章节数量

    def process(self, context: PipelineContext) -> PipelineContext:
        """
        接收包含 original_book 的上下文，返回填充了 translation_tasks 的新上下文。
        """
        new_context = context.model_copy(deep=True)

        if not new_context.is_successful or not new_context.original_book:
            return new_context

        self.logger.info("Extracting translatable chapters into tasks...")
        try:
            # 1. 从“货箱”中取出 Book 对象
            book = new_context.original_book
            
            # 2. 调用【现有】的核心功能函数
            # 这个函数内部已经包含了所有智能拆分和打包的逻辑
            translatable_tasks = extract_translatable_chapters(book, self.logger)

            if not translatable_tasks:
                self.logger.warning("No translatable content found in the book. The pipeline will finish early.")
                # 这不是一个硬性错误，只是说明书是空的，所以我们让流程继续，它会在后续步骤自然结束。
                return new_context

            # (可选) 根据用户运行时提供的参数，截取需要翻译的任务数量，这在调试时非常有用
            if self.max_chapters and self.max_chapters > 0:
                self.logger.info(f"Limiting translation to the first {self.max_chapters} tasks as requested.")
                translatable_tasks = translatable_tasks[:self.max_chapters]

            # 3. 将产出的任务列表放回“货箱”
            new_context.translation_tasks = translatable_tasks
            self.logger.info(f"Successfully extracted and prepared {len(translatable_tasks)} translation task(s).")

        except Exception as e:
            self.logger.error(f"Chapter extraction failed: {e}", exc_info=True)
            new_context.is_successful = False
            new_context.error_message = f"Chapter extraction failed: {e}"
            
        return new_context