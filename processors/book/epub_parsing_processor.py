import logging
from genai_processors import processor
from workflows.parts import TranslationRequestPart
from workflows.book.parts import EpubBookPart
# 導入項目自有的 epub 解析器
from format_converters.epub_parser import epub_to_book

class EpubParsingProcessor(processor.Processor):
    """
    一個接收 TranslationRequestPart，調用項目自有的解析器來處理 EPUB 文件，
    並輸出一個包含結構化 Book 對象的 EpubBookPart 的處理器。
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
                # 使用項目中已有的、更強大的解析器
                book_object = epub_to_book(epub_path, self.logger)
                
                self.logger.info(f"Successfully parsed EPUB. Title: '{book_object.metadata.title_source}'.")

                # 產生包含完整 Book 對象的 Part
                yield EpubBookPart(
                    book=book_object,
                    metadata=part.metadata # 傳遞原始的元數據
                )

            except Exception as e:
                self.logger.error(f"EPUB parsing failed for {epub_path}: {e}", exc_info=True)
                # 可以在這裡重新拋出異常，以終止整個工作流
                # raise
