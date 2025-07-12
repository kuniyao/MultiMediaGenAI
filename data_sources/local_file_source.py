import logging
from genai_processors import processor
from workflows.parts import TranslationRequestPart


class LocalFileSource(processor.Processor):
    """
    一個接收包含文件路徑的 TranslationRequestPart，讀取文件內容，
    並產生一個新的、包含了文件內容的 TranslationRequestPart 的處理器。
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def call(self, stream):
        """
        處理傳入的數據流。
        """
        async for part in stream:
            if not isinstance(part, TranslationRequestPart):
                self.logger.warning(f"LocalFileSource received an unexpected part type: {type(part)}")
                yield part
                continue

            file_path = part.text_to_translate
            self.logger.info(f"Reading file from path: {file_path}")

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 創建一個新的 Part，用文件內容替換掉路徑
                # 同時保留所有原始的語言和元數據信息
                yield TranslationRequestPart(
                    text_to_translate=content,
                    source_lang=part.source_lang,
                    target_lang=part.target_lang,
                    metadata=part.metadata
                )
                self.logger.info(f"Successfully read file '{file_path}' and yielded content.")

            except FileNotFoundError:
                self.logger.error(f"File not found at {file_path}")
                # 在這裡可以選擇產生一個 ErrorPart
            except Exception as e:
                self.logger.error(f"Error reading file {file_path}: {e}", exc_info=True)
