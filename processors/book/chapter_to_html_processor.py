# processors/book/chapter_to_html_processor.py

import logging
from bs4 import BeautifulSoup
from genai_processors import processor
from workflows.book.parts import ChapterPart
from workflows.parts import TranslationRequestPart
# 導入底層的映射函數
from format_converters.html_mapper import map_block_to_html

class ChapterToHtmlProcessor(processor.PartProcessor):
    """
    一個將結構化的 ChapterPart 序列化為包含 HTML 字符串的 
    TranslationRequestPart 的處理器。
    """
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    def _chapter_content_to_html(self, chapter) -> str:
        """
        一個輔助函數，將 Chapter 對象的 content (Block 列表) 轉換為 HTML 字符串。
        這是對 format_converters.html_mapper 中核心邏輯的直接使用。
        """
        if not chapter.content:
            return ""

        # 創建一個臨���的 BeautifulSoup 對象來構建 HTML
        soup = BeautifulSoup("", "html.parser")
        
        for block in chapter.content:
            # 調用核心的映射函數
            html_element = map_block_to_html(block, soup)
            if html_element:
                soup.append(html_element)
                
        # 返回 soup 中所有子元素的字符串表示
        return "".join(str(child) for child in soup.contents)

    def match(self, part: processor.ProcessorPart) -> bool:
        """只處理 ChapterPart。"""
        return isinstance(part, ChapterPart)

    async def call(self, part: ChapterPart):
        """
        處理單個 ChapterPart，將其內容轉換為 HTML 字符串。
        """
        try:
            chapter_id = part.chapter.id
            self.logger.info(f"Serializing chapter '{chapter_id}' to HTML...")
            
            # 調用輔助函數將 Chapter 對象的 content 轉換為 HTML
            html_string = self._chapter_content_to_html(part.chapter)
            html_len = len(html_string)
            
            # 關鍵日誌：如果 HTML 為空，我們需要一個明確的警告
            if html_len == 0:
                self.logger.warning(f"Chapter '{chapter_id}' serialized to an EMPTY HTML string. It will be skipped by the translator.")
            else:
                self.logger.info(f"Successfully serialized chapter '{chapter_id}'. HTML length: {html_len}")

            # 創建一個新的 TranslationRequestPart
            yield TranslationRequestPart(
                text_to_translate=html_string,
                source_lang=part.metadata.get("source_lang", "en"),
                target_lang=part.metadata.get("target_lang", "en"),
                metadata={
                    # 傳遞所有必要的元數據，以便後續可以重建 Chapter
                    "original_chapter_id": chapter_id,
                    "original_chapter_title": part.chapter.title,
                    "original_chapter_epub_type": part.chapter.epub_type,
                    "original_chapter_internal_css": part.chapter.internal_css,
                    **part.metadata
                }
            )

        except Exception as e:
            self.logger.error(f"Error serializing chapter {part.chapter.id}: {e}", exc_info=True)
            # 在出錯時，返回原始 part，以免數據流中斷
            yield part
