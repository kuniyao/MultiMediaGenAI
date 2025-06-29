import os
import logging
import json
import asyncio
from typing import Optional
from pathlib import Path

from data_sources.epub_source import EpubSource
from format_converters.epub_writer import book_to_epub
from llm_utils.book_processor import extract_translatable_chapters, apply_translations_to_book
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
                 output_dir: str):
        self.data_source = data_source
        self.target_lang = target_lang
        self.concurrency = concurrency
        self.prompts_path = prompts_path
        self.glossary_path = glossary_path
        self.logger = logger
        self.prompts = {}
        self.glossary = None
        self.output_manager = OutputManager(output_dir, self.logger)

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

        # 1. 解析 EPUB (通过数据源)
        self.logger.info(f"Loading and parsing EPUB file: {self.data_source.source}...")
        try:
            book = self.data_source.get_data()
        except Exception as e:
            self.logger.error(f"Error parsing EPUB: {e}", exc_info=True)
            return
        self.logger.info("Parsing complete.")

        # 2. 提取可翻译章节
        self.logger.info("Extracting translatable chapters...")
        translatable_chapters = extract_translatable_chapters(book, logger=self.logger)
        if not translatable_chapters:
            self.logger.info("No translatable chapters found in this EPUB. Workflow terminated.")
            return
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
        
        # Use output_manager for raw LLM log directory
        raw_llm_log_dir = self.output_manager.get_workflow_output_path("epub_llm_logs", "raw_logs")
        raw_llm_log_dir.mkdir(parents=True, exist_ok=True) # Ensure the directory exists

        translated_results = await execute_translation_async(
            tasks_to_translate=tasks_for_translator,
            source_lang_code=source_lang,
            target_lang=self.target_lang,
            raw_llm_log_dir=str(raw_llm_log_dir), # Pass the correct argument for logging
            logger=self.logger,
            concurrency=self.concurrency,
            glossary=self.glossary
        )

        if not translated_results:
            self.logger.error("Translation process failed or returned no results. Workflow terminated.")
            return
        self.logger.info(f"Successfully received {len(translated_results)} results from the translator.")

        # 4. 应用翻译结果
        self.logger.info("Applying translations to create a new Book object...")
        translated_book = apply_translations_to_book(
            original_book=book,
            translated_results=translated_results,
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
        except Exception as e:
            self.logger.error(f"Error generating new EPUB file: {e}", exc_info=True)
            return
            
        self.logger.info("\n" + "="*50)
        self.logger.info("Workflow execution successful!")
        self.logger.info(f"New EPUB file saved to: {output_path}")
        self.logger.info("="*50) 