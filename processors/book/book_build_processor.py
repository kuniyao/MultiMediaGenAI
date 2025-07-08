import logging
import asyncio
from ..base_processor import BaseProcessor
from workflows.dto import PipelineContext
# 导入你现有的、功能强大的核心函数
from llm_utils.book_processor import apply_translations_to_book
# 【新】我们还需要一个翻译器来处理修复任务
from llm_utils.translator import execute_translation_async


class BookBuildProcessor(BaseProcessor):
    """
    处理器第五步：应用所有翻译结果，构建最终的 Book 对象。
    它负责处理修复任务，并将所有结果合并到最终的书中。
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        
    # 这个处理器包含一个可选的异步API调用，所以我们将它设为异步
    async def process(self, context: PipelineContext) -> PipelineContext:
        """
        接收包含原始书籍、初翻结果和修复任务的上下文，
        返回填充了 translated_book 的新上下文。
        """
        new_context = context.model_copy(deep=True)

        if not new_context.is_successful or not new_context.original_book:
            return new_context

        self.logger.info("Building final translated Book object...")
        try:
            # --- 1. 处理修复任务 (如果存在) ---
            final_results = new_context.translated_results # 从初翻结果开始
            
            if new_context.repair_tasks:
                self.logger.info(f"Executing repair round for {len(new_context.repair_tasks)} task(s).")
                
                # 调用核心翻译函数，但只针对修复任务
                repair_results, repair_llm_logs = await execute_translation_async(
                    tasks_to_translate=new_context.repair_tasks,
                    source_lang_code=new_context.source_lang or "en",
                    target_lang=new_context.target_lang,
                    logger=self.logger,
                    concurrency=new_context.concurrency,
                    glossary=new_context.glossary
                )
                
                new_context.llm_logs.extend(repair_llm_logs)

                if repair_results:
                    self.logger.info("Repair round completed. Merging results.")
                    # 将修复结果合并到总结果列表中
                    final_results.extend(repair_results)
                else:
                    self.logger.warning("Repair round did not return any results. Proceeding with initial translations only.")

            # --- 2. 应用所有翻译结果 ---
            self.logger.info("Applying all translated results to create the final Book object...")
            
            # 调用【现有】的核心功能函数来完成复杂的组装工作
            translated_book = apply_translations_to_book(
                original_book=new_context.original_book,
                translated_results=final_results, 
                logger=self.logger
            )
            
            # --- 3. 更新书籍元数据 ---
            if translated_book.metadata.title_source:
                title_map = {"zh-CN": "【中文翻译】", "ja": "【日本語訳】"}
                prefix = title_map.get(new_context.target_lang, f"[{new_context.target_lang}] ")
                translated_book.metadata.title_target = prefix + translated_book.metadata.title_source
            translated_book.metadata.language_target = new_context.target_lang
            self.logger.info("Metadata updated for the new translated book.")

            # --- 4. 将最终成品放回“货箱” ---
            new_context.translated_book = translated_book

        except Exception as e:
            self.logger.error(f"Failed during final book build process: {e}", exc_info=True)
            new_context.is_successful = False
            new_context.error_message = f"Book build process failed: {e}"
            
        return new_context