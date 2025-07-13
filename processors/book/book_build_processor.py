import logging
from copy import deepcopy
from genai_processors import processor
from workflows.book.parts import TranslatedChapterPart, TranslatedBookPart, EpubBookPart
from format_converters.book_schema import Book

class BookBuildProcessor(processor.Processor):
    """
    一個接收 TranslatedChapterPart 流，將它們重新組裝成一本完整的書，
    並在流結束時輸出一個 TranslatedBookPart 的處理器。
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._original_book_structure: Book | None = None

    async def call(self, stream):
        """
        處理傳入的數據流，收集所有已翻譯的章節。
        """
        translated_chapters_map = {}
        
        async for part in stream:
            # 捕獲原始的 EpubBookPart 以獲取書籍結構
            if isinstance(part, EpubBookPart):
                self.logger.info("BookBuildProcessor captured the original book structure.")
                # 我們需要一個深拷貝，因為我們將修改其內容
                self._original_book_structure = deepcopy(part.book)
                continue

            if not isinstance(part, TranslatedChapterPart):
                self.logger.warning(f"BookBuildProcessor received an unexpected part type: {type(part)}")
                continue
            
            # 按章節 ID 存儲已翻譯的章節對象
            chapter = part.translated_chapter
            translated_chapters_map[chapter.id] = chapter
            self.logger.info(f"Collected translated chapter: {chapter.id}")

        # 當流結束時，如果我們有原始書籍結構和已翻譯的章節，就開始構建
        if self._original_book_structure and translated_chapters_map:
            self.logger.info("All translated chapters received. Building final book object...")
            
            final_book = self._original_book_structure
            
            # 用翻譯後的章節替換原始書籍結構中的章節
            final_chapters = []
            for original_chapter in final_book.chapters:
                if original_chapter.id in translated_chapters_map:
                    final_chapters.append(translated_chapters_map[original_chapter.id])
                else:
                    # 如果某個章節由於某種原因沒有被翻譯，保留原始章節
                    self.logger.warning(f"Chapter '{original_chapter.id}' was not found in translated parts. Keeping original.")
                    final_chapters.append(original_chapter)
            
            final_book.chapters = final_chapters
            
            # 更新書籍元數據中的目標語言和標題等
            # (這部分邏輯可以根據需要擴展)
            final_book.metadata.language_target = final_book.metadata.language_source # 假設
            final_book.metadata.title_target = final_book.metadata.title_source + " (Translated)"

            # 創建並產生包含完整 Book 對象的 Part
            yield TranslatedBookPart(
                book=final_book
            )
            self.logger.info("Successfully built and yielded TranslatedBookPart.")
        elif not self._original_book_structure:
             self.logger.error("BookBuildProcessor did not receive the original book structure (EpubBookPart). Cannot build final book.")
