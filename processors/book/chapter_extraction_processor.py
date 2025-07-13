import logging
from genai_processors import processor
from workflows.book.parts import EpubBookPart, ChapterPart

class ChapterExtractionProcessor(processor.Processor):
    """
    一個接收 EpubBookPart，並為書中每個章節產生一個包含結構化 Chapter 對象的 
    ChapterPart 的處理器。
    """
    def __init__(self, max_chapters: int = None):
        self.logger = logging.getLogger(__name__)
        self.max_chapters = max_chapters

    async def call(self, stream):
        """
        處理傳入的數據流，將單個 EpubBookPart 分解為多個 ChapterPart。
        """
        async for part in stream:
            if not isinstance(part, EpubBookPart):
                self.logger.warning(f"ChapterExtractionProcessor received an unexpected part type: {type(part)}")
                yield part
                continue

            book_title = part.book.metadata.title_source
            self.logger.info(f"Extracting chapters from book: {book_title}")
            
            chapters_to_process = part.book.chapters
            if self.max_chapters and self.max_chapters > 0:
                self.logger.info(f"Limiting to the first {self.max_chapters} chapters.")
                chapters_to_process = chapters_to_process[:self.max_chapters]

            # 為每個 Chapter 對象，直接產出一個 ChapterPart
            for chapter_object in chapters_to_process:
                try:
                    # 將原始 part 的元數據與書籍元數據結合，傳遞給每個章節
                    combined_metadata = {
                        "book_title": book_title,
                        "book_author": ", ".join(part.book.metadata.author_source),
                        "image_resources": part.book.image_resources, # <--- 【修復】传递图片资源
                        **part.metadata
                    }
                    
                    yield ChapterPart(
                        chapter=chapter_object,
                        metadata=combined_metadata
                    )
                except Exception as e:
                    self.logger.error(f"Error creating ChapterPart for chapter '{chapter_object.id}': {e}", exc_info=True)

            self.logger.info(f"Successfully yielded {len(chapters_to_process)} chapters.")
