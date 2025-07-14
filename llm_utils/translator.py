# llm_utils/translator.py

import logging
import asyncio
from typing import Optional

from genai_processors import processor
from workflows.book.parts import BatchTranslationTaskPart, SplitChapterTaskPart
from workflows.parts import TranslatedTextPart
from .gemini_client import GeminiClient
from .base_client import BaseLLMClient
from .prompt_builder import PromptBuilder

class TranslatorProcessor(processor.PartProcessor):
    """
    一個多功能翻譯器，它接收不同類型的翻譯任務Part，
    為其構建合適的提示，調用LLM進行翻譯，並輸出翻譯結果。
    【新】: 它還會將所有成功的翻譯結果緩存起來，供其他處理器查詢。
    """

    def __init__(self, client: Optional[BaseLLMClient] = None, concurrency_limit: int = 5):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.client = client or GeminiClient(logger=self.logger)
        self.semaphore = asyncio.Semaphore(concurrency_limit)
        self._is_initialized = False
        self.llm_responses: list[TranslatedTextPart] = [] # 【新】增加緩存列表

    async def initialize(self):
        """異步初始化底層的 LLM 客戶端。"""
        if self._is_initialized:
            return
        try:
            self.logger.info(f"正在初始化 {self.client.__class__.__name__}...")
            await self.client.initialize()
            self._is_initialized = True
            self.logger.info(f"{self.client.__class__.__name__} 初始化成功。")
        except Exception as e:
            self.logger.critical(f"初始化 LLM 客戶端失敗: {e}", exc_info=True)
            raise

    def match(self, part: processor.ProcessorPart) -> bool:
        """【變更】: 現在可以處理多種翻譯任務 Part。"""
        return isinstance(part, (BatchTranslationTaskPart, SplitChapterTaskPart))

    async def call(self, part: processor.ProcessorPart):
        """
        處理單個任務 Part，根據其類型��擇不同的處理邏輯。
        """
        if not self._is_initialized:
            await self.initialize()

        task_type = ""
        text_to_translate = ""
        
        # 1. 根據 Part 類型準備不同的參數
        if isinstance(part, BatchTranslationTaskPart):
            task_type = 'json_batch'
            text_to_translate = part.json_string
            self.logger.debug(f"Received batch task with {part.chapter_count} chapters.")
        elif isinstance(part, SplitChapterTaskPart):
            task_type = 'text_file' # 對於單個HTML塊，我們使用通用的文本文件提示
            text_to_translate = part.html_content
            self.logger.debug(f"Received split chapter task: part #{part.part_number} for chapter '{part.original_chapter_id}'.")

        if not text_to_translate.strip():
            self.logger.warning(f"Task input for {part.metadata.get('llm_processing_id')} is empty, skipping translation.")
            yield TranslatedTextPart(translated_text="", source_text="", metadata=part.metadata)
            return

        # 2. 構建提示
        prompt_builder = PromptBuilder(
            source_lang=part.metadata.get("source_lang", "en"),
            target_lang=part.metadata.get("target_lang", "zh-CN")
        )
        messages = prompt_builder.build_messages(
            task_type=task_type,
            task_string=text_to_translate
        )

        # 3. 調用 API
        translated_text = "[TRANSLATION_FAILED]: Unknown error"
        try:
            async with self.semaphore:
                response_text, _ = await self.client.call_api_async(
                    messages=messages,
                    task_id=str(part.metadata.get("llm_processing_id", "N/A"))
                )
                translated_text = response_text
        except Exception as e:
            self.logger.error(f"任務在 API 調用中遇到異常: {e}", exc_info=True)
            translated_text = f"[TRANSLATION_FAILED]: {e}"

        # 4. 產出統一的結果 Part
        output_metadata = part.metadata.copy() # 複製基礎元數據
        output_metadata['type'] = task_type    # 注入我們自己的類型

        # 如果是切分任務，需要確保關鍵的ID和編號信息被傳遞下去
        if isinstance(part, SplitChapterTaskPart):
            output_metadata['original_chapter_id'] = part.original_chapter_id
            output_metadata['part_number'] = part.part_number
            output_metadata['injected_heading'] = part.injected_heading

        result_part = TranslatedTextPart(
            translated_text=translated_text,
            source_text=text_to_translate,
            metadata=output_metadata
        )
        
        # 【新】將結果存入緩存
        self.llm_responses.append(result_part)
        
        yield result_part