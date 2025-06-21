from __future__ import annotations
from bs4 import BeautifulSoup, Tag
from format_converters import html_mapper
from format_converters.book_schema import Chapter, Book, AnyBlock, TextItem
from typing import List, Dict
from llm_utils.translator import get_model_client
import config
import pathlib
import re

# --- (辅助函数，无需修改) ---
def _get_base_chapter_id(chapter_id: str) -> str:
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

# --- (extract_translatable_chapters 函数，无需修改) ---
def extract_translatable_chapters(book: Book, logger=None) -> list:
    # This function is correct from the previous version.
    # No changes needed here.
    # ... (此处代码与上一版完全相同，请保留) ...
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
    logical_chapters: Dict[str, List[Chapter]] = {}
    for chapter in book.chapters:
        base_id = _get_base_chapter_id(chapter.id)
        if base_id not in logical_chapters:
            logical_chapters[base_id] = []
        logical_chapters[base_id].append(chapter)
    for base_id, chapter_parts in logical_chapters.items():
        first_part = chapter_parts[0]
        if first_part.epub_type and any(t in first_part.epub_type for t in ['toc', 'cover', 'copyright', 'titlepage']):
            if logger:
                logger.info(f"Skipping logical chapter {base_id} due to its type: {first_part.epub_type}")
            continue
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
                    task = {"id": f"chapter::{base_id}::part_{part_number}", "text_to_translate": chunk_html, "source_data": {"id": base_id, "type": "chapter_part"}}
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
                task = {"id": f"chapter::{base_id}::part_{part_number}", "text_to_translate": chunk_html, "source_data": {"id": base_id, "type": "chapter_part"}}
                translation_tasks.append(task)
                if logger:
                    logger.info(f"    - Created final chunk part_{part_number} with {current_chunk_tokens} tokens.")
    if logger:
        logger.info(f"Extracted {len(translation_tasks)} translation tasks from {len(logical_chapters)} logical chapters.")
    return translation_tasks

# --- (标题修正辅助函数，已修正) ---
# book_processor.py -> 只替换这个函数

def _patch_toc_titles(book: Book, chapter_id_map: Dict[str, Chapter], logger):
    """(FINAL, ROBUST VERSION) Patches titles in the ToC, handling both list-based and paragraph-based ToCs."""
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
    
    # 遍历目录章节里的每一个内容块
    for block in toc_chapter.content:
        
        # (MODIFIED) 核心修改：准备一个列表，用来存放需要被检查和修正的富文本内容
        content_items_to_patch = []
        
        # 如果这个块是列表(ul/ol)，就从列表项中提取内容
        if block.type == 'list' and hasattr(block, 'items_source'):
            for item in block.items_source:
                if hasattr(item, 'content'):
                    content_items_to_patch.extend(item.content)
        # 如果这个块是段落(p)，就直接从段落中提取内容
        elif block.type == 'paragraph' and hasattr(block, 'content_rich_source'):
            content_items_to_patch = block.content_rich_source

        # 统一对提取出的富文本内容进行遍历和修正
        for content_item in content_items_to_patch:
            if content_item.type == 'hyperlink':
                href = content_item.href
                try:
                    # 使用pathlib来安全地处理路径
                    target_id_path = pathlib.Path(href).name.split('#')[0]
                    
                    # 假定所有章节文件都在 'text/' 目录下，这是一个安全的通用假设
                    full_target_id = f"text/{target_id_path}"
                    base_target_id = _get_base_chapter_id(full_target_id)
                    
                    target_chapter_obj = chapter_id_map.get(base_target_id)

                    if target_chapter_obj and target_chapter_obj.title_target:
                        # 获取权威标题
                        authoritative_title = target_chapter_obj.title_target
                        
                        # 尝试保留链接前的数字（如果存在）
                        original_link_text = "".join(t.content for t in content_item.content if t.type == 'text')
                        match = re.match(r'^\s*(\d+\s*)\s*', original_link_text)
                        prefix = match.group(1) if match else ""
                        
                        new_link_text = f"{prefix}{authoritative_title}"
                        
                        logger.debug(f"  - Correcting link for '{href}' to '{new_link_text}'")
                        content_item.content = [TextItem(content=new_link_text)]
                    else:
                        logger.warning(f"  - Could not find authoritative title for target '{href}'")
                except Exception as e:
                    logger.error(f"Error patching TOC link for href '{href}': {e}")

# --- (update_book_with_translated_html 函数，已修正) ---
def update_book_with_translated_html(book: Book, translated_results: List[Dict], logger):
    """(REWRITTEN) Updates the Book object with a robust, two-pass approach."""
    logger.info("Starting to update Book object with translated results...")
    
    # --- STAGE 1: DATA PREPARATION ---
    grouped_translations = {}
    for result in translated_results:
        if "[TRANSLATION_FAILED]" in result.get('translated_text', ''):
            logger.warning(f"Translation failed for task {result.get('llm_processing_id')}. Skipping.")
            continue
        try:
            _, base_chapter_id, part_str = result['llm_processing_id'].split('::')
            part_number = int(part_str.split('_')[1])
            if base_chapter_id not in grouped_translations:
                grouped_translations[base_chapter_id] = []
            grouped_translations[base_chapter_id].append((part_number, result['translated_text']))
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
            parts = grouped_translations[base_id]
            parts.sort(key=lambda x: x[0])
            full_translated_html = "".join([part[1] for part in parts])
            
            main_chapter_obj.content = html_mapper.html_to_blocks(full_translated_html, book.image_resources, logger)
            
            soup = BeautifulSoup(full_translated_html, 'html.parser')
            
            # (MODIFIED) More specific and robust title finding logic
            new_title = ""
            h_tag = soup.find('h2', class_='h') # Specific finder for main title
            if not h_tag:
                h_tag = soup.find(['h1', 'h2', 'h3', 'h4']) # Fallback to general finder
            
            if h_tag:
                # Use .get_text() to handle complex inner tags like <a><strong>...</strong></a>
                cleaned_title = h_tag.get_text(strip=True, separator=' ')
                if cleaned_title:
                    new_title = cleaned_title

            if new_title:
                logger.info(f"  - Established authoritative title for '{base_id}': '{new_title}'")
                main_chapter_obj.title_target = new_title
            else:
                logger.warning(f"  - Could NOT establish authoritative title for '{base_id}'. nav.xhtml might be incorrect.")

    # --- STAGE 3: CLEANUP & TOC CORRECTION (SECOND PASS) ---
    chapters_to_keep = list(logical_chapter_map.values())
    book.chapters = chapters_to_keep
    
    final_chapter_id_map = {_get_base_chapter_id(ch.id): ch for ch in book.chapters}
    
    logger.info("--- Pass 2: Correcting ToC page titles ---")
    _patch_toc_titles(book, final_chapter_id_map, logger)
    
    logger.info("Book object update process complete.")