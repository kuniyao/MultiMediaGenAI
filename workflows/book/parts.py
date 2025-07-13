# workflows/book/parts.py

from dataclasses import dataclass, field
from typing import Any, Dict
from genai_processors.content_api import ProcessorPart

# 導入底層的結構化數據模型
from format_converters.book_schema import Book, Chapter

@dataclass
class EpubBookPart(ProcessorPart):
    """
    一個代表已剖析的 EPUB 書籍的數據部分。
    它包含一個完整的、結構化的 Book 對象。
    """
    book: Book
    unzip_dir: str  # 新增：用於追蹤解壓縮後的臨時目錄路徑
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # 將書籍的元數據放入 ProcessorPart 的元數據中
        full_metadata = {
            "title": self.book.metadata.title_source,
            "author": ", ".join(self.book.metadata.author_source),
            **self.metadata
        }
        # 主要內容可以是一個代表書籍的簡單字符串
        super().__init__(f"EPUB Book: {self.book.metadata.title_source}", metadata=full_metadata)


@dataclass
class ChapterPart(ProcessorPart):
    """
    一個代表單個書籍章節的數據部分。
    它包含一個完整的、結構化的 Chapter 對象。
    """
    chapter: Chapter
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # 將章節的元數據放入 ProcessorPart 的元數據中
        full_metadata = {
            "chapter_id": self.chapter.id,
            "title": self.chapter.title,
            **self.metadata
        }
        # 主要內容可以是一個代表章節的簡單字符串
        super().__init__(f"Chapter: {self.chapter.title}", metadata=full_metadata)

@dataclass
class TranslatedChapterPart(ProcessorPart):
    """
    一個代表已翻譯的單個書籍章節的數據部分。
    """
    translated_chapter: Chapter
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        full_metadata = {
            "chapter_id": self.translated_chapter.id,
            "title": self.translated_chapter.title_target,
            **self.metadata
        }
        super().__init__(f"Translated Chapter: {self.translated_chapter.title_target}", metadata=full_metadata)


@dataclass
class TranslatedBookPart(ProcessorPart):
    """
    一個代表已完全翻譯的書籍的數據部分。
    它包含一個完整的、已翻譯的 Book 對象。
    """
    book: Book
    unzip_dir: str  # 新增：用於追蹤解壓縮後的臨時目錄路徑
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        full_metadata = {
            "title": self.book.metadata.title_target,
            "author": ", ".join(self.book.metadata.author_target),
            **self.metadata
        }
        super().__init__(f"Translated EPUB Book: {self.book.metadata.title_target}", metadata=full_metadata)


# ==============================================================================
#  【新增】用於智能預處理器 (ChapterPreperationProcessor) 的新 Part 類型
# ==============================================================================

@dataclass
class BatchTranslationTaskPart(ProcessorPart):
    """
    一個代表“批處理”翻譯任務的數據部分。
    它包含一個由多個短章節HTML打包而成的JSON字符串。
    """
    json_string: str
    chapter_count: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # 主要內容是一個描述性的字符串
        super().__init__(f"Batch translation task with {self.chapter_count} chapters.", metadata=self.metadata)


@dataclass
class SplitChapterTaskPart(ProcessorPart):
    """
    一個代表“長章節切分”翻譯任務的數據部分。
    它包含一個長章節被切分後單個部分的HTML內容。
    """
    html_content: str
    original_chapter_id: str
    part_number: int
    injected_heading: bool
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # 主要內容是一個描述性的字符串
        super().__init__(f"Split part #{self.part_number} for chapter '{self.original_chapter_id}'.", metadata=self.metadata)
