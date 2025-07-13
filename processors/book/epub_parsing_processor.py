import logging
from genai_processors import processor
from workflows.parts import TranslationRequestPart
from workflows.book.parts import EpubBookPart
# 【變更】: 從導入 epub_to_book 改為導入 EpubParser
from format_converters.epub_parser import EpubParser

class EpubParsingProcessor(processor.Processor):
    """
    一個接收 TranslationRequestPart，調用項目自有的解析器來處理 EPUB 文件，
    並輸出一個包含結構化 Book 對象和臨時目錄路徑的 EpubBookPart 的處理器。
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
                # 【變更】: 直接實例化和使用 EpubParser
                parser = EpubParser(epub_path, self.logger)
                book_object = parser.to_book()
                
                self.logger.info(f"Successfully parsed EPUB. Title: '{book_object.metadata.title_source}'.")

                # 【變更】: 產生包含 Book 對象和 unzip_dir 路徑的 Part
                yield EpubBookPart(
                    book=book_object,
                    unzip_dir=str(parser.unzip_dir), # 傳遞臨時目錄路徑
                    metadata=part.metadata
                )

            except Exception as e:
                self.logger.error(f"EPUB parsing failed for {epub_path}: {e}", exc_info=True)
                # 可以在這裡重新拋出異常，以終止整個工作流
                # raise
