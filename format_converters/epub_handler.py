# This file will contain the logic for parsing an EPUB file
# and converting it into the standardized Book object.

import logging
from typing import List, Tuple
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup, NavigableString

from .book_schema import (
    Book, BookMetadata, AnyBlock,
    HeadingBlock, ParagraphBlock, ImageBlock, ListBlock, TableBlock, TableContent,
    TextItem, BoldItem, ItalicItem, NoteReferenceItem, RichContentItem
)

def _parse_paragraph_tag(tag: BeautifulSoup) -> Tuple[List[RichContentItem], str]:
    """
    Parses a BeautifulSoup tag for a paragraph (<p>) and extracts rich content.

    Returns a tuple containing:
    - A list of RichContentItem objects.
    - A string with simple HTML-like tags for translation.
    """
    rich_content_list = []
    tagged_string = ""

    for child in tag.children:
        if isinstance(child, NavigableString):
            text = str(child)
            # Whitespace handling can be tricky. We'll condense it.
            # A more sophisticated approach might preserve spaces differently.
            if text.strip():
                rich_content_list.append(TextItem(content=text))
                tagged_string += text
        elif hasattr(child, 'name'):
            # Handle <br> specifically to preserve line breaks
            if child.name == 'br':
                tagged_string += "\n"
                continue

            text = child.get_text()
            if not text.strip():
                continue

            if child.name in ['b', 'strong']:
                rich_content_list.append(BoldItem(content=text))
                tagged_string += f"<b>{text}</b>"
            elif child.name in ['i', 'em']:
                rich_content_list.append(ItalicItem(content=text))
                tagged_string += f"<i>{text}</i>"
            # TODO: Add handling for other inline tags like <a> for footnotes
            else:
                # Treat other unhandled tags as plain text for now
                rich_content_list.append(TextItem(content=text))
                tagged_string += text

    return rich_content_list, tagged_string.strip()

def epub_to_book(epub_path: str, logger: logging.Logger = None) -> Book:
    """
    Parses an EPUB file and converts it into a standardized Book object.

    This function reads the metadata and content of an EPUB, converting each
    chapter/document into the appropriate block types (Heading, Paragraph, etc.).

    Args:
        epub_path: The file path to the EPUB file.
        logger: An optional logger instance.

    Returns:
        A Book object representing the EPUB's content.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    logger_to_use.info(f"Starting to parse EPUB file: {epub_path}")

    # --- Step 1: Read the EPUB file ---
    book_epub = epub.read_epub(epub_path)
    
    # --- Step 2: Extract Metadata ---
    metadata = BookMetadata(
        title_source=book_epub.get_metadata('DC', 'title')[0][0] if book_epub.get_metadata('DC', 'title') else "Untitled",
        author_source=[creator[0] for creator in book_epub.get_metadata('DC', 'creator')] if book_epub.get_metadata('DC', 'creator') else [],
        language_source=book_epub.get_metadata('DC', 'language')[0][0] if book_epub.get_metadata('DC', 'language') else "unknown",
        language_target="zh-CN", # Default target language, can be changed later
        isbn=book_epub.get_metadata('DC', 'identifier')[0][0] if book_epub.get_metadata('DC', 'identifier') else None
    )
    logger_to_use.info(f"Extracted metadata: Title='{metadata.title_source}', Author='{metadata.author_source}'")

    # --- Step 3: Extract and Parse Content Documents (Chapters) ---
    content_blocks: list[AnyBlock] = []
    block_id_counter = 0

    for item in book_epub.get_items_of_type(ITEM_DOCUMENT):
        logger_to_use.debug(f"Processing content document: {item.get_name()}")
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        
        if not soup.body:
            continue

        # Find all supported block-level tags in document order.
        # This is more robust than iterating over direct children, as it
        # finds content nested inside <div> or <section> tags.
        tags_to_find = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'img', 'ul', 'ol', 'table']
        for tag in soup.body.find_all(tags_to_find):
            
            # Skip tags that are children of other block elements we are already processing
            # e.g., <p> inside a <li> of a <ul> which would be handled by the list parser.
            # This is a simple but effective way to avoid double-processing.
            if tag.find_parent(tags_to_find, recursive=False):
                 continue

            block_id_counter += 1
            block_id = f"{item.id}_{block_id_counter}"
            
            # --- Heading Parser ---
            if tag.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                level = int(tag.name[1])
                text = tag.get_text().strip()
                if text:
                    content_blocks.append(HeadingBlock(id=block_id, level=level, content_source=text))

            # --- Paragraph Parser ---
            elif tag.name == 'p':
                rich_content, tagged_text = _parse_paragraph_tag(tag)
                if tagged_text:
                    content_blocks.append(ParagraphBlock(
                        id=block_id,
                        content_rich_source=rich_content,
                        content_source=tagged_text
                    ))

            # --- Image Parser ---
            elif tag.name == 'img':
                src = tag.get('src', '')
                alt_text = tag.get('alt', '')
                if src:
                    content_blocks.append(ImageBlock(id=block_id, path=src, content_source=alt_text))

            # --- List Parser ---
            elif tag.name in ['ul', 'ol']:
                items = [li.get_text().strip() for li in tag.find_all('li') if li.get_text().strip()]
                if items:
                    content_blocks.append(ListBlock(
                        id=block_id,
                        ordered=(tag.name == 'ol'),
                        content_source=items
                    ))

            # --- Table Parser ---
            elif tag.name == 'table':
                headers = [th.get_text().strip() for th in tag.find_all('th')]
                rows = []
                for tr in tag.find_all('tr'):
                    row_cells = [td.get_text().strip() for td in tr.find_all('td')]
                    if any(row_cells): # Only add rows with content
                        # Ensure row has same number of columns as header
                        if headers and len(row_cells) == len(headers):
                           rows.append(row_cells)
                
                if headers or rows:
                    content_blocks.append(TableBlock(
                        id=block_id,
                        content_source=TableContent(headers=headers, rows=rows)
                    ))

    logger_to_use.info(f"Parsing complete. Extracted {len(content_blocks)} content blocks.")

    # --- Step 4: Assemble the final Book object ---
    book_model = Book(
        metadata=metadata,
        content=content_blocks
    )

    return book_model 