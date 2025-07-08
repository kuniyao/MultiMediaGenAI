import logging
import asyncio
from ..base_processor import BaseProcessor
from workflows.dto import PipelineContext
from llm_utils.translator import execute_translation_async

class BookTranslationProcessor(BaseProcessor):
    """
    处理器第三步：执行核心的初翻任务。
    它接收翻译任务列表，并调用LLM进行翻译。
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    # 这个处理器是异步的，因为它直接调用了异步的翻译函数
    async def process(self, context: PipelineContext) -> PipelineContext:
        """
        接收包含 translation_tasks 的上下文，返回填充了 translated_results 的新上下文。
        """
        new_context = context.model_copy(deep=True)

        if not new_context.is_successful or not new_context.translation_tasks:
            if new_context.is_successful and not new_context.translation_tasks:
                 self.logger.info("No translation tasks found. Skipping translation.")
            return new_context

        self.logger.info(f"Starting translation for {len(new_context.translation_tasks)} tasks...")
        try:
            # 1. 从“货箱”中取出执行翻译所需的所有信息
            tasks = new_context.translation_tasks
            source_lang = new_context.source_lang or "en" # 如果未指定，则默认为英语
            target_lang = new_context.target_lang
            concurrency = new_context.concurrency
            glossary = new_context.glossary

            # 2. 调用【现有】的核心翻译函数
            # 这是与LLM API交互的核心步骤
            translated_results, llm_logs = await execute_translation_async(
                tasks_to_translate=tasks,
                source_lang_code=source_lang,
                target_lang=target_lang,
                logger=self.logger,
                concurrency=concurrency,
                glossary=glossary
            )

            if not translated_results:
                raise RuntimeError("Translation execution returned no results.")

            # 3. 将产出的“零件”（翻译结果和日志）放回“货箱”
            new_context.translated_results = translated_results
            new_context.llm_logs.extend(llm_logs)
            self.logger.info(f"Successfully received {len(translated_results)} results from the translation round.")

        except Exception as e:
            self.logger.error(f"Book translation failed: {e}", exc_info=True)
            new_context.is_successful = False
            new_context.error_message = f"Book translation failed: {e}"
            
        return new_context