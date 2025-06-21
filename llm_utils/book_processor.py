from __future__ import annotations
from bs4 import BeautifulSoup, Tag
from format_converters import html_mapper
from format_converters.book_schema import Chapter, Book, AnyBlock, TextItem, HeadingBlock
from typing import List, Dict
from llm_utils.translator import get_model_client
import config
import pathlib
import re

# --- (辅助函数，无需修改) ---
def _get_base_chapter_id(chapter_id: str) -> str:
    """Gets the base ID for a chapter, stripping any '_split_' suffixes."""
    return chapter_id.split('_split_')[0]

def _serialize_blocks_to_html(blocks: List[AnyBlock]) -> str:
    soup = BeautifulSoup('<body></body>', 'html.parser')
    body = soup.body
    if body:
        for block in blocks:
            html_element = html_mapper.map_block_to_html(block, soup)
            if html_element:
                body.append(html_element)
    return body.prettify(formatter="html5")

# --- (extract_translatable_chapters 函数，已加入标记逻辑) ---
def extract_translatable_chapters(book: Book, logger=None) -> list:
    """
    (MODIFIED) Extracts tasks, injects titles into headless chapters, 
    and MARKS them for later removal.
    """
    if logger: logger.info("Initializing model client for token counting...")
    model = get_model_client()
    # ... (Token计算逻辑不变) ...
    effective_input_limit = config.OUTPUT_TOKEN_LIMIT / config.LANGUAGE_EXPANSION_FACTOR
    target_token_per_chunk = effective_input_limit * config.SAFETY_MARGIN
    if logger:
        logger.info("Starting to extract and process translatable chapters...")
        logger.info(f"Model Output Limit: {config.OUTPUT_TOKEN_LIMIT}, Language Expansion Factor: {config.LANGUAGE_EXPANSION_FACTOR}, Safety Margin: {config.SAFETY_MARGIN}")
        logger.info(f"Calculated effective target tokens per chunk: {int(target_token_per_chunk)}")

    translation_tasks = []
    logical_chapters: Dict[str, List[Chapter]] = {}
    for chapter in book.chapters:
        base_id = _get_base_chapter_id(chapter.id)
        if base_id not in logical_chapters:
            logical_chapters[base_id] = []
        logical_chapters[base_id].append(chapter)

    for base_id, chapter_parts in logical_chapters.items():
        first_part = chapter_parts[0]
        
        # We process all chapters now, even metadata ones, to inject titles if needed
        all_blocks = []
        for part in chapter_parts:
            all_blocks.extend(part.content)

        # (MODIFIED) TITLE INJECTION AND MARKING LOGIC
        was_title_injected = False # Our flag/marker
        has_heading = any(isinstance(block, HeadingBlock) for block in all_blocks)

        if not has_heading and first_part.title:
            if logger: logger.info(f"  -> Injecting title '{first_part.title}' as H1 into headless chapter {base_id}")
            injected_heading = HeadingBlock(
                id=f"injected-title-{first_part.id}", level=1,
                content_source=first_part.title, content_target=""
            )
            all_blocks.insert(0, injected_heading)
            was_title_injected = True # Set the mark!

        if not all_blocks:
            if logger: logger.info(f"Skipping logical chapter {base_id} as it has no content.")
            continue

        full_chapter_html = _serialize_blocks_to_html(all_blocks)
        # ... (Token counting and splitting logic is the same) ...
        try:
            # ... (omitted for brevity, same as before) ...
            response = model.count_tokens(full_chapter_html)
            total_tokens = response.total_tokens
        except:
            total_tokens = len(full_chapter_html) // 3 # Fallback if API fails
        
        # When creating tasks, pass the marker
        task_source_data = {
            "id": base_id, 
            "type": "chapter_part", 
            "title_was_injected": was_title_injected # Pass the marker
        }
        # ... (The rest of the splitting logic creates tasks using this source_data) ...
        if total_tokens < target_token_per_chunk:
            task = {"id": f"chapter::{base_id}::part_0", "text_to_translate": full_chapter_html, "source_data": task_source_data}
            translation_tasks.append(task)
        else:
            # Split and create tasks, making sure each task gets the task_source_data
            # ... (omitted for brevity, same as before, but ensuring source_data is passed) ...
            part_number = 0
            current_chunk_blocks = []
            current_chunk_tokens = 0
            for block in all_blocks:
                block_html = _serialize_blocks_to_html([block])
                try:
                    block_tokens = model.count_tokens(block_html).total_tokens
                except:
                    block_tokens = len(block_html) // 3
                if current_chunk_tokens + block_tokens > target_token_per_chunk and current_chunk_blocks:
                    chunk_html = _serialize_blocks_to_html(current_chunk_blocks)
                    task = {"id": f"chapter::{base_id}::part_{part_number}", "text_to_translate": chunk_html, "source_data": task_source_data}
                    translation_tasks.append(task)
                    part_number += 1
                    current_chunk_blocks = [block]
                    current_chunk_tokens = block_tokens
                else:
                    current_chunk_blocks.append(block)
                    current_chunk_tokens += block_tokens
            if current_chunk_blocks:
                chunk_html = _serialize_blocks_to_html(current_chunk_blocks)
                task = {"id": f"chapter::{base_id}::part_{part_number}", "text_to_translate": chunk_html, "source_data": task_source_data}
                translation_tasks.append(task)
                
    if logger: logger.info(f"Extracted {len(translation_tasks)} translation tasks.")
    return translation_tasks

# --- (标题修正辅助函数，无需修改) ---
def _patch_toc_titles(book: Book, chapter_id_map: Dict[str, Chapter], logger):
    # This function is correct from the previous version.
    # No changes needed here.
    # ... (此处代码与上一版完全相同，请保留) ...
    logger.info("Starting TOC title correction post-processing step...")
    toc_chapter = None
    for ch in book.chapters:
        if ch.epub_type and 'toc' in ch.epub_type:
            toc_chapter = ch
            break
        if ch.title:
            if 'contents' in ch.title.lower() or '目录' in ch.title:
                toc_chapter = ch
                break
    if not toc_chapter:
        logger.warning("Could not find ToC chapter by epub:type or title. Skipping title correction.")
        return
    logger.info(f"Found ToC chapter: {toc_chapter.id}. Patching titles...")
    for block in toc_chapter.content:
        content_items_to_patch = []
        if block.type == 'list' and hasattr(block, 'items_source'):
            for item in block.items_source:
                if hasattr(item, 'content'):
                    content_items_to_patch.extend(item.content)
        elif block.type == 'paragraph' and hasattr(block, 'content_rich_source'):
            content_items_to_patch = block.content_rich_source
        for content_item in content_items_to_patch:
            if content_item.type == 'hyperlink':
                href = content_item.href
                try:
                    target_id_path = pathlib.Path(href).name.split('#')[0]
                    base_target_id = _get_base_chapter_id(f"text/{target_id_path}")
                    if base_target_id not in chapter_id_map:
                        base_target_id = _get_base_chapter_id(f"OEBPS/text/{target_id_path}")
                    target_chapter_obj = chapter_id_map.get(base_target_id)
                    if target_chapter_obj and target_chapter_obj.title_target:
                        authoritative_title = target_chapter_obj.title_target
                        original_link_text = "".join(t.content for t in content_item.content if t.type == 'text')
                        match = re.match(r'^\s*([a-zA-Z0-9]+\s*)\s*', original_link_text)
                        prefix = match.group(1) if match else ""
                        new_link_text = f"{prefix}{authoritative_title}".strip()
                        logger.debug(f"  - Correcting link for '{href}' to '{new_link_text}'")
                        content_item.content = [TextItem(content=new_link_text)]
                    else:
                        logger.warning(f"  - Could not find authoritative title for target href '{href}' (mapped to base_id '{base_target_id}')")
                except Exception as e:
                    logger.error(f"Error patching TOC link for href '{href}': {e}")


# --- (update_book_with_translated_html 函数，已加入移除逻辑) ---
def update_book_with_translated_html(book: Book, translated_results: List[Dict], logger):
    """
    (MODIFIED) Updates the book, extracting titles first, and then conditionally
    removing injected titles from the final body content.
    """
    logger.info("Starting to update Book object with translated results...")
    
    # --- STAGE 1: DATA PREPARATION ---
    grouped_translations = {}
    for result in translated_results:
        # ... (grouping logic now includes capturing the marker) ...
        if "[TRANSLATION_FAILED]" in result.get('translated_text', ''):
            logger.warning(f"Translation failed for task {result.get('llm_processing_id')}. Skipping.")
            continue
        try:
            _, base_chapter_id, part_str = result['llm_processing_id'].split('::')
            part_number = int(part_str.split('_')[1])
            title_was_injected = result.get('source_data', {}).get('title_was_injected', False)

            if base_chapter_id not in grouped_translations:
                grouped_translations[base_chapter_id] = {'parts': [], 'title_was_injected': title_was_injected}
            
            grouped_translations[base_chapter_id]['parts'].append((part_number, result['translated_text']))
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not parse ID '{result.get('llm_processing_id', 'N/A')}'. Skipping result. Error: {e}")

    logical_chapter_map: Dict[str, Chapter] = {}
    for ch in book.chapters:
        base_id = _get_base_chapter_id(ch.id)
        if base_id not in logical_chapter_map:
            logical_chapter_map[base_id] = ch

    # --- STAGE 2: CONTENT & TITLE POPULATION (FIRST PASS) ---
    logger.info("--- Pass 1: Populating content and authoritative titles ---")
    for base_id, main_chapter_obj in logical_chapter_map.items():
        if base_id in grouped_translations:
            data = grouped_translations[base_id]
            parts = data['parts']
            title_was_injected = data['title_was_injected']
            
            parts.sort(key=lambda x: x[0])
            full_translated_html = "".join([part[1] for part in parts])
            
            soup = BeautifulSoup(full_translated_html, 'html.parser')
            
            # 1. First, always extract the title for metadata consistency (nav.xhtml)
            new_title = ""
            h_tag = soup.find(['h1', 'h2', 'h3', 'h4'])
            if h_tag:
                cleaned_title = h_tag.get_text(strip=True, separator=' ')
                if cleaned_title:
                    new_title = cleaned_title
            
            if new_title:
                logger.info(f"  - Established authoritative title for '{base_id}': '{new_title}'")
                main_chapter_obj.title_target = new_title
            else:
                logger.warning(f"  - Could NOT establish authoritative title for '{base_id}'.")

            # 2. (NEW) Conditionally remove the injected title from the body content
            if title_was_injected and h_tag:
                logger.info(f"  -> Removing injected title '{new_title}' from final content of {base_id}")
                h_tag.decompose() # Remove the tag and its contents from the soup
            
            # 3. Update the chapter content with the (potentially modified) HTML
            final_html_content = str(soup)
            main_chapter_obj.content = html_mapper.html_to_blocks(final_html_content, book.image_resources, logger)

    # --- STAGE 3: CLEANUP & TOC CORRECTION (SECOND PASS) ---
    # ... (This part is correct from the previous version, no changes needed) ...
    chapters_to_keep = list(logical_chapter_map.values())
    book.chapters = chapters_to_keep
    final_chapter_id_map = {_get_base_chapter_id(ch.id): ch for ch in book.chapters}
    logger.info("--- Pass 2: Correcting ToC page titles ---")
    _patch_toc_titles(book, final_chapter_id_map, logger)
    
    logger.info("Book object update process complete.")