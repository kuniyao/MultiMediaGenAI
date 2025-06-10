# This file will contain the logic for handling the standardized Book object.
# Its primary responsibilities will be:
# 1. Converting the standardized Book object into final output formats (like Markdown).
# 2. Potentially containing helper functions for manipulating the Book object.

import logging
from .book_schema import Book, HeadingBlock, ParagraphBlock, ImageBlock, ListBlock, TableBlock, NoteContentBlock, CodeBlock

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

    # Second, process the content blocks
    if not book.content:
        logger_to_use.warning("No content blocks found in the Book object to convert.")
        md_content.append("[No content to display]")
        return "\n".join(md_content)

    for block in book.content:
        # Pydantic has already validated the block types
        if isinstance(block, HeadingBlock):
            translated_text = block.content_target or block.content_source
            md_content.append(f"{'#' * block.level} {translated_text}")
        
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
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    logger_to_use.info("Converting Book object to EPUB format...")
    # This would be a complex function involving creating XHTML files from blocks
    # and packaging them into an EPUB zip archive.
    raise NotImplementedError("Conversion to EPUB is not yet implemented.")