import logging
from ..base_processor import BaseProcessor
from workflows.dto import PipelineContext
from data_sources.epub_source import EpubSource

class EpubParsingProcessor(BaseProcessor):
    """
    处理器第一步：解析输入的EPUB文件，构建一个包含 mmg_id 的 Book 对象。
    这个处理器封装了所有的文件读取和初始解析逻辑。
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def process(self, context: PipelineContext) -> PipelineContext:
        """
        接收包含 source_input 的上下文，返回填充了 original_book 的新上下文。
        """
        # 函数式风格：不修改输入的context，而是创建一个副本
        new_context = context.model_copy(deep=True)

        # 契约检查：如果流程已失败，则直接传递，不执行任何操作
        if not new_context.is_successful:
            return new_context

        self.logger.info(f"Starting EPUB parsing for: {new_context.source_input}")
        try:
            # 1. 实例化 EPUB 的数据源专家
            # 注意：我们将日志记录器传递给了数据源，以便于追踪更深层次的问题
            data_source = EpubSource(new_context.source_input, self.logger)

            # 2. 调用【现有】的核心功能来获取 Book 对象
            # data_source.get_book() 内部会调用 EpubParser，完成所有复杂的解析工作
            book = data_source.get_book()

            # 3. 将产出的核心“零件”(Book对象) 和相关元数据放回“货箱”
            new_context.original_book = book
            new_context.source_metadata = book.metadata.model_dump() # 使用Pydantic的model_dump获取字典
            new_context.source_lang = book.metadata.language_source

            self.logger.info(f"Successfully parsed EPUB. Title: '{book.metadata.title_source}'.")

        except Exception as e:
            self.logger.error(f"EPUB parsing failed: {e}", exc_info=True)
            new_context.is_successful = False
            new_context.error_message = f"EPUB parsing failed: {e}"
            
        return new_context