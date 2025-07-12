import logging
from genai_processors import processor
from workflows.book.parts import EpubBookPart, ChapterPart

class ChapterExtractionProcessor(processor.Processor):
    """
    一個接收 EpubBookPart，並為書中每個章節產生一個 ChapterPart 的處理器。
    """
    def __init__(self, max_chapters: int = None):
        self.logger = logging.getLogger(__name__)
        self.max_chapters = max_chapters

    async def call(self, stream):
        """
        處理傳入的數據流。
        """
        async for part in stream:
            if not isinstance(part, EpubBookPart):
                self.logger.warning(f"ChapterExtractionProcessor received an unexpected part type: {type(part)}")
                yield part
                continue

            self.logger.info(f"Extracting chapters from book: {part.title}")
            
            chapters_to_process = part.chapters
            if self.max_chapters and self.max_chapters > 0:
                self.logger.info(f"Limiting to the first {self.max_chapters} chapters.")
                chapters_to_process = chapters_to_process[:self.max_chapters]

            for chapter_data in chapters_to_process:
                try:
                    # 創建並產生一個 ChapterPart
                    yield ChapterPart(
                        chapter_id=chapter_data["id"],
                        title=chapter_data.get("title", "Untitled Chapter"), # 假設 title 可能不存在
                        html_content=chapter_data["content"],
                        # 將書籍的元數據和原始 Part 的元數據合併後傳遞下去
                        metadata={
                            "book_title": part.title,
                            "book_author": part.author,
                            **part.metadata
                        }
                    )
                except KeyError as e:
                    self.logger.error(f"Chapter data is missing a required key: {e}. Data: {chapter_data}")
                except Exception as e:
                    self.logger.error(f"Error creating ChapterPart: {e}", exc_info=True)

            self.logger.info(f"Successfully extracted {len(chapters_to_process)} chapters.")
