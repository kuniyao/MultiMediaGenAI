# This file will contain the logic for handling the standardized Book object.
# Its primary responsibilities will be:
# 1. Converting the standardized Book object into final output formats (like Markdown).
# 2. Potentially containing helper functions for manipulating the Book object.

import logging
from .book_schema import (
    Book, AnyBlock, HeadingBlock, ParagraphBlock, ImageBlock, ListBlock, TableBlock,
    NoteContentBlock, CodeBlock, RichContentItem, MarkerBlock, LineBreakItem
)
from ebooklib import epub, ITEM_STYLE
from typing import List

def _rich_content_to_html(items: List[RichContentItem]) -> str:
    """Converts a list of RichContentItem objects into an HTML string."""
    html_parts = []
    for item in items:
        if item.type == 'text':
            html_parts.append(item.content)
        elif item.type == 'bold':
            html_parts.append(f"<b>{item.content}</b>")
        elif item.type == 'italic':
            html_parts.append(f"<i>{item.content}</i>")
        elif item.type == 'line_break':
            html_parts.append('<br/>')
        # NoteReferenceItem could be converted to <a> tags if needed
        elif item.type == 'note_reference':
            html_parts.append(f"<sup><a href=\"#note-{item.note_id}\">{item.marker}</a></sup>")
    return "".join(html_parts)

def book_to_markdown(book: Book, logger: logging.Logger = None) -> str:
    """
    Converts a (translated) Book object into a Markdown string.
    This function is generic and works on the standardized Book object, regardless
    of its original source (EPUB, PDF, etc.).
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    logger_to_use.info("Converting Book object to Markdown format...")
    
    md_content = []
    
    # First, add metadata from the Book object
    metadata = book.metadata
    title = metadata.title_target or metadata.title_source
    authors = metadata.author_target or metadata.author_source
    
    md_content.append(f"# {title}")
    if authors:
        md_content.append(f"**By:** {', '.join(authors)}\n")

    # Second, process the chapters and their content blocks
    if not book.chapters:
        logger_to_use.warning("No chapters found in the Book object to convert.")
        md_content.append("[No content to display]")
        return "\n".join(md_content)

    for chapter in book.chapters:
        if chapter.title:
            # We can add a chapter title to the Markdown output.
            # Let's use a level 1 heading for chapter titles for now.
            md_content.append(f"# {chapter.title}")
            
        if not chapter.content:
            logger_to_use.debug(f"Chapter '{chapter.id}' has no content blocks.")
            continue

        for block in chapter.content:
            # Pydantic has already validated the block types
            if isinstance(block, HeadingBlock):
                translated_text = block.content_target or block.content_source
                # We'll adjust heading levels based on the chapter context.
                # For instance, a Level 1 heading in the content might become Level 2 under a chapter title.
                md_content.append(f"{'#' * (block.level + 1)} {translated_text}")
            
            elif isinstance(block, ParagraphBlock):
                # This is simplified; a real version would need to reconstruct rich content
                # For now, we fall back to the plain text source if available
                if block.content_rich_target:
                    # TODO: Implement rich content to markdown conversion
                    text_parts = [item.content for item in block.content_rich_target if hasattr(item, 'content')]
                    translated_text = "".join(text_parts)
                elif block.content_rich_source:
                     text_parts = [item.content for item in block.content_rich_source if hasattr(item, 'content')]
                     translated_text = "".join(text_parts)
                else:
                    translated_text = "[NO PARAGRAPH TEXT FOUND]"
                md_content.append(translated_text)
            
            # ... other block types like lists, images, etc., would be handled here ...
            # Fallback for any unhandled but valid block types
            else:
                block_type = block.type
                # Try to find some text to display as a fallback
                fallback_text = getattr(block, 'content_source', f"[Unsupported Block Type: {block_type}]")
                md_content.append(f"> [Unsupported Block Type: {block_type}]\n> {fallback_text}")
            
    logger_to_use.info("Successfully converted Book object to Markdown.")
    return "\n\n".join(md_content)

# Future function:
def book_to_epub(book: Book, output_path: str, logger: logging.Logger = None):
    """
    Converts a (translated) Book object back into a valid EPUB file.
    
    Note: This implementation does not currently handle image files, as the
    Book model only stores image paths, not the image data itself.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    logger_to_use.info(f"Converting Book object to EPUB format at: {output_path}")

    # --- Step 1: Create a new EPUB book instance ---
    new_book = epub.EpubBook()
    
    # --- Step 2: Set Metadata ---
    metadata = book.metadata
    title = metadata.title_target or metadata.title_source
    new_book.set_title(title)
    
    lang = metadata.language_target or metadata.language_source
    new_book.set_language(lang)

    authors = metadata.author_target or metadata.author_source
    for author in authors:
        new_book.add_author(author)
        
    if metadata.isbn:
        new_book.set_identifier(metadata.isbn)

    # --- New Step: Add CSS Resources to the EPUB ---
    if book.css_resources:
        logger_to_use.info(f"Adding {len(book.css_resources)} CSS resources to the new EPUB.")
        for path, resource in book.css_resources.items():
            # Create a unique ID from path, replacing characters not suitable for IDs.
            uid = path.replace('/', '_').replace('.', '_').replace('-', '_')
            
            css_item = epub.EpubItem(
                uid=uid,
                file_name=path,
                media_type='text/css',
                content=resource.content.encode('utf-8') # CSS content is string, needs encoding
            )
            new_book.add_item(css_item)

    # --- New Step: Add Image Resources to the EPUB ---
    # This must be done before creating chapters that reference them.
    if book.image_resources:
        logger_to_use.info(f"Adding {len(book.image_resources)} images to the new EPUB.")
        for path, resource in book.image_resources.items():
            # Create a unique ID from path, replacing characters not suitable for IDs.
            uid = path.replace('/', '_').replace('.', '_').replace('-', '_')
            
            epub_image = epub.EpubImage(
                uid=uid,
                file_name=path,
                media_type=resource.media_type,
                content=resource.content
            )
            new_book.add_item(epub_image)

    # --- Step 3: Create Content Documents (Chapters) ---
    epub_chapters = []
    for i, chapter in enumerate(book.chapters, start=1):
        chapter_title = chapter.title or f"Chapter {i}"
        file_name = f"chap_{i}.xhtml"
        
        # Create an EPUB HTML object for the chapter
        epub_chapter = epub.EpubHtml(title=chapter_title, file_name=file_name, lang=lang)
        
        # --- New: Construct head with CSS links and internal styles ---
        head_content = f'<title>{chapter_title}</title>'
        
        # Link to global CSS files from css_resources
        for path in book.css_resources:
            # Use relative path for href
            relative_path = path.split('/')[-1]
            head_content += f'<link rel="stylesheet" type="text/css" href="{relative_path}">'
        
        # Add internal CSS from the chapter
        if chapter.internal_css:
            head_content += f'<style type="text/css">\n{chapter.internal_css}\n</style>'
        
        # Assign the constructed head to the chapter object
        if head_content:
            epub_chapter.head = head_content.encode('utf-8')

        # --- New: Construct body tag with epub:type ---
        body_tag = '<body'
        if chapter.epub_type:
            body_tag += f' epub:type="{chapter.epub_type}"'
        body_tag += '>'
        
        body_content = [f"<h1>{chapter_title}</h1>"]
        
        for block in chapter.content:
            # --- New: Add css_classes to all block-level elements ---
            classes = ' '.join(block.css_classes) if block.css_classes else ''
            class_attr = f' class="{classes}"' if classes else ''

            if isinstance(block, HeadingBlock):
                level = block.level + 1  # Adjust for chapter title as h1
                text = block.content_target or block.content_source
                body_content.append(f"<h{level}{class_attr}>{text}</h{level}>")
            
            elif isinstance(block, ParagraphBlock):
                content_items = block.content_rich_target or block.content_rich_source
                html = _rich_content_to_html(content_items)
                if html:
                    body_content.append(f"<p{class_attr}>{html}</p>")
            
            elif isinstance(block, ImageBlock):
                src = block.path
                alt = block.content_target or block.content_source
                body_content.append(f'<img src="{src}" alt="{alt}"{class_attr} />')
            
            elif isinstance(block, ListBlock):
                tag = "ol" if block.ordered else "ul"
                items = block.content_target or block.content_source
                list_items = "".join([f"<li>{item}</li>" for item in items])
                body_content.append(f"<{tag}{class_attr}>{list_items}</{tag}>")
            
            elif isinstance(block, TableBlock):
                table_data = block.content_target or block.content_source
                header_html = ""
                if table_data.headers:
                    header_items = "".join([f"<th>{h}</th>" for h in table_data.headers])
                    header_html = f"<thead><tr>{header_items}</tr></thead>"
                
                rows_html = ""
                if table_data.rows:
                    row_items = "".join([f"<tr>{''.join([f'<td>{cell}</td>' for cell in row])}</tr>" for row in table_data.rows])
                    rows_html = f"<tbody>{row_items}</tbody>"

                body_content.append(f"<table{class_attr}>{header_html}{rows_html}</table>")

            elif isinstance(block, MarkerBlock):
                # Convert markers back to a horizontal rule with its role as a class.
                role_class = block.role.replace(':', '_') if block.role else ''
                title_attr = f' title="{block.title}"' if block.title else ''
                final_class = f'class="{role_class}"' if role_class else ''
                body_content.append(f'<hr {final_class}{title_attr}/>')
                
        # Assemble the full HTML content for the chapter's body
        epub_chapter.content = f'{body_tag}\n' + "\n".join(body_content) + '\n</body>'

        new_book.add_item(epub_chapter)
        epub_chapters.append(epub_chapter)

    # --- Step 4: Define TOC and Spine ---
    new_book.toc = tuple(epub_chapters)
    
    # Add default NCX and Nav file
    new_book.add_item(epub.EpubNcx())
    new_book.add_item(epub.EpubNav())
    
    # Define the "spine" of the book, which dictates the reading order
    new_book.spine = ['nav'] + epub_chapters
    
    # --- Step 5: Write the EPUB file ---
    try:
        epub.write_epub(output_path, new_book, {})
        logger_to_use.info(f"Successfully created EPUB file at {output_path}")
    except Exception as e:
        logger_to_use.error(f"Failed to write EPUB file: {e}")
        raise