# processors/subtitle/file_write_processor.py

import logging
from pathlib import Path
import json

from genai_processors import processor
from workflows.parts import TranslatedTextPart
from common_utils.output_manager import OutputManager
from common_utils.file_helpers import sanitize_filename


class FileWriterProcessor(processor.Processor):
    """
    一個接收包含翻譯文本和元數據的 Part，並將內容寫入目標文件的處理器。
    """

    def __init__(self, output_dir: str | Path):
        super().__init__()
        self.output_dir = Path(output_dir)
        self.logger = logging.getLogger(__name__)

    async def call(self, stream):
        """
        處理傳入的數據流，並根據 Part 中的信息寫入文件。
        """
        async for part in stream:
            # 我們只關心包含最終翻譯結果的 Part
            if not isinstance(part, TranslatedTextPart):
                yield part  # 將不處理的 Part 直接傳遞下去
                continue

            try:
                metadata = part.metadata
                # 從元數據中獲取文件名或標題
                # 這是為了保持與舊邏輯的兼容性
                title = metadata.get("title", "untitled")
                sanitized_title = sanitize_filename(title)
                
                # 構造特定於該任務的輸出管理器
                task_output_dir = self.output_dir / sanitized_title
                output_manager = OutputManager(str(task_output_dir), self.logger)

                # 確定輸出文件名
                # 這裡我們假設元數據中會提供原始文件名或一個基礎名
                original_file_path = Path(metadata.get("original_file", "output.txt"))
                original_filename = original_file_path.stem
                target_lang = metadata.get("target_lang", "lang")
                
                # 構建最終的文件名，例如 "my_document_fr.txt"
                output_filename = f"{original_filename}_{target_lang}{original_file_path.suffix}"
                
                # 獲取完整的輸出路徑
                # 這裡我們假設所有翻譯文件都存放在 'translations' 子目錄中
                output_path = output_manager.get_workflow_output_path(
                    "translations", 
                    output_filename
                )

                # 寫入文件
                output_manager.save_file(output_path, part.translated_text)
                self.logger.info(f"成功將翻譯���容寫入到: {output_path}")

                # 將原始的 Part 傳遞下去，表示處理完成
                yield part

            except Exception as e:
                self.logger.error(f"寫入文件時出錯 (metadata: {part.metadata}): {e}", exc_info=True)
                # 發生錯誤時，不傳遞任何 Part