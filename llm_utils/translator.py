# llm_utils/translator.py

import logging
import asyncio
from typing import Optional

from genai_processors import processor
from workflows.parts import ApiRequestPart, TranslatedTextPart, TranslationRequestPart
from .gemini_client import GeminiClient
from .base_client import BaseLLMClient


class TranslatorProcessor(processor.Processor):
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

    async def _translate_task(self, part: ApiRequestPart) -> TranslatedTextPart:
        """執行單個翻譯任務的核心邏輯。"""
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
                return TranslatedTextPart(
                    translated_text=response_text,
                    source_text=source_text, # 傳遞原始文本
                    metadata=part.metadata
                )

            except Exception as e:
                self.logger.error(f"任務 {task_id} 在 API 調用中遇到異常: {e}", exc_info=True)
                # 在失敗時，也創建一個 Part，但可能包含錯誤信息
                return TranslatedTextPart(
                    translated_text=f"[TRANSLATION_FAILED]: {e}",
                    source_text=part.metadata.get("source_text", ""),
                    metadata=part.metadata
                )

    async def call(self, stream):
        """處理傳入的 ApiRequestPart 流。"""
        # 在處理第一個 part 之前確保客戶端已初始化
        if not self._is_initialized:
            await self.initialize()

        # 創建一組並發執行的翻譯任務
        translation_tasks = []
        async for part in stream:
            if isinstance(part, ApiRequestPart):
                # 為每個 part 創建一個協程任務
                task = asyncio.create_task(self._translate_task(part))
                translation_tasks.append(task)
        
        # 等待所有翻譯任務完成
        for task in asyncio.as_completed(translation_tasks):
            # 當任務完成時，獲取結果並將其傳遞下去
            result_part = await task
            yield result_part
