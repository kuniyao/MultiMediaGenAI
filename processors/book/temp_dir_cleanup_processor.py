import logging
import shutil
import pathlib
from genai_processors import processor
from workflows.book.parts import EpubBookPart, TranslatedBookPart

class TempDirCleanupProcessor(processor.Processor):
    """
    一個在工作流結束時清理臨時解壓縮目錄的處理器。
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def call(self, stream):
        """
        處理傳入的數據流，查找包含 unzip_dir 的 Part 並執行清理。
        """
        async for part in stream:
            cleanup_dir = None
            # 這個處理器可能在工作流的不同階段被調用
            # 我們檢查它是否在解析後或翻譯後
            if isinstance(part, EpubBookPart) or isinstance(part, TranslatedBookPart):
                if hasattr(part, 'unzip_dir') and getattr(part, 'unzip_dir'):
                    cleanup_dir = getattr(part, 'unzip_dir')

            if cleanup_dir:
                dir_path = pathlib.Path(cleanup_dir)
                if dir_path.exists() and dir_path.is_dir():
                    try:
                        shutil.rmtree(dir_path)
                        self.logger.info(f"成功清理臨時目錄: {dir_path}")
                    except Exception as e:
                        self.logger.error(f"清理臨時目錄 {dir_path} 失敗: {e}", exc_info=True)
                else:
                    self.logger.warning(f"嘗試清理的目錄不存在或不是一個目錄: {dir_path}")
            
            # 將 part 原樣傳遞下去
            yield part
