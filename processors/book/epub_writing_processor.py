import logging
import pathlib
from genai_processors import processor
from workflows.book.parts import TranslatedBookPart
from common_utils.output_manager import OutputManager
# 導入項目自有的 epub 寫入器工具函數
from format_converters.epub_writer import book_to_epub

class EpubWritingProcessor(processor.Processor):
    """
    一個接收 TranslatedBookPart，並調用項目自有的寫入器工具函數
    來生成最終 .epub 文件的處理器。
    """
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    async def call(self, stream):
        """
        處理傳入的數據流。
        """
        async for part in stream:
            if not isinstance(part, TranslatedBookPart):
                self.logger.warning(f"EpubWritingProcessor received an unexpected part type: {type(part)}")
                yield part
                continue

            book_object = part.book
            self.logger.info(f"Writing translated book to EPUB file: {book_object.metadata.title_target}")

            try:
                # 1. 決定輸出路徑
                output_path = self._get_output_path(part.metadata)
                output_path.parent.mkdir(parents=True, exist_ok=True)

                # 2. 調用核心工具函數來完成所有寫入工作
                book_to_epub(book_object, str(output_path))
                
                self.logger.info(f"Successfully wrote translated EPUB to: {output_path}")
                
                # 為了保持數據流的完整性，可以選擇性地將結果傳遞下去
                yield part

            except Exception as e:
                self.logger.error(f"EPUB file writing failed: {e}", exc_info=True)
                # 即使寫入失敗，也將 part 傳遞下去，以便可能的錯誤處理
                yield part
    
    def _get_output_path(self, metadata: dict) -> pathlib.Path:
        """根據元數據確定最終的輸出文件路徑。"""
        output_dir = metadata.get("output_dir", "GlobalWorkflowOutputs")
        # 假設 book_title 存在於元數據中
        original_filename = pathlib.Path(metadata.get("book_title", "book")).stem
        target_lang = metadata.get("target_lang", "lang")
        output_filename = f"{original_filename}_{target_lang}.epub"
        
        output_manager = OutputManager(output_dir, self.logger)
        return output_manager.get_workflow_output_path("epub_translated", output_filename)
