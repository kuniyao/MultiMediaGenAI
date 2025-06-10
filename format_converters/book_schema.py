from __future__ import annotations
from typing import List, Union, Literal, Optional
from pydantic import BaseModel, Field

# --- Rich Content and Structured Content Types ---
# These models represent inline elements or structured lines within main content blocks.

class TextItem(BaseModel):
    """Represents a plain text segment within a larger content block."""
    type: Literal["text"] = "text"
    content: str

class BoldItem(BaseModel):
    """Represents a bolded text segment."""
    type: Literal["bold"] = "bold"
    content: str

class ItalicItem(BaseModel):
    """Represents an italicized text segment."""
    type: Literal["italic"] = "italic"
    content: str

class NoteReferenceItem(BaseModel):
    """Represents a reference (like [1]) to a footnote or endnote."""
    type: Literal["note_reference"] = "note_reference"
    marker: str
    note_id: str

RichContentItem = Union[TextItem, BoldItem, ItalicItem, NoteReferenceItem]

class CommentLine(BaseModel):
    """A comment line within a code block, intended for translation."""
    type: Literal["comment"] = "comment"
    value: str

class CodeLine(BaseModel):
    """A line of code within a code block, generally not translated."""
    type: Literal["code"] = "code"
    value: str

CodeContentItem = Union[CommentLine, CodeLine]

# --- Main Content Block Definitions ---
# Each class represents a distinct type of content block in the book.

class BaseBlock(BaseModel):
    """Base model for all content blocks, containing common fields."""
    id: str
    status: Literal["untranslated", "translated", "in_progress", "reviewed"] = "untranslated"

class HeadingBlock(BaseBlock):
    """A heading element (h1, h2, etc.)."""
    type: Literal["heading"] = "heading"
    level: int
    content_source: str
    content_target: str = ""

class ParagraphBlock(BaseBlock):
    """A paragraph, which can contain a mix of text and other inline elements."""
    type: Literal["paragraph"] = "paragraph"
    content_rich_source: List[RichContentItem]
    content_rich_target: List[RichContentItem] = Field(default_factory=list)
    content_source: str # Tagged string for translation, e.g., "Hello <b>world</b>."
    content_target: str = ""

class ImageBlock(BaseBlock):
    """An image, where the caption is the translatable content."""
    type: Literal["image"] = "image"
    path: str
    content_source: str  # Caption for the image
    content_target: str = ""

class ListBlock(BaseBlock):
    """An ordered or unordered list. Items are simple strings for now."""
    type: Literal["list"] = "list"
    ordered: bool = False
    content_source: List[str]
    content_target: List[str] = Field(default_factory=list)

class TableContent(BaseModel):
    """The structured content of a table."""
    headers: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)

class TableBlock(BaseBlock):
    """A table with headers and rows."""
    type: Literal["table"] = "table"
    content_source: TableContent
    content_target: TableContent = Field(default_factory=TableContent)

class NoteContentBlock(BaseBlock):
    """The content of a footnote or endnote, linked by an ID."""
    type: Literal["note_content"] = "note_content"
    marker_source: str
    content_source: str
    content_target: str = ""

class CodeBlock(BaseBlock):
    """A block of code, with comments and code structured for translation."""
    type: Literal["code_block"] = "code_block"
    language: Optional[str] = None
    content_structured_source: List[CodeContentItem]
    content_structured_target: List[CodeContentItem] = Field(default_factory=list)

# A discriminated union of all possible block types.
# Pydantic will use the 'type' field to automatically determine
# which model to use when parsing a block from the JSON.
AnyBlock = Union[
    HeadingBlock,
    ParagraphBlock,
    ImageBlock,
    ListBlock,
    TableBlock,
    NoteContentBlock,
    CodeBlock,
]

# --- Top-Level Book Structure ---

class BookMetadata(BaseModel):
    """Metadata for the book."""
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
    """The root model for the entire standardized book JSON structure."""
    schema_version: str = "1.0"
    metadata: BookMetadata
    content: List[AnyBlock] 