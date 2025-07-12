import logging
from genai_processors import processor
from workflows.parts import TranslatedTextPart
from workflows.book.parts import TranslatedBookPart

class BookBuildProcessor(processor.Processor):
    """
    一個接收 TranslatedTextPart 流，將它們組裝成一本書，
    並在流結束時輸出一個 TranslatedBookPart 的處理器。
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def call(self, stream):
        """
        處理傳入的數據流。
        """
        translated_chapters = []
        book_metadata = {}
        
        # 1. 收集所有翻譯完的章節
        async for part in stream:
            if not isinstance(part, TranslatedTextPart):
                self.logger.warning(f"BookBuildProcessor received an unexpected part type: {type(part)}")
                # 如果我們不想處理它，可以選擇直接將其傳遞下去
                # yield part
                continue

            # 從第一個 Part 中獲取書籍的元數據
            if not book_metadata:
                book_metadata = part.metadata
            
            # 將翻譯結果添加到列表中
            translated_chapters.append({
                "id": part.metadata.get("chapter_id", "unknown_id"),
                "title": part.metadata.get("title", "Untitled Chapter"),
                "translated_content": part.translated_text
            })

        # 2. 當流結束時，如果我們收集到了章節，就創建並產生 TranslatedBookPart
        if translated_chapters:
            self.logger.info(f"Building translated book: {book_metadata.get('book_title', 'Untitled')}")
            
            # 創建一個新的 Part 來代表整本翻譯完的書
            yield TranslatedBookPart(
                title=book_metadata.get("book_title", "Untitled"),
                author=book_metadata.get("book_author", "Unknown Author"),
                translated_chapters=translated_chapters,
                metadata=book_metadata # 傳遞所有收集到的元數據
            )
            self.logger.info("Successfully built and yielded TranslatedBookPart.")
