import os
import logging
import json
import asyncio
from typing import Optional
from pathlib import Path

from data_sources.epub_source import EpubSource
from format_converters.epub_writer import book_to_epub
from llm_utils.book_processor import extract_translatable_chapters, apply_translations_to_book, validate_and_extract_fixes
from llm_utils.translator import execute_translation_async
from common_utils.output_manager import OutputManager

class EpubOrchestrator:
    def __init__(self, 
                 data_source: EpubSource, 
                 target_lang: str, 
                 concurrency: int, 
                 prompts_path: str, 
                 glossary_path: Optional[str], 
                 logger: logging.Logger,
                 output_dir: str,
                 save_llm_logs: bool = False,
                 max_chapters: Optional[int] = None):
        self.data_source = data_source
        self.target_lang = target_lang
        self.concurrency = concurrency
        self.prompts_path = prompts_path
        self.glossary_path = glossary_path
        self.logger = logger
        self.prompts = {}
        self.glossary = None
        self.output_manager = OutputManager(output_dir, self.logger)
        self.save_llm_logs = save_llm_logs
        self.max_chapters = max_chapters
        self._collected_llm_logs = [] # Initialize list to collect LLM logs

    def _load_resources(self):
        """加载 prompts 和术语表."""
        if os.path.exists(self.prompts_path):
            self.logger.info(f"Loading prompts from {self.prompts_path}...")
            with open(self.prompts_path, 'r', encoding='utf-8') as f:
                self.prompts = json.load(f)
        else:
            self.logger.error(f"Prompts file not found at {self.prompts_path}. Aborting.")
            raise FileNotFoundError(f"Prompts file not found: {self.prompts_path}")

        if self.glossary_path:
            if os.path.exists(self.glossary_path):
                self.logger.info(f"Loading glossary from {self.glossary_path}...")
                with open(self.glossary_path, 'r', encoding='utf-8') as f:
                    self.glossary = json.load(f)
            else:
                self.logger.warning(f"Glossary file specified but not found at {self.glossary_path}. Proceeding without a glossary.")

    async def run(self):
        """执行完整的EPUB翻译流程."""
        self.logger.info("Starting EPUB translation workflow...")
        self._load_resources()

        translation_successful = True # Initialize to True, set to False on failure conditions

        # 1. 解析 EPUB (通过数据源)
        self.logger.info(f"Loading and parsing EPUB file: {self.data_source.source}...")
        try:
            book = self.data_source.get_data()
        except Exception as e:
            self.logger.error(f"Error parsing EPUB: {e}", exc_info=True)
            translation_successful = False
            # Always save LLM logs on unexpected errors
            self._save_llm_logs_to_file(self._collected_llm_logs, self.target_lang)
            return
        self.logger.info("Parsing complete.")

        # 2. 提取可翻译章节
        self.logger.info("Extracting translatable chapters...")
        translatable_chapters = extract_translatable_chapters(book, logger=self.logger)
        if not translatable_chapters:
            self.logger.info("No translatable chapters found in this EPUB. Workflow terminated.")
            return
        
        if self.max_chapters and self.max_chapters > 0:
            self.logger.info(f"Limiting translation to the first {self.max_chapters} chapters as requested.")
            translatable_chapters = translatable_chapters[:self.max_chapters]

        self.logger.info(f"Extracted {len(translatable_chapters)} translatable chapter tasks.")

        tasks_for_translator = [
            {
                "llm_processing_id": chapter_task["llm_processing_id"],
                "text_to_translate": chapter_task["text_to_translate"],
                "source_data": chapter_task["source_data"]
            }
            for chapter_task in translatable_chapters
        ]
        
        # 3. 执行翻译
        self.logger.info("Calling advanced asynchronous translation function...")
        source_lang = book.metadata.language_source if book.metadata.language_source else "en"
        
        initial_translated_results, initial_llm_logs = await execute_translation_async(
            tasks_to_translate=tasks_for_translator,
            source_lang_code=source_lang,
            target_lang=self.target_lang,
            logger=self.logger,
            concurrency=self.concurrency,
            glossary=self.glossary
        )
        self._collected_llm_logs.extend(initial_llm_logs)

        if not initial_translated_results:
            self.logger.error("Initial translation failed or returned no results. Workflow terminated.")
            translation_successful = False
            # Save LLM logs on failure if option is enabled
            if self.save_llm_logs:
                self._save_llm_logs_to_file(self._collected_llm_logs, self.target_lang)
            return
        self.logger.info(f"Successfully received {len(initial_translated_results)} results from the initial translation round.")

        # --- 【新增步骤 3.5: 验证和修复】 ---
        repair_tasks = validate_and_extract_fixes(
            original_book=book,
            translated_results=initial_translated_results,
            image_resources=book.image_resources,
            logger=self.logger
        )

        final_results = initial_translated_results

        if repair_tasks:
            self.logger.info(f"Proceeding with a repair round for {len(repair_tasks)} task(s).")
            
            repair_results, repair_llm_logs = await execute_translation_async(
                tasks_to_translate=repair_tasks,
                source_lang_code=source_lang,
                target_lang=self.target_lang,
                logger=self.logger,
                concurrency=self.concurrency, # 可以为修复任务设置较低的并发数
                glossary=self.glossary
            )
            self._collected_llm_logs.extend(repair_llm_logs)

            if repair_results:
                self.logger.info("Repair round completed. Merging results.")
                final_results.extend(repair_results)
            else:
                self.logger.warning("Repair round did not return any results. Proceeding with initial translations only.")
        # --- 【新增步骤结束】 ---

        # 4. 应用翻译结果
        self.logger.info("Applying translations to create a new Book object...")
        translated_book = apply_translations_to_book(
            original_book=book,
            # 【修改】使用合并后的最终结果
            translated_results=final_results, 
            logger=self.logger
        )
        
        if translated_book.metadata.title_source:
             title_map = {"zh-CN": "【中文翻译】", "ja": "【日本語訳】"}
             prefix = title_map.get(self.target_lang, f"[{self.target_lang}] ")
             translated_book.metadata.title_target = prefix + translated_book.metadata.title_source
        translated_book.metadata.language_target = self.target_lang
        self.logger.info("Metadata updated for the new book.")

        # 5. 生成新的 EPUB 文件
        file_name, file_ext = os.path.splitext(os.path.basename(self.data_source.source))
        lang_suffix = self.target_lang.replace('-', '_')
        output_filename = f"{file_name}_{lang_suffix}{file_ext}"
        
        output_path = self.output_manager.get_workflow_output_path("epub_translated", output_filename)

        self.logger.info(f"Writing updated Book object to new EPUB file: {output_path}...")
        try:
            book_to_epub(translated_book, str(output_path))
            translation_successful = True
        except Exception as e:
            self.logger.error(f"Error generating new EPUB file: {e}", exc_info=True)
            translation_successful = False
            return
            
        self.logger.info("\n" + "="*50)
        self.logger.info("Workflow execution successful!")
        self.logger.info(f"New EPUB file saved to: {output_path}")
        self.logger.info("="*50)

        # Save LLM logs based on success/failure and save_llm_logs flag
        if not translation_successful or self.save_llm_logs:
            self._save_llm_logs_to_file(self._collected_llm_logs, self.target_lang)

    def _save_llm_logs_to_file(self, llm_logs: list[str], target_lang: str):
        if not llm_logs:
            self.logger.info("No LLM logs collected to save.")
            return

        log_file_name = f"llm_raw_responses_{target_lang.lower().replace('-', '').replace('_', '')}.jsonl"
        log_file_path = self.output_manager.get_workflow_output_path("llm_logs", log_file_name)
        
        try:
            with open(log_file_path, 'w', encoding='utf-8') as f:
                for log_entry in llm_logs:
                    f.write(log_entry + '\n')
            self.logger.info(f"LLM raw response logs saved to: {log_file_path}")
        except Exception as e:
            self.logger.error(f"Failed to save LLM raw response logs to {log_file_path}: {e}", exc_info=True) 