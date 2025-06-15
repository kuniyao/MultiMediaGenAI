from __future__ import annotations
from typing import List, Union, Literal, Optional, Dict
from pydantic import BaseModel, Field, field_serializer, field_validator
import base64

# ==============================================================================
# 1. 行内内容元素 (Inline Content Items)
# 这些是构成段落富文本内容的最小单位。
# ==============================================================================

class TextItem(BaseModel):
    """普通文本"""
    type: Literal["text"] = "text"
    content: str

class BoldItem(BaseModel):
    """粗体文本"""
    type: Literal["bold"] = "bold"
    content: str

class ItalicItem(BaseModel):
    """斜体文本"""
    type: Literal["italic"] = "italic"
    content: str

class HyperlinkItem(BaseModel):
    """超链接 (<a> 标签)"""
    type: Literal["hyperlink"] = "hyperlink"
    href: str  # URL 或锚点链接
    content: str # 可点击的文本
    title: Optional[str] = None # <a> 标签的 title 属性

class LineBreakItem(BaseModel):
    """换行符 (<br> 标签)"""
    type: Literal["line_break"] = "line_break"

class NoteReferenceItem(BaseModel):
    """脚注/尾注在正文中的引用标记"""
    type: Literal["note_reference"] = "note_reference"
    marker: str
    note_id: str

# 将所有行内元素合并为一个联合类型
RichContentItem = Union[TextItem, BoldItem, ItalicItem, HyperlinkItem, NoteReferenceItem, LineBreakItem]


# ==============================================================================
# 2. 块级内容元素 (Block Content Items)
# 这些是构成书籍主体内容的独立块。
# ==============================================================================

# --- 特殊块所需的内容模型 ---

class CommentLine(BaseModel):
    type: Literal["comment"] = "comment"
    value: str

class CodeLine(BaseModel):
    type: Literal["code"] = "code"
    value: str

CodeContentItem = Union[CommentLine, CodeLine]

# 为表格单元格和行定义类型别名，以提高可读性
CellContent = List[RichContentItem]
"""一个单元格的内容，可以是富文本。"""
Row = List[CellContent]
"""一个表格行，由多个单元格组成。"""

class TableContent(BaseModel):
    """表格的完整内容，包括表头和数据行。"""
    headers: Row = Field(default_factory=list)
    rows: List[Row] = Field(default_factory=list)

class ListItem(BaseModel):
    """列表中的一个项目 (<li>)。"""
    # 列表项自身的内容，可以是富文本
    content: List[RichContentItem] = Field(default_factory=list) 
    # 跟随在此项下的嵌套列表 (e.g., <li>item 1<ul>...</ul></li>)
    nested_list: Optional['ListBlock'] = None

# --- 所有块的基类 ---

class BaseBlock(BaseModel):
    id: str
    status: Literal["untranslated", "translated", "in_progress", "reviewed"] = "untranslated"
    css_classes: Optional[List[str]] = None  # 存储HTML标签的class属性

# --- 具体的块类型 ---

class HeadingBlock(BaseBlock):
    type: Literal["heading"] = "heading"
    level: int
    content_source: str
    content_target: str = ""

class ParagraphBlock(BaseBlock):
    type: Literal["paragraph"] = "paragraph"
    content_rich_source: List[RichContentItem]
    content_rich_target: List[RichContentItem] = Field(default_factory=list)
    content_source: str # 纯文本表示，用于快速预览或处理
    content_target: str = ""

class ImageBlock(BaseBlock):
    type: Literal["image"] = "image"
    path: str
    container_tag: Optional[str] = None  # e.g., 'p', 'div', or None
    content_source: str # 通常是图片的描述或标题
    content_target: str = ""
    img_css_classes: Optional[List[str]] = None

class ListBlock(BaseBlock):
    """代表一个有序 (<ol>) 或无序 (<ul>) 列表。"""
    type: Literal["list"] = "list"
    ordered: bool = False
    items_source: List[ListItem]
    items_target: List[ListItem] = Field(default_factory=list)

class TableBlock(BaseBlock):
    type: Literal["table"] = "table"
    content_source: TableContent
    content_target: TableContent = Field(default_factory=TableContent)

class CodeBlock(BaseBlock):
    type: Literal["code_block"] = "code_block"
    language: Optional[str] = None
    content_structured_source: List[CodeContentItem]
    content_structured_target: List[CodeContentItem] = Field(default_factory=list)

class NoteContentBlock(BaseBlock):
    """脚注/尾注的实际内容块。"""
    type: Literal["note_content"] = "note_content"
    marker_source: str # 脚注在注释区域显示的标记 (e.g., "1.")
    content_source: List['AnyBlock'] # 脚注内容可以是多个段落、列表等
    content_target: List['AnyBlock'] = Field(default_factory=list)

class MarkerBlock(BaseBlock):
    """非内容标记，如分页符 <hr class="doc-pagebreak" title="vii"/>"""
    type: Literal["marker"] = "marker"
    role: str  # e.g., "doc-pagebreak"
    title: Optional[str] = None # e.g., "vii"

# 将所有块类型合并为一个联合类型
AnyBlock = Union[
    HeadingBlock,
    ParagraphBlock,
    ImageBlock,
    ListBlock,
    TableBlock,
    CodeBlock,
    NoteContentBlock,
    MarkerBlock,
]

# --- 手动处理向前引用 ---
# 因为 ListItem 和 NoteContentBlock 中引用了尚未完整定义的 ListBlock/AnyBlock，
# 需要在所有模型定义后调用 model_rebuild() 来正确解析类型。
ListItem.model_rebuild()
NoteContentBlock.model_rebuild()


# ==============================================================================
# 3. 资源定义 (Resource Definitions)
# ==============================================================================

class ImageResource(BaseModel):
    """图片资源"""
    content: bytes
    media_type: str

    @field_serializer('content')
    def serialize_content(self, content: bytes) -> str:
        """在序列化为JSON时，将图片内容编码为Base64字符串。"""
        return base64.b64encode(content).decode('ascii')

    @field_validator('content', mode='before')
    @classmethod
    def decode_content(cls, v: Union[str, bytes]) -> bytes:
        """
        在数据验证（解析）时，将输入的Base64字符串解码为bytes。
        如果输入已经是bytes，则直接返回。
        这使得模型可以从原始数据（bytes）或序列化后的数据（str）创建。
        """
        if isinstance(v, str):
            return base64.b64decode(v.encode('ascii'))
        return v

class CSSResource(BaseModel):
    """CSS样式资源"""
    content: str # CSS是文本
    media_type: str = "text/css"


# ==============================================================================
# 4. 书籍结构 (Book Structure)
# ==============================================================================

class Chapter(BaseModel):
    id: str
    title: Optional[str] = None
    epub_type: Optional[str] = None # 存储章节的语义类型 (e.g., 'toc', 'bodymatter')
    internal_css: Optional[str] = None # 存储章节内的<style>块内容
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
    cover_image: Optional[str] = None # 指向 image_resources 中的 key


# ==============================================================================
# 5. 顶级书籍模型 (Top-Level Book Model)
# ==============================================================================

class Book(BaseModel):
    schema_version: str = "1.0"
    metadata: BookMetadata
    chapters: List[Chapter]
    image_resources: Dict[str, ImageResource] = Field(default_factory=dict)
    css_resources: Dict[str, CSSResource] = Field(default_factory=dict)