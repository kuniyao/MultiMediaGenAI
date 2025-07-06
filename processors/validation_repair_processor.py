import logging
from .base_processor import BaseProcessor
from workflows.dto import PipelineContext
# 导入你现有的、功能强大的核心函数
from llm_utils.book_processor import validate_and_extract_fixes

class ValidationAndRepairProcessor(BaseProcessor):
    """
    处理器第四步：验证初翻结果，找出“漏翻”的块，并生成一个修复任务列表。
    它扮演着“质检员”的角色。
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def process(self, context: PipelineContext) -> PipelineContext:
        """
        接收包含 original_book 和 translated_results 的上下文，
        返回一个可能填充了 repair_tasks 的新上下文。
        """
        new_context = context.model_copy(deep=True)

        # 如果前序步骤失败，或没有原始书籍或翻译结果，则跳过此步骤
        if not new_context.is_successful or not new_context.original_book or not new_context.translated_results:
            if new_context.is_successful:
                 self.logger.info("Skipping validation as there are no translation results.")
            return new_context

        self.logger.info("Validating initial translation to find missed translations...")
        try:
            # 1. 从“货箱”中取出需要的“原材料”
            original_book = new_context.original_book
            translated_results = new_context.translated_results
            
            # image_resources 是 html_to_blocks 函数需要的参数
            image_resources = original_book.image_resources if original_book else {}

            # 2. 调用【现有】的核心功能函数
            # 这个函数会执行所有复杂的对比和提取逻辑
            repair_tasks = validate_and_extract_fixes(
                original_book=original_book,
                translated_results=translated_results,
                image_resources=image_resources,
                logger=self.logger
            )

            # 3. 将产出的“返工清单”（修复任务）放回“货箱”
            new_context.repair_tasks = repair_tasks
            
            if repair_tasks:
                self.logger.warning(f"Validation complete. Found {len(repair_tasks)} task(s) that need repair.")
            else:
                self.logger.info("Validation complete. No missed translations found.")

        except Exception as e:
            self.logger.error(f"Validation and repair preparation failed: {e}", exc_info=True)
            new_context.is_successful = False
            new_context.error_message = f"Validation and repair preparation failed: {e}"
            
        return new_context