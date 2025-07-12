# workflows/book/parts.py

from dataclasses import dataclass, field
from typing import Any, Dict, List
from genai_processors.content_api import ProcessorPart

@dataclass
class EpubBookPart(ProcessorPart):
    """
    一個代表已剖析的 EPUB 書籍的數據部分。
    """
    title: str
    author: str
    chapters: List[Dict[str, Any]] # 一個包含章節資訊的字典列表
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # 將書籍的元數據和章節列表放入 ProcessorPart 的元數據中
        full_metadata = {
            "title": self.title,
            "author": self.author,
            "chapters": self.chapters,
            **self.metadata
        }
        # 主要內容可以是一個代表書籍的簡單字符串
        super().__init__(f"EPUB Book: {self.title}", metadata=full_metadata)


@dataclass
class ChapterPart(ProcessorPart):
    """
    一個代表單個書籍章節的數據部分。
    """
    chapter_id: str
    title: str
    html_content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # 將章節的元數據放入 ProcessorPart 的元數據中
        full_metadata = {
            "chapter_id": self.chapter_id,
            "title": self.title,
            **self.metadata
        }
        # 主要內容是章節的 HTML
        super().__init__(self.html_content, metadata=full_metadata)


@dataclass
class TranslatedBookPart(ProcessorPart):
    """
    一個代表已完全翻譯的書籍的數據部分。
    """
    title: str
    author: str
    translated_chapters: List[Dict[str, Any]] # 包含翻譯後內容的章節列表
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        full_metadata = {
            "title": self.title,
            "author": self.author,
            "translated_chapters": self.translated_chapters,
            **self.metadata
        }
        super().__init__(f"Translated EPUB Book: {self.title}", metadata=full_metadata)
