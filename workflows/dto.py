# 数据传输对象（契约）
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
# 导入EPUB和字幕共用的数据结构
from format_converters.book_schema import SubtitleTrack, Book

class PipelineContext(BaseModel):
    """
    一个在管道中流转的、携带所有状态和数据的上下文对象。
    它现在同时支持字幕和EPUB工作流。
    """
    # --- 通用输入 ---
    source_input: str
    target_lang: str
    output_dir: str

    # --- 通用元数据 ---
    source_metadata: Optional[Dict[str, Any]] = None
    source_lang: Optional[str] = None

    # --- 字幕工作流专用字段 ---
    raw_segments: Optional[List[Dict[str, Any]]] = None
    source_type: Optional[str] = None
    subtitle_track: Optional[SubtitleTrack] = None
    final_srt_content: Optional[str] = None

    # --- EPUB 工作流专用字段 ---
    original_book: Optional[Book] = None
    translated_book: Optional[Book] = None # 用于存放最终翻译完成的Book对象
    repair_tasks: List[Dict[str, Any]] = Field(default_factory=list)

    # --- LLM 交互通用字段 ---
    translation_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    translated_results: List[Dict[str, Any]] = Field(default_factory=list)

    # --- 流程控制与配置 ---
    concurrency: int = 10 # EPUB流程需要的并发数
    glossary: Optional[Dict[str, str]] = None # EPUB流程需要的术语表

    # --- 流程控制与日志 ---
    llm_logs: List[str] = Field(default_factory=list)
    is_successful: bool = True
    error_message: Optional[str] = None

    # Pydantic v2 推荐的配置
    class Config:
        arbitrary_types_allowed = True

    