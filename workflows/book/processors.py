# workflows/book/processors.py

import logging
from genai_processors import processor
from workflows.book.parts import ChapterPart
from workflows.parts import TranslationRequestPart

class ChapterToTranslationRequestProcessor(processor.Processor):
    """
    一個 "適配器" 處理器，將 ChapterPart 轉換為 TranslationRequestPart。
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def call(self, stream):
        """
        處理傳入的數據流。
        """
        async for part in stream:
            if not isinstance(part, ChapterPart):
                self.logger.warning(f"Adapter received an unexpected part type: {type(part)}")
                yield part
                continue

            try:
                # 從 ChapterPart 的元數據中提取 source_lang 和 target_lang
                # 我們假設這些資訊是從最一開始的 Part 一路傳遞下來的
                source_lang = part.metadata.get("source_lang", "en")
                target_lang = part.metadata.get("target_lang", "en")

                # 創建一個新的 TranslationRequestPart
                # text_to_translate 的內容是章節的 HTML
                yield TranslationRequestPart(
                    text_to_translate=part.html_content,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    # 將 ChapterPart 的所有元數據都傳遞下去
                    metadata=part.metadata
                )
            except Exception as e:
                self.logger.error(f"Error in adapter processor: {e}", exc_info=True)
