from __future__ import annotations
from typing import List, Union, Literal, Optional, Dict
from pydantic import BaseModel, Field

# --- Rich Content and Structured Content Types ---

class TextItem(BaseModel):
    type: Literal["text"] = "text"
    content: str

class BoldItem(BaseModel):
    type: Literal["bold"] = "bold"
    content: str

class ItalicItem(BaseModel):
    type: Literal["italic"] = "italic"
    content: str
    
class LineBreakItem(BaseModel): # <--- 新增: 用于表示 <br> 标签
    """Represents a line break (<br>) within a paragraph."""
    type: Literal["line_break"] = "line_break"

class NoteReferenceItem(BaseModel):
    type: Literal["note_reference"] = "note_reference"
    marker: str
    note_id: str

# --- 修改: 将 LineBreakItem 加入联合类型 ---
RichContentItem = Union[TextItem, BoldItem, ItalicItem, NoteReferenceItem, LineBreakItem]

class CommentLine(BaseModel):
    type: Literal["comment"] = "comment"
    value: str

class CodeLine(BaseModel):
    type: Literal["code"] = "code"
    value: str

CodeContentItem = Union[CommentLine, CodeLine]

# --- Main Content Block Definitions ---

class BaseBlock(BaseModel):
    id: str
    status: Literal["untranslated", "translated", "in_progress", "reviewed"] = "untranslated"
    css_classes: Optional[List[str]] = None  # <--- 新增: 用于存储HTML标签的class属性

class HeadingBlock(BaseBlock):
    type: Literal["heading"] = "heading"
    level: int
    content_source: str
    content_target: str = ""

class ParagraphBlock(BaseBlock):
    type: Literal["paragraph"] = "paragraph"
    content_rich_source: List[RichContentItem]
    content_rich_target: List[RichContentItem] = Field(default_factory=list)
    content_source: str
    content_target: str = ""

class ImageBlock(BaseBlock):
    type: Literal["image"] = "image"
    path: str
    content_source: str
    content_target: str = ""
    
class MarkerBlock(BaseBlock): # <--- 新增: 用于表示非内容标记，如分页符
    """Represents a non-content marker, like a page break."""
    type: Literal["marker"] = "marker"
    role: str  # e.g., "doc-pagebreak"
    title: Optional[str] = None # e.g., "vii"

class ListBlock(BaseBlock):
    type: Literal["list"] = "list"
    ordered: bool = False
    content_source: List[str]
    content_target: List[str] = Field(default_factory=list)

class TableContent(BaseModel):
    headers: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)

class TableBlock(BaseBlock):
    type: Literal["table"] = "table"
    content_source: TableContent
    content_target: TableContent = Field(default_factory=TableContent)

class NoteContentBlock(BaseBlock):
    type: Literal["note_content"] = "note_content"
    marker_source: str
    content_source: str
    content_target: str = ""

class CodeBlock(BaseBlock):
    type: Literal["code_block"] = "code_block"
    language: Optional[str] = None
    content_structured_source: List[CodeContentItem]
    content_structured_target: List[CodeContentItem] = Field(default_factory=list)

# --- 修改: 将 MarkerBlock 加入联合类型 ---
AnyBlock = Union[
    HeadingBlock,
    ParagraphBlock,
    ImageBlock,
    ListBlock,
    TableBlock,
    NoteContentBlock,
    CodeBlock,
    MarkerBlock, # <--- 新增
]

# --- Top-Level Book Structure ---

class ImageResource(BaseModel):
    content: bytes
    media_type: str

class CSSResource(BaseModel): # <--- 新增: 用于表示CSS样式资源
    """Represents a CSS resource, either from a file or an internal style block."""
    content: str # CSS是文本，所以用str
    media_type: str = "text/css"

class Chapter(BaseModel):
    id: str
    title: Optional[str] = None
    epub_type: Optional[str] = None # <--- 新增: 用于存储章节的语义类型
    internal_css: Optional[str] = None # <--- 新增: 用于存储章节内的<style>块内容
    content: List[AnyBlock]

class BookMetadata(BaseModel):
    title_source: str
    title_target: str = ""
    author_source: List[str] = Field(default_factory=list)
    author_target: List[str] = Field(default_factory=list)
    language_source: str
    language_target: str
    isbn: Optional[str] = None
    publisher_source: Optional[str] = None
    publisher_target: str = ""
    cover_image: Optional[str] = None

class Book(BaseModel):
    schema_version: str = "1.0"
    metadata: BookMetadata
    chapters: List[Chapter]
    image_resources: Dict[str, ImageResource] = Field(default_factory=dict)
    css_resources: Dict[str, CSSResource] = Field(default_factory=dict) # <--- 新增: 存储全局CSS文件