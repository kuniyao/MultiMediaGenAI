# llm_utils/translator.py

import logging
import asyncio
from typing import Optional

from genai_processors import processor
from workflows.parts import ApiRequestPart, TranslatedTextPart, TranslationRequestPart
from .gemini_client import GeminiClient
from .base_client import BaseLLMClient


class TranslatorProcessor(processor.PartProcessor):
    """
    一個接收 API 請求、調用 LLM 進行翻譯，並輸出翻譯結果的處理器。
    """

    def __init__(self, client: Optional[BaseLLMClient] = None, concurrency_limit: int = 5):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        # 如果沒有提供客戶端，則創建一個默認的 Gemini 客戶端
        self.client = client or GeminiClient(logger=self.logger)
        self.semaphore = asyncio.Semaphore(concurrency_limit)
        self._is_initialized = False

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
            # 重新引發異常，以便工作流可以捕獲它
            raise

    def match(self, part: processor.ProcessorPart) -> bool:
        """只處理 ApiRequestPart。"""
        return isinstance(part, ApiRequestPart)

    async def call(self, part: ApiRequestPart):
        """處理單個 ApiRequestPart。"""
        # 確保客戶端已初始化
        if not self._is_initialized:
            await self.initialize()

        async with self.semaphore:
            task_id = part.metadata.get("llm_processing_id", "N/A")
            self.logger.info(f"正在處理任務 (ID: {task_id})...")

            try:
                # 調用 LLM API
                response_text, _ = await self.client.call_api_async(
                    messages=part.messages,
                    task_id=task_id
                )
                
                # 提取原始文本，如果它存在於元數據中
                source_text = part.metadata.get("source_text", "")

                # 創建並返回包含結果的 Part
                yield TranslatedTextPart(
                    translated_text=response_text,
                    source_text=source_text, # 傳遞原始文本
                    metadata=part.metadata
                )

            except Exception as e:
                self.logger.error(f"任務 {task_id} 在 API 調用中遇到異常: {e}", exc_info=True)
                # 在失敗時，也創建一個 Part，但可能包含錯誤信息
                yield TranslatedTextPart(
                    translated_text=f"[TRANSLATION_FAILED]: {e}",
                    source_text=part.metadata.get("source_text", ""),
                    metadata=part.metadata
                )


class SimpleTranslator(processor.Processor):
    """
    一個簡化的翻譯器，直接接收 TranslationRequestPart，
    內部完成提示構建和翻譯。
    """
    def __init__(self, client: Optional[BaseLLMClient] = None):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.prompt_builder = PromptBuilderProcessor()
        self.translator = TranslatorProcessor(client=client)

    async def call(self, stream):
        # 1. 將 TranslationRequestPart 轉換為 ApiRequestPart
        # 因為 prompt_builder 現在是 PartProcessor，我們需要用 to_processor()
        api_request_stream = self.prompt_builder.to_processor()(stream)
        
        # 2. 將 ApiRequestPart 傳遞給翻��器
        # 同樣，translator 現在也是 PartProcessor
        translated_stream = self.translator.to_processor()(api_request_stream)
        
        # 3. 產出結果
        async for result in translated_stream:
            yield result

