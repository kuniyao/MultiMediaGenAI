from __future__ import annotations
from bs4 import BeautifulSoup
from format_converters import html_mapper
from format_converters.book_schema import Chapter, Book, AnyBlock, TextItem
from typing import List, Dict
from llm_utils.translator import get_model_client
import config
import pathlib

# --- 1. NEW HELPER FUNCTIONS (新增的辅助函数) ---

def _get_base_chapter_id(chapter_id: str) -> str:
    """Gets the base ID for a chapter, stripping any '_split_' suffixes."""
    return chapter_id.split('_split_')[0]

def _serialize_blocks_to_html(blocks: List[AnyBlock]) -> str:
    """Helper function to serialize a list of Block objects to an HTML string."""
    soup = BeautifulSoup('<body></body>', 'html.parser')
    body = soup.body
    for block in blocks:
        html_element = html_mapper.map_block_to_html(block, soup)
        if html_element:
            body.append(html_element)
    return body.prettify(formatter="html5")

# --- 2. REFACTORED extract_translatable_chapters (重构的章节提取函数) ---

def extract_translatable_chapters(book: Book, logger=None) -> list:
    """
    (MODIFIED) Extracts translatable content by grouping split files into logical chapters,
    then creates translation tasks. Splits large logical chapters by token count.
    """
    if logger:
        logger.info("Initializing model client for token counting...")
    model = get_model_client()
    
    effective_input_limit = config.OUTPUT_TOKEN_LIMIT / config.LANGUAGE_EXPANSION_FACTOR
    target_token_per_chunk = effective_input_limit * config.SAFETY_MARGIN
    
    if logger:
        logger.info("Starting to extract and process translatable chapters...")
        logger.info(f"Model Output Limit: {config.OUTPUT_TOKEN_LIMIT}, Language Expansion Factor: {config.LANGUAGE_EXPANSION_FACTOR}, Safety Margin: {config.SAFETY_MARGIN}")
        logger.info(f"Calculated effective target tokens per chunk: {int(target_token_per_chunk)}")
        
    translation_tasks = []
    
    # (NEW) Group chapters by their base ID to form logical chapters
    logical_chapters: Dict[str, List[Chapter]] = {}
    for chapter in book.chapters:
        base_id = _get_base_chapter_id(chapter.id)
        if base_id not in logical_chapters:
            logical_chapters[base_id] = []
        logical_chapters[base_id].append(chapter)

    # (MODIFIED) Iterate over logical chapters, not individual files
    for base_id, chapter_parts in logical_chapters.items():
        # Skip non-content chapters
        first_part = chapter_parts[0]
        if first_part.epub_type and any(t in first_part.epub_type for t in ['toc', 'cover', 'copyright', 'titlepage']):
            if logger:
                logger.info(f"Skipping logical chapter {base_id} due to its type: {first_part.epub_type}")
            continue

        # (NEW) Concatenate content from all parts of the logical chapter
        all_blocks = []
        for part in chapter_parts:
            all_blocks.extend(part.content)

        if not all_blocks:
            if logger:
                logger.info(f"Skipping logical chapter {base_id} as it has no content.")
            continue

        full_chapter_html = _serialize_blocks_to_html(all_blocks)
        if not full_chapter_html.strip():
            if logger:
                logger.info(f"Skipping logical chapter {base_id} because its serialized HTML is empty.")
            continue
            
        try:
            response = model.count_tokens(full_chapter_html)
            total_tokens = response.total_tokens
            if logger:
                logger.info(f"Logical chapter {base_id} has an estimated {total_tokens} tokens.")
        except Exception as e:
            if logger:
                logger.error(f"Could not count tokens for chapter {base_id}: {e}. Skipping chapter.")
            continue

        # Decision point: Split or not?
        if total_tokens < target_token_per_chunk:
            task = {
                "id": f"chapter::{base_id}::part_0",
                "text_to_translate": full_chapter_html,
                "source_data": {"id": base_id, "type": "chapter_part"}
            }
            translation_tasks.append(task)
            if logger:
                logger.info(f"  -> Logical chapter is small enough. Created one task.")
        else:
            if logger:
                logger.info(f"  -> Logical chapter exceeds token limit ({int(target_token_per_chunk)}). Splitting into smaller chunks...")
            
            # (MODIFIED) The splitting logic now works on the combined 'all_blocks' list
            part_number = 0
            current_chunk_blocks = []
            current_chunk_tokens = 0

            for block in all_blocks:
                block_html = _serialize_blocks_to_html([block])
                try:
                    block_tokens = model.count_tokens(block_html).total_tokens
                except Exception as e:
                    if logger:
                        logger.warning(f"Could not count tokens for a block in {base_id}. Skipping block. Error: {e}")
                    continue

                if current_chunk_tokens + block_tokens > target_token_per_chunk and current_chunk_blocks:
                    chunk_html = _serialize_blocks_to_html(current_chunk_blocks)
                    task = {
                        "id": f"chapter::{base_id}::part_{part_number}",
                        "text_to_translate": chunk_html,
                        "source_data": {"id": base_id, "type": "chapter_part"}
                    }
                    translation_tasks.append(task)
                    if logger:
                        logger.info(f"    - Created chunk part_{part_number} with {current_chunk_tokens} tokens.")
                    
                    part_number += 1
                    current_chunk_blocks = [block]
                    current_chunk_tokens = block_tokens
                else:
                    current_chunk_blocks.append(block)
                    current_chunk_tokens += block_tokens

            if current_chunk_blocks:
                chunk_html = _serialize_blocks_to_html(current_chunk_blocks)
                task = {
                    "id": f"chapter::{base_id}::part_{part_number}",
                    "text_to_translate": chunk_html,
                    "source_data": {"id": base_id, "type": "chapter_part"}
                }
                translation_tasks.append(task)
                if logger:
                    logger.info(f"    - Created final chunk part_{part_number} with {current_chunk_tokens} tokens.")

    if logger:
        logger.info(f"Extracted {len(translation_tasks)} translation tasks from {len(logical_chapters)} logical chapters.")

    return translation_tasks

# --- 3. NEW TITLE CORRECTION FUNCTION (新增的标题修正函数) ---

def _patch_toc_titles(book: Book, chapter_id_map: Dict[str, Chapter], logger):
    """(NEW) Post-processing step to correct titles in the ToC page."""
    logger.info("Starting TOC title correction post-processing step...")

    # Find the ToC chapter
    toc_chapter = None
    for ch in book.chapters:
        # Check epub_type safely
        if ch.epub_type and 'toc' in ch.epub_type:
            toc_chapter = ch
            break
            
    if not toc_chapter:
        logger.info("No ToC chapter found. Skipping title correction.")
        return

    logger.info(f"Found ToC chapter: {toc_chapter.id}. Patching titles...")
    
    # Iterate through its content blocks to find and update hyperlink texts
    for block in toc_chapter.content:
        if block.type == 'list':
            for item in block.items_source:  # Assuming we patch the source list items
                for content_item in item.content:
                    if content_item.type == 'hyperlink':
                        href = content_item.href
                        # Normalize href to match chapter IDs (e.g., remove '../' or anchors)
                        target_id = str(pathlib.Path(href).name).split('#')[0]
                        
                        # Find the authoritative title from our map
                        target_chapter_obj = chapter_id_map.get(_get_base_chapter_id(f"text/{target_id}"))

                        if target_chapter_obj and target_chapter_obj.title_target:
                            logger.debug(f"  - Correcting link for '{target_id}' to '{target_chapter_obj.title_target}'")
                            # Replace the link's text with the authoritative title
                            content_item.content = [TextItem(content=target_chapter_obj.title_target)]
                        else:
                            logger.warning(f"  - Could not find authoritative title for target '{target_id}'")

# --- 4. REFACTORED update_book_with_translated_html (重构的更新函数) ---

def update_book_with_translated_html(book: Book, translated_results: List[Dict], logger):
    """
    (MODIFIED) Updates the Book object. It reassembles logical chapters,
    updates their content, establishes an authoritative title, and then
    patches the ToC page to ensure title consistency.
    """
    logger.info("Starting to update Book object with translated results...")
    
    grouped_translations = {}
    for result in translated_results:
        if "[TRANSLATION_FAILED]" in result.get('translated_text', ''):
            logger.warning(f"Translation failed for task {result.get('llm_processing_id')}. Skipping.")
            continue
        try:
            _, base_chapter_id, part_str = result['llm_processing_id'].split('::')
            part_number = int(part_str.split('_')[1])
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not parse ID '{result.get('llm_processing_id', 'N/A')}'. Skipping result. Error: {e}")
            continue

        if base_chapter_id not in grouped_translations:
            grouped_translations[base_chapter_id] = []
        grouped_translations[base_chapter_id].append((part_number, result['translated_text']))

    chapters_to_keep = []
    chapter_id_map = {ch.id: ch for ch in book.chapters} # For quick lookup

    processed_base_ids = set()

    for chapter in book.chapters:
        base_id = _get_base_chapter_id(chapter.id)

        if base_id in processed_base_ids:
            # This is a subsequent part of an already processed logical chapter, skip it.
            logger.info(f"Skipping redundant chapter part: {chapter.id}")
            continue

        if base_id in grouped_translations:
            # This is the first part of a logical chapter that was translated.
            logger.info(f"Reassembling and updating logical chapter: {base_id}")
            
            parts = grouped_translations[base_id]
            parts.sort(key=lambda x: x[0])
            full_translated_html = "".join([part[1] for part in parts])
            
            target_chapter = chapter # Update the first chapter part
            
            new_blocks = html_mapper.html_to_blocks(full_translated_html, book.image_resources, logger)
            target_chapter.content = new_blocks
            
            soup = BeautifulSoup(full_translated_html, 'html.parser')
            h_tags = soup.find(['h1', 'h2', 'h3', 'h4'])
            if h_tags and h_tags.text:
                new_title = h_tags.text.strip()
                if new_title:
                    logger.info(f"  - Updating title for {base_id} from H-tag to: '{new_title}'")
                    # Update the title for all original parts of this logical chapter
                    for original_part in book.chapters:
                        if _get_base_chapter_id(original_part.id) == base_id:
                             original_part.title_target = new_title

            chapters_to_keep.append(target_chapter)
            processed_base_ids.add(base_id)
        else:
            # This chapter was not in the translation results (e.g., skipped), keep it as is.
            chapters_to_keep.append(chapter)

    # (NEW) Replace the old chapter list with the new one that has merged content
    book.chapters = chapters_to_keep
    
    # (NEW) Create a new map for the patched chapters for the final correction step
    final_chapter_id_map = {ch.id: ch for ch in book.chapters}
    
    # (NEW) Run the final title correction pass
    _patch_toc_titles(book, final_chapter_id_map, logger)
    
    logger.info("Book object update process complete.")