from abc import ABC, abstractmethod
from pathlib import Path
from workflows.parts import ProcessorPart
from format_converters.epub_writer import EpubWriter
from workflows.book.parts import TranslatedBookPart

class BaseArtifactWriter(ABC):
    """写入最终产物（如.epub, .srt）的策略接口"""
    @abstractmethod
    def write(self, final_part: ProcessorPart, output_dir: Path, original_filename: str):
        """
        将最终的Part写入指定的输出目录。

        Args:
            final_part: 包含最终产物数据的Part (e.g., TranslatedBookPart).
            output_dir: 最终的输出目录.
            original_filename: 原始文件名 (不含扩展名), 用于构建输出文件名.
        """
        pass

class EpubArtifactWriter(BaseArtifactWriter):
    def write(self, final_part: TranslatedBookPart, output_dir: Path, original_filename: str):
        """将TranslatedBookPart写入EPUB文件。"""
        # 输出文件名将是 'original_filename_translated.epub'
        output_filename = f"{original_filename}_translated.epub"
        output_path = output_dir / output_filename
        
        # 使用正确的参数初始化EpubWriter，并调用其write方法
        writer = EpubWriter(final_part.book, str(output_path))
        writer.write() 