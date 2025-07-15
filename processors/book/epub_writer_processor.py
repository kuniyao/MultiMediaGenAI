# processors/book/epub_writer_processor.py

import logging
from pathlib import Path
from typing import AsyncGenerator

from genai_processors.processor import Processor
from genai_processors.content_api import ProcessorPart
from workflows.book.parts import TranslatedBookPart
from .artifact_writers import EpubArtifactWriter

class EpubWriterProcessor(Processor):
    """
    一个专用的处理器，仅负责将 TranslatedBookPart 写入为 .epub 文件。
    """

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.artifact_writer = EpubArtifactWriter()

    async def call(self, stream: AsyncGenerator[ProcessorPart, None]) -> AsyncGenerator[ProcessorPart, None]:
        """
        处理输入流，查找 TranslatedBookPart 并将其写入文件。
        """
        async for part in stream:
            # 只对 TranslatedBookPart 感兴趣
            if isinstance(part, TranslatedBookPart):
                # 从元数据中读取上游处理器准备好的输出目录
                output_dir_str = part.metadata.get("output_dir")
                if not output_dir_str:
                    self.logger.error("Could not find 'output_dir' in part metadata. Cannot write EPUB file.")
                    # 即使出错，也要把 Part 传下去，以免中断流程
                    yield part
                    continue

                output_dir = Path(output_dir_str)
                original_filename = Path(part.metadata.get("original_file", "unknown.epub")).stem
                
                self.logger.info(f"Writing final EPUB artifact to directory: {output_dir}")
                try:
                    # 使用注入的写入器策略来写入最终产物
                    self.artifact_writer.write(part, output_dir, original_filename)
                    self.logger.info(f"Successfully wrote EPUB file for '{original_filename}'.")
                except Exception as e:
                    self.logger.error(f"Failed to write EPUB file for '{original_filename}': {e}", exc_info=True)
            
            # 将所有 Part（包括我们处理过的）原样传递给下游
            yield part