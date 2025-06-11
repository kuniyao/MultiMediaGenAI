# This file will contain the logic for parsing an EPUB file
# and converting it into the standardized Book object.

import logging
from typing import List, Tuple, Dict
from urllib.parse import urljoin
from ebooklib import epub, ITEM_DOCUMENT, ITEM_IMAGE, ITEM_STYLE
from bs4 import BeautifulSoup, NavigableString

from .book_schema import (
    Book, BookMetadata, AnyBlock,
    HeadingBlock, ParagraphBlock, ImageBlock, ListBlock, TableBlock, TableContent,
    TextItem, BoldItem, ItalicItem, NoteReferenceItem, RichContentItem, Chapter,
    ImageResource, LineBreakItem, MarkerBlock, CSSResource
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
                rich_content_list.append(LineBreakItem())
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

def _flatten_toc(toc_items):
    """
    Recursively flattens the ebooklib TOC structure into a simple list of epub.Link objects.
    This handles nested chapters and sections.
    """
    flat_list = []
    for item in toc_items:
        if isinstance(item, tuple):
            # This is a section with sub-items, like (Link, [Link, Link, ...])
            # The first element of the tuple is the section link/header
            if isinstance(item[0], epub.Link):
                flat_list.append(item[0])
            # The second element is a list of sub-links, so we recurse
            flat_list.extend(_flatten_toc(item[1]))
        elif isinstance(item, epub.Link):
            flat_list.append(item)
    return flat_list

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

    # --- New Step: Extract Image Resources ---
    image_resources: Dict[str, ImageResource] = {}
    for item in book_epub.get_items_of_type(ITEM_IMAGE):
        path = item.get_name()
        content = item.get_content()
        media_type = item.media_type
        if path and content and media_type:
            image_resources[path] = ImageResource(content=content, media_type=media_type)
    logger_to_use.info(f"Extracted {len(image_resources)} image resources.")

    # --- New Step: Extract CSS Resources ---
    css_resources: Dict[str, CSSResource] = {}
    for item in book_epub.get_items_of_type(ITEM_STYLE):
        path = item.get_name()
        # CSS is text, so decode it. Assume UTF-8, which is common.
        content = item.get_content().decode('utf-8', errors='ignore')
        if path and content:
            css_resources[path] = CSSResource(content=content)
    logger_to_use.info(f"Extracted {len(css_resources)} CSS resources.")

    # --- Step 3: Extract and Parse Content Documents based on TOC ---
    chapters: list[Chapter] = []
    
    # Create a map of hrefs to EPUB items for quick lookup
    href_map = {item.get_name(): item for item in book_epub.get_items()}
    
    # Flatten the Table of Contents to get a reliable list of chapters.
    # This is the correct way to identify chapters, avoiding treating every single 
    # HTML file as a chapter.
    flat_toc = _flatten_toc(book_epub.toc)
    
    # Use a set to track processed files to avoid duplicates, as TOC can link to the same file.
    processed_hrefs = set()

    for toc_link in flat_toc:
        chapter_title = toc_link.title
        # Href can be like "text/chapter1.xhtml#section1", we only need the file path.
        chapter_href = toc_link.href.split('#')[0]
        
        if not chapter_href or chapter_href in processed_hrefs:
            continue

        item = href_map.get(chapter_href)
        
        if not item or item.get_type() != ITEM_DOCUMENT:
            logger_to_use.warning(f"TOC link '{chapter_href}' (Title: {chapter_title}) could not be found or is not a document. Skipping.")
            continue
            
        processed_hrefs.add(chapter_href)
        logger_to_use.debug(f"Processing content from TOC: {item.get_name()} (Title: {chapter_title})")
        
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        
        if not soup.body:
            continue
            
        # --- New: Extract chapter-level metadata ---
        # Extract internal CSS from <head><style>
        internal_css = None
        if soup.head:
            style_tags = soup.head.find_all('style')
            if style_tags:
                internal_css_str = "\n".join(style_tag.string for style_tag in style_tags if style_tag.string)
                if internal_css_str.strip():
                    internal_css = internal_css_str.strip()

        # Extract chapter epub:type from <body> tag's epub:type attribute
        epub_type = soup.body.get('epub:type')
            
        content_blocks: list[AnyBlock] = []
        block_id_counter = 0

        # Find all supported block-level tags in document order.
        # This is more robust than iterating over direct children, as it
        # finds content nested inside <div> or <section> tags.
        # Add div/hr for marker detection.
        tags_to_find = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'img', 'ul', 'ol', 'table', 'div', 'hr']
        for tag in soup.body.find_all(tags_to_find):
            
            # Skip tags that are children of other block elements we are already processing
            # e.g., <p> inside a <li> of a <ul> which would be handled by the list parser.
            # This is a simple but effective way to avoid double-processing.
            # This check is crucial to avoid double-processing content.
            # We want to process block-level elements. If a tag (like a <p>)
            # is inside another element that we already parse completely 
            # (like a <ul> or <table>), we should skip it to let the parent's
            # parser handle it.
            # Plain container tags like <div> should not cause their children to be skipped.
            parent = tag.find_parent(tags_to_find, recursive=False)
            if parent and parent.name in ['table', 'ul', 'ol']:
                 continue

            block_id_counter += 1
            block_id = f"{item.id}_{block_id_counter}"
            css_classes = tag.get('class')
            
            # --- Marker Parser (for things like page breaks) ---
            # This should be checked early. We look for a semantic "epub:type" that
            # indicates a non-content marker.
            epub_type_attr = tag.get('epub:type')
            if epub_type_attr and 'pagebreak' in epub_type_attr:
                content_blocks.append(MarkerBlock(
                    id=block_id,
                    role=epub_type_attr,
                    title=tag.get('title'),
                    css_classes=css_classes
                ))
                continue # This tag is processed, move to the next one.
            
            # --- Heading Parser ---
            if tag.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                level = int(tag.name[1])
                text = tag.get_text().strip()
                if text:
                    content_blocks.append(HeadingBlock(
                        id=block_id,
                        level=level,
                        content_source=text,
                        css_classes=css_classes
                    ))

            # --- Paragraph Parser ---
            elif tag.name == 'p':
                rich_content, tagged_text = _parse_paragraph_tag(tag)
                if tagged_text:
                    content_blocks.append(ParagraphBlock(
                        id=block_id,
                        content_rich_source=rich_content,
                        content_source=tagged_text,
                        css_classes=css_classes
                    ))

            # --- Image Parser ---
            elif tag.name == 'img':
                src = tag.get('src', '')
                alt_text = tag.get('alt', '')
                if src:
                    # Resolve relative path of image src against the chapter's path
                    # e.g., if chapter is at 'text/chap1.xhtml' and src is '../images/img.png',
                    # the absolute path in the epub is 'images/img.png'.
                    absolute_path = urljoin(chapter_href, src)
                    content_blocks.append(ImageBlock(
                        id=block_id,
                        path=absolute_path,
                        content_source=alt_text,
                        css_classes=css_classes
                    ))

            # --- List Parser ---
            elif tag.name in ['ul', 'ol']:
                items = [li.get_text().strip() for li in tag.find_all('li') if li.get_text().strip()]
                if items:
                    content_blocks.append(ListBlock(
                        id=block_id,
                        ordered=(tag.name == 'ol'),
                        content_source=items,
                        css_classes=css_classes
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
                        content_source=TableContent(headers=headers, rows=rows),
                        css_classes=css_classes
                    ))
            
            # --- DIV as Paragraph Parser ---
            elif tag.name == 'div':
                # Heuristic: A div is treated as a paragraph-like content block if it does not
                # contain any other block-level elements. This is to capture content in divs
                # without duplicating content from divs that are only used for wrapping.
                # We check for child tags that are in our master list of blocks.
                if not tag.find_all(tags_to_find, recursive=False):
                    rich_content, tagged_text = _parse_paragraph_tag(tag)
                    if tagged_text:
                        content_blocks.append(ParagraphBlock(
                            id=block_id,
                            content_rich_source=rich_content,
                            content_source=tagged_text,
                            css_classes=css_classes
                        ))
        
        if content_blocks:
            chapters.append(Chapter(
                id=item.get_name(), # Use file name as a unique chapter ID
                title=chapter_title, # Use the accurate title from the TOC
                content=content_blocks,
                epub_type=epub_type,
                internal_css=internal_css
            ))

    if not chapters:
        logger_to_use.warning("No chapters found based on the EPUB's Table of Contents. The resulting book may be empty.")
    else:
        logger_to_use.info(f"Parsing complete. Extracted {len(chapters)} chapters based on TOC.")

    # --- Step 4: Assemble the final Book object ---
    book_model = Book(
        metadata=metadata,
        chapters=chapters,
        image_resources=image_resources,
        css_resources=css_resources
    )

    return book_model