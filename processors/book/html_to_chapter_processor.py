# processors/book/html_to_chapter_processor.py

import logging
import re
import json
from genai_processors import processor
from workflows.parts import TranslatedTextPart
from workflows.book.parts import TranslatedChapterPart
from format_converters.book_schema import Chapter
from format_converters.html_mapper import html_to_blocks, parse_html_body_content

class HtmlToChapterProcessor(processor.PartProcessor):
    """
    一個將包含已翻譯 HTML 字符串的 TranslatedTextPart 反序列化為
    結構化的 TranslatedChapterPart 的處理器。
    它現在可以處理來自批處理或單塊翻譯的結果。
    """
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    def _clean_html_content(self, html_string: str) -> str:
        """清理 LLM 可能返回的額外文本或 Markdown 標記。"""
        # 策略一：使用正則表達式尋找被Markdown包裹的JSON或HTML代碼塊
        match = re.search(r'```(?:json|html)?\s*([\s\S]*?)\s*```', html_string, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # 策略二：如果沒有找到代碼塊，則假定它是一個乾淨的片段
        return html_string.strip()

    def match(self, part: processor.ProcessorPart) -> bool:
        """只處理 TranslatedTextPart。"""
        return isinstance(part, TranslatedTextPart)

    async def call(self, part: TranslatedTextPart):
        """
        處理單個 TranslatedTextPart，將其 HTML 內容轉換回 Chapter 對象。
        """
        source_metadata = part.metadata
        task_type = source_metadata.get("type")

        # 情況一：處理來自批處理任務的結果
        if task_type == "json_batch":
            self.logger.info("Processing a batch translation result...")
            try:
                cleaned_json_str = self._clean_html_content(part.translated_text)
                translated_chapters_data = json.loads(cleaned_json_str)
                
                for chapter_data in translated_chapters_data:
                    chapter_id = chapter_data.get("id")
                    html_content = chapter_data.get("html_content", "")
                    if not chapter_id:
                        self.logger.warning("Found a chapter in batch without an 'id'. Skipping.")
                        continue
                    
                    blocks = html_to_blocks(html_content, source_metadata.get("image_resources", {}), self.logger)
                    
                    # 【關鍵修復】: 為每個從批處理中解析出的章節，創建一個新的、獨立的Part
                    new_metadata = source_metadata.copy()
                    new_metadata["type"] = "batch_item" # 標記它的來源
                    new_metadata["original_chapter_id"] = chapter_id # 注入ID

                    yield TranslatedChapterPart(
                        translated_chapter=Chapter(id=chapter_id, content=blocks),
                        metadata=new_metadata
                    )
                self.logger.info(f"Successfully deserialized {len(translated_chapters_data)} chapters from batch.")

            except json.JSONDecodeError:
                self.logger.error(f"Failed to decode JSON from batch result. Raw text: {part.translated_text}", exc_info=True)
        
        # 情況二：處理來自單個（可能是切分的）章節塊的結果
        elif task_type == "text_file":
            original_chapter_id = source_metadata.get("original_chapter_id")
            if not original_chapter_id:
                self.logger.error(f"Received a single part task without 'original_chapter_id' in metadata. Skipping. Metadata: {source_metadata}")
                return

            self.logger.info(f"Processing a single/split chapter result for '{original_chapter_id}'...")
            
            cleaned_html = self._clean_html_content(part.translated_text)
            if cleaned_html and not cleaned_html.strip().startswith('<'):
                self.logger.warning(f"Content for '{original_chapter_id}' appears to be plain text. Wrapping in <p> tags.")
                cleaned_html = f"<p>{cleaned_html.strip()}</p>"

            blocks = html_to_blocks(cleaned_html, source_metadata.get("image_resources", {}), self.logger)
            
            yield TranslatedChapterPart(
                translated_chapter=Chapter(id=original_chapter_id, content=blocks),
                metadata=source_metadata
            )
        else:
            self.logger.warning(f"HtmlToChapterProcessor received a TranslatedTextPart with an unknown task type: '{task_type}'. Skipping.")
