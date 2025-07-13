# processors/book/html_to_chapter_processor.py

import logging
import re
from genai_processors import processor
from workflows.parts import TranslatedTextPart
from workflows.book.parts import TranslatedChapterPart
from format_converters.book_schema import Chapter
from format_converters.html_mapper import html_to_blocks

class HtmlToChapterProcessor(processor.PartProcessor):
    """
    一個將包含已翻譯 HTML 字符串的 TranslatedTextPart 反序列化為
    結構化的 TranslatedChapterPart 的處理器。
    """
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    def _clean_html_content(self, html_string: str) -> str:
        """
        清理 LLM 可能返回的額外文本或 Markdown 標記。
        """
        # 移除 Markdown 代码块标记
        cleaned_string = re.sub(r'^```[a-zA-Z]*\n', '', html_string.strip())
        cleaned_string = re.sub(r'\n```$', '', cleaned_string)
        
        # 嘗試找到 XML 聲明的起始位置
        xml_declaration_pos = cleaned_string.find('<?xml')
        if xml_declaration_pos != -1:
            return cleaned_string[xml_declaration_pos:]

        # 如果沒有 XML 聲明，嘗試找到 <html> 標籤的起始位置（不區分大小寫）
        html_tag_match = re.search(r'<html', cleaned_string, re.IGNORECASE)
        if html_tag_match:
            return cleaned_string[html_tag_match.start():]
        
        self.logger.warning("Could not find '<?xml' or '<html>' tag in the translated content. Assuming it's a clean fragment.")
        return cleaned_string

    def match(self, part: processor.ProcessorPart) -> bool:
        """只處理 TranslatedTextPart。"""
        return isinstance(part, TranslatedTextPart)

    async def call(self, part: TranslatedTextPart):
        """
        處理單個 TranslatedTextPart，將其 HTML 內容轉換回 Chapter 對象。
        """
        chapter_id = part.metadata.get("original_chapter_id", "unknown_chapter")
        try:
            self.logger.info(f"Deserializing HTML for chapter '{chapter_id}'...")
            
            # 1. 清理 LLM 返回的 HTML 字符串
            cleaned_html = self._clean_html_content(part.translated_text)

            # 2. 調用工具函數將 HTML 解析回 Block 列表
            # 【修復】從元數據中獲取 image_resources，以正確解析圖片路徑
            image_resources = part.metadata.get("image_resources", {})
            translated_blocks = html_to_blocks(cleaned_html, image_resources=image_resources, logger=self.logger)

            # 3. 根據原始元數據和翻譯後的 Block 重建 Chapter 對象
            translated_chapter = Chapter(
                id=chapter_id,
                title=part.metadata.get("original_chapter_title"), # title 可以是 None
                epub_type=part.metadata.get("original_chapter_epub_type"),
                internal_css=part.metadata.get("original_chapter_internal_css"),
                content=translated_blocks,
                # 【修復】確保 title_target 總是一個字符串，以滿足 Pydantic 驗證
                title_target=part.metadata.get("original_chapter_title") or ""
            )

            # 4. 產出包含新 Chapter 對象的 Part
            yield TranslatedChapterPart(
                translated_chapter=translated_chapter,
                metadata=part.metadata
            )
            self.logger.info(f"Successfully deserialized chapter '{chapter_id}'.")

        except Exception as e:
            self.logger.error(f"Error deserializing chapter {chapter_id}: {e}", exc_info=True)
            yield part