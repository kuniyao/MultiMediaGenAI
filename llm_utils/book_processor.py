from __future__ import annotations
from bs4 import BeautifulSoup
from format_converters import html_mapper
from format_converters.book_schema import Chapter, Book, AnyBlock
from typing import List, Dict
from llm_utils.translator import get_model_client
import config


def _serialize_blocks_to_html(blocks: List[AnyBlock]) -> str:
    """Helper function to serialize a list of Block objects to an HTML string."""
    soup = BeautifulSoup('<body></body>', 'html.parser')
    body = soup.body
    for block in blocks:
        html_element = html_mapper.map_block_to_html(block, soup)
        if html_element:
            body.append(html_element)
    return body.prettify(formatter="html5")


def chapter_content_to_html(chapter: Chapter) -> str:
    """
    Serializes the content of a single Chapter object back into an HTML string.
    This function now uses the internal helper for serialization.
    """
    return _serialize_blocks_to_html(chapter.content)


def extract_translatable_chapters(book: Book, logger=None) -> list:
    """
    Extracts all translatable content from the Book object and generates a list
    of translation tasks. If a chapter's token count exceeds the configured limit,
    it is intelligently split into multiple smaller tasks (chunks).
    """
    if logger:
        logger.info("Initializing model client for token counting...")
    model = get_model_client()
    
    # Calculate the effective target token size for a single input chunk.
    # This accounts for the expected expansion in token count after translation.
    effective_input_limit = config.OUTPUT_TOKEN_LIMIT / config.LANGUAGE_EXPANSION_FACTOR
    target_token_per_chunk = effective_input_limit * config.SAFETY_MARGIN
    
    if logger:
        logger.info("Starting to extract and process translatable chapters...")
        logger.info(f"Model Output Limit: {config.OUTPUT_TOKEN_LIMIT}, Language Expansion Factor: {config.LANGUAGE_EXPANSION_FACTOR}, Safety Margin: {config.SAFETY_MARGIN}")
        logger.info(f"Calculated effective target tokens per chunk: {int(target_token_per_chunk)}")
        
    translation_tasks = []
    
    for i, chapter in enumerate(book.chapters):
        if chapter.epub_type and any(t in chapter.epub_type for t in ['toc', 'cover', 'copyright', 'titlepage']):
            if logger:
                logger.info(f"Skipping chapter {i} (ID: {chapter.id}, Title: {chapter.title}) due to its type: {chapter.epub_type}")
            continue

        if not chapter.content:
            if logger:
                logger.info(f"Skipping chapter {i} (ID: {chapter.id}, Title: {chapter.title}) as it has no content.")
            continue

        full_chapter_html = _serialize_blocks_to_html(chapter.content)
        if not full_chapter_html.strip():
            if logger:
                logger.info(f"Skipping chapter {i} (ID: {chapter.id}, Title: {chapter.title}) because its serialized HTML is empty.")
            continue
            
        try:
            response = model.count_tokens(full_chapter_html)
            total_tokens = response.total_tokens
            if logger:
                logger.info(f"Chapter {i} (ID: {chapter.id}) has an estimated {total_tokens} tokens.")
        except Exception as e:
            if logger:
                logger.error(f"Could not count tokens for chapter {chapter.id}: {e}. Skipping chapter.")
            continue

        # Decision point: Split or not?
        if total_tokens < target_token_per_chunk:
            # Chapter is small enough, create a single task
            task = {
                "id": f"chapter::{chapter.id}::part_0",
                "text_to_translate": full_chapter_html,
                "source_data": {"id": chapter.id, "type": "chapter_part"}
            }
            translation_tasks.append(task)
            if logger:
                logger.info(f"  -> Chapter is small enough. Created one task.")
        else:
            # Chapter needs to be split
            if logger:
                logger.info(f"  -> Chapter exceeds token limit ({int(target_token_per_chunk)}). Splitting into smaller chunks...")
            
            part_number = 0
            current_chunk_blocks = []
            current_chunk_tokens = 0

            for block in chapter.content:
                block_html = _serialize_blocks_to_html([block])
                try:
                    block_tokens = model.count_tokens(block_html).total_tokens
                except Exception as e:
                    if logger:
                        logger.warning(f"Could not count tokens for a block in {chapter.id}. Skipping block. Error: {e}")
                    continue

                if current_chunk_tokens + block_tokens > target_token_per_chunk and current_chunk_blocks:
                    # Finalize the current chunk and create a task
                    chunk_html = _serialize_blocks_to_html(current_chunk_blocks)
                    task = {
                        "id": f"chapter::{chapter.id}::part_{part_number}",
                        "text_to_translate": chunk_html,
                        "source_data": {"id": chapter.id, "type": "chapter_part"}
                    }
                    translation_tasks.append(task)
                    if logger:
                        logger.info(f"    - Created chunk part_{part_number} with {current_chunk_tokens} tokens.")
                    
                    # Reset for the next chunk
                    part_number += 1
                    current_chunk_blocks = []
                    current_chunk_tokens = 0

                # Add the current block to the new chunk
                current_chunk_blocks.append(block)
                current_chunk_tokens += block_tokens

            # Create a task for the last remaining chunk
            if current_chunk_blocks:
                chunk_html = _serialize_blocks_to_html(current_chunk_blocks)
                task = {
                    "id": f"chapter::{chapter.id}::part_{part_number}",
                    "text_to_translate": chunk_html,
                    "source_data": {"id": chapter.id, "type": "chapter_part"}
                }
                translation_tasks.append(task)
                if logger:
                    logger.info(f"    - Created final chunk part_{part_number} with {current_chunk_tokens} tokens.")

    if logger:
        logger.info(f"Extracted {len(translation_tasks)} translation tasks from {len(book.chapters)} chapters.")

    return translation_tasks


def update_book_with_translated_html(book: Book, translated_results: List[Dict], logger):
    """
    Updates the Book object using the translated HTML results. It correctly
    handles and reassembles chapters that were split into multiple parts.
    """
    logger.info("Starting to update Book object with translated results...")
    
    # Group translated parts by their base chapter ID
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
        
        grouped_translations[base_chapter_id].append(
            (part_number, result['translated_text'])
        )

    # Process each chapter's grouped and translated parts
    for chapter_id, parts in grouped_translations.items():
        logger.info(f"Reassembling and updating chapter: {chapter_id}")
        
        # Sort parts by their part number to ensure correct order
        parts.sort(key=lambda x: x[0])
        
        # Concatenate the HTML content of all parts
        full_translated_html = "".join([part[1] for part in parts])
        
        # Find the corresponding chapter in the book
        target_chapter = next((ch for ch in book.chapters if ch.id == chapter_id), None)
        
        if not target_chapter:
            logger.warning(f"Could not find chapter with ID '{chapter_id}' in the book to update.")
            continue
            
        # 1. Deserialize the reassembled HTML back into Block objects
        new_blocks = html_mapper.html_to_blocks(full_translated_html, book.image_resources, logger)
        
        # 2. Replace the chapter's original content
        target_chapter.content = new_blocks
        
        # 3. Attempt to update the chapter title from the new content
        soup = BeautifulSoup(full_translated_html, 'html.parser')
        h_tags = soup.find(['h1', 'h2', 'h3', 'h4'])
        if h_tags and h_tags.text:
            new_title = h_tags.text.strip()
            if new_title:
                logger.info(f"  - Updating title from H-tag to: '{new_title}'")
                target_chapter.title = new_title
                target_chapter.title_target = new_title
    
    logger.info("Book object update process complete.")