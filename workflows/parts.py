from dataclasses import dataclass, field
from typing import Any, Dict, List
from genai_processors.content_api import ProcessorPart


@dataclass
class FilePathPart(ProcessorPart):
    """一個包含文件路徑的數據部分。"""
    path: str

    def __post_init__(self):
        # 我們將路徑作為 ProcessorPart 的 "value"
        super().__init__(self.path)


@dataclass
class FileContentPart(ProcessorPart):
    """一個包含文件內容和元數據的數據部分。"""
    path: str
    content: str

    def __post_init__(self):
        # 內容是主要數據
        super().__init__(self.content, metadata={"path": self.path})


# --- 翻譯工作流 Parts ---

@dataclass
class TranslationRequestPart(ProcessorPart):
    """發起一個翻譯請求的數據部分。"""
    text_to_translate: str
    source_lang: str
    target_lang: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # 對於這個 Part，主要內容是待翻譯的文本（或文件路徑）
        # 我們將其他信息放入元數據中
        full_metadata = {
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            **self.metadata
        }
        super().__init__(self.text_to_translate, metadata=full_metadata)


@dataclass
class ApiRequestPart(ProcessorPart):
    """一個準備好發送給 LLM API 的請求。"""
    messages: List[Dict[str, Any]]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # 在這個案例中，沒有一個簡單的字符串值，所以我們傳入一個代表性的空字符串
        # 並將真實數據（messages）放入元數據中
        full_metadata = {
            "messages": self.messages,
            **self.metadata
        }
        super().__init__("", metadata=full_metadata)


@dataclass
class ApiResponsePart(ProcessorPart):
    """來自 LLM API 的響應。"""
    response_text: str
    is_successful: bool
    error_message: str | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        full_metadata = {
            "is_successful": self.is_successful,
            "error_message": self.error_message,
            **self.metadata
        }
        super().__init__(self.response_text, metadata=full_metadata)


@dataclass
class TranslatedTextPart(ProcessorPart):
    """包含最��翻譯結果的數據部分。"""
    translated_text: str
    source_text: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        full_metadata = {
            "source_text": self.source_text,
            **self.metadata
        }
        super().__init__(self.translated_text, metadata=full_metadata)
