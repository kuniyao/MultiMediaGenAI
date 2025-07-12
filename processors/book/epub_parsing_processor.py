import logging
from ebooklib import epub
from genai_processors import processor
from workflows.parts import TranslationRequestPart
from workflows.book.parts import EpubBookPart

class EpubParsingProcessor(processor.Processor):
    """
    一個接收 TranslationRequestPart，剖析其路徑指向的 EPUB 文件，
    並輸出一個 EpubBookPart 的處理器。
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def call(self, stream):
        """
        處理傳入的數據流。
        """
        async for part in stream:
            if not isinstance(part, TranslationRequestPart):
                self.logger.warning(f"EpubParsingProcessor received an unexpected part type: {type(part)}")
                yield part
                continue

            epub_path = part.text_to_translate
            self.logger.info(f"Starting EPUB parsing for: {epub_path}")

            try:
                # 使用 ebooklib 直接讀取和剖析 EPUB 文件
                book = epub.read_epub(epub_path)

                # 提取元數據
                title = "Untitled"
                if book.get_metadata('DC', 'title'):
                    title = book.get_metadata('DC', 'title')[0][0]

                author = "Unknown Author"
                if book.get_metadata('DC', 'creator'):
                    author = book.get_metadata('DC', 'creator')[0][0]

                # 提取章節，並過濾掉非內容文件 (如導航頁)
                chapters = []
                # 獲取書脊中定義的內容順序
                spine_ids = [item[0] for item in book.spine]
                
                for item in book.get_items_of_type(9): # 9 is a magic number for XHTML
                    # 只有在書脊中，並且不是導航文件的項目，才被視為章節
                    if item.get_id() in spine_ids and 'nav' not in item.get_name():
                        chapters.append({
                            "id": item.get_id(),
                            "file_name": item.get_name(),
                            "content": item.get_content().decode('utf-8', 'ignore')
                        })
                
                self.logger.info(f"Successfully parsed EPUB. Title: '{title}'. Found {len(chapters)} chapters.")

                # 產生包含書籍資訊的 Part
                yield EpubBookPart(
                    title=title,
                    author=author,
                    chapters=chapters,
                    metadata=part.metadata # 傳遞原始的元數據
                )

            except Exception as e:
                self.logger.error(f"EPUB parsing failed for {epub_path}: {e}", exc_info=True)
                # 在這裡可以選擇產生一個 ErrorPart