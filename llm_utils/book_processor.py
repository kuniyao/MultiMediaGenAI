# llm_utils/book_processor.py (FINAL VERSION)

from __future__ import annotations
from bs4 import BeautifulSoup, Tag
from format_converters import html_mapper
from format_converters.book_schema import Chapter, Book, AnyBlock, TextItem, HeadingBlock
from typing import List, Dict
from llm_utils.translator import get_model_client
import config
import pathlib
import re
import copy
import json

# --- (輔助函數，無需修改) ---
def _get_base_chapter_id(chapter_id: str) -> str:
    """獲取章節的基礎ID，剝離任何 '_split_' 後綴。"""
    return chapter_id.split('_split_')[0]

def _serialize_blocks_to_html(blocks: List[AnyBlock], soup: BeautifulSoup) -> str:
    """將一個塊列表序列化為一個HTML字符串。"""
    body = soup.new_tag('body')
    for block in blocks:
        html_element = html_mapper.map_block_to_html(block, soup)
        if html_element:
            body.append(html_element)
    return ''.join(str(child) for child in body.children)

# --- (提取和打包函數，無需修改) ---
def extract_translatable_chapters(book: Book, logger=None) -> list:
    if logger: logger.info("Initializing model client for token counting...")
    model = get_model_client(logger=logger)
    if not model:
        if logger: logger.critical("Failed to initialize the model client. Cannot proceed. Aborting.")
        return []

    effective_input_limit = config.OUTPUT_TOKEN_LIMIT / config.LANGUAGE_EXPANSION_FACTOR
    target_token_per_chunk = int(effective_input_limit * config.SAFETY_MARGIN)
    if logger: logger.info(f"Target tokens per LLM chunk calculated: {target_token_per_chunk}")

    translation_tasks = []
    current_batch_chapters_payload = []
    current_batch_tokens = 0
    soup_for_serialization = BeautifulSoup('', 'html.parser')

    for chapter in book.chapters:
        if not chapter.content:
            if logger: logger.info(f"Skipping chapter '{chapter.id}' as it has no content.")
            continue
        
        chapter_html = _serialize_blocks_to_html(chapter.content, soup_for_serialization)
        try:
            token_count = model.count_tokens(chapter_html).total_tokens
        except Exception as e:
            if logger: logger.warning(f"Token count API failed for chapter {chapter.id}. Falling back to char estimation. Error: {e}")
            token_count = len(chapter_html) // 3

        if token_count > target_token_per_chunk:
            if logger: logger.info(f"Chapter '{chapter.id}' ({token_count} tokens) is too large, applying splitting strategy.")
            
            if current_batch_chapters_payload:
                if logger: logger.info(f"Finalizing current batch of {len(current_batch_chapters_payload)} chapters before splitting.")
                batch_task_id = f"batch::{current_batch_chapters_payload[0]['id']}::to::{current_batch_chapters_payload[-1]['id']}"
                batch_json_string = json.dumps(current_batch_chapters_payload, ensure_ascii=False)
                translation_tasks.append({
                    "llm_processing_id": batch_task_id,
                    "text_to_translate": batch_json_string,
                    "source_data": {"type": "json_batch", "chapter_count": len(current_batch_chapters_payload)}
                })
                current_batch_chapters_payload = []
                current_batch_tokens = 0

            part_number = 0
            current_split_blocks = []
            current_split_tokens = 0
            for block in chapter.content:
                block_html = _serialize_blocks_to_html([block], soup_for_serialization)
                try:
                    block_tokens = model.count_tokens(block_html).total_tokens
                except:
                    block_tokens = len(block_html) // 3
                
                if current_split_tokens + block_tokens > target_token_per_chunk and current_split_blocks:
                    chunk_html = _serialize_blocks_to_html(current_split_blocks, soup_for_serialization)
                    task_id = f"split::{chapter.id}::part_{part_number}"
                    translation_tasks.append({ "llm_processing_id": task_id, "text_to_translate": chunk_html, "source_data": {"type": "split_part", "original_chapter_id": chapter.id, "part_number": part_number}})
                    part_number += 1
                    current_split_blocks = [block]
                    current_split_tokens = block_tokens
                else:
                    current_split_blocks.append(block)
                    current_split_tokens += block_tokens
            
            if current_split_blocks:
                chunk_html = _serialize_blocks_to_html(current_split_blocks, soup_for_serialization)
                task_id = f"split::{chapter.id}::part_{part_number}"
                translation_tasks.append({ "llm_processing_id": task_id, "text_to_translate": chunk_html, "source_data": {"type": "split_part", "original_chapter_id": chapter.id, "part_number": part_number}})
        else:
            if current_batch_chapters_payload and (current_batch_tokens + token_count > target_token_per_chunk):
                if logger: logger.info(f"Current batch full. Finalizing batch of {len(current_batch_chapters_payload)} chapters.")
                batch_task_id = f"batch::{current_batch_chapters_payload[0]['id']}::to::{current_batch_chapters_payload[-1]['id']}"
                batch_json_string = json.dumps(current_batch_chapters_payload, ensure_ascii=False)
                translation_tasks.append({
                    "llm_processing_id": batch_task_id,
                    "text_to_translate": batch_json_string,
                    "source_data": {"type": "json_batch", "chapter_count": len(current_batch_chapters_payload)}
                })
                current_batch_chapters_payload = []
                current_batch_tokens = 0
            
            if logger: logger.info(f"Adding chapter '{chapter.id}' ({token_count} tokens) to current batch.")
            current_batch_chapters_payload.append({"id": chapter.id, "html_content": chapter_html})
            current_batch_tokens += token_count

    if current_batch_chapters_payload:
        if logger: logger.info(f"Finalizing the last batch of {len(current_batch_chapters_payload)} chapters.")
        batch_task_id = f"batch::{current_batch_chapters_payload[0]['id']}::to::{current_batch_chapters_payload[-1]['id']}"
        batch_json_string = json.dumps(current_batch_chapters_payload, ensure_ascii=False)
        translation_tasks.append({
            "llm_processing_id": batch_task_id,
            "text_to_translate": batch_json_string,
            "source_data": {"type": "json_batch", "chapter_count": len(current_batch_chapters_payload)}
        })

    if logger: logger.info(f"Extracted {len(book.chapters)} chapters into {len(translation_tasks)} translation tasks.")
    return translation_tasks

# --- (标题修正辅助函数，無需修改) ---
def _patch_toc_titles(book: Book, chapter_id_map: Dict[str, Chapter], logger):
    logger.info("Starting TOC title correction post-processing step...")
    toc_chapter = None
    for ch in book.chapters:
        if ch.epub_type and 'toc' in ch.epub_type:
            toc_chapter = ch
            break
        if ch.title and ('contents' in ch.title.lower() or '目录' in ch.title):
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
                if hasattr(item, 'content'): content_items_to_patch.extend(item.content)
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
                        if logger: logger.debug(f"  - Correcting link for '{href}' to '{new_link_text}'")
                        content_item.content = [TextItem(content=new_link_text)]
                    else:
                        if logger: logger.warning(f"  - Could not find authoritative title for target href '{href}' (mapped to base_id '{base_target_id}')")
                except Exception as e:
                    if logger: logger.error(f"Error patching TOC link for href '{href}': {e}")


# --- (核心修改：應用翻譯的最終實現) ---
def apply_translations_to_book(original_book: Book, translated_results: list[dict], logger) -> Book:
    """
    【最終實現 - 已修正】
    將翻譯結果（包括批處理和拆分的部分）應用回Book對象，並重建完整的翻譯書籍。
    """
    if logger: logger.info("Applying all translations to create the final Book object...")
    
    # STAGE 1: 數據準備
    translated_book = copy.deepcopy(original_book)
    chapter_map = {ch.id: ch for ch in translated_book.chapters}
    grouped_split_parts: Dict[str, List[Dict]] = {} 

    # STAGE 2: 遍歷翻譯結果，解包並更新/收集內容
    for result in translated_results:
        task_id = result["llm_processing_id"]
        source_data = result["source_data"]
        task_type = source_data.get("type")
        translated_text = result["translated_text"]

        if "[TRANSLATION_FAILED]" in translated_text:
            logger.warning(f"Translation failed for task {task_id}. Skipping application.")
            continue
            
        # 策略一：直接應用批處理任務 (JSON Batch)
        if task_type == 'json_batch':
            try:
                # 【數據清洗】
                cleaned_json_text = re.sub(r'(<a href=\\"\\\"></a>)+', '', translated_text)
                
                translated_chapters = json.loads(cleaned_json_text)
                for translated_chapter in translated_chapters:
                    chapter_id = translated_chapter['id']
                    html_content = translated_chapter['html_content']
                    if chapter_id in chapter_map:
                        target_chapter = chapter_map[chapter_id]
                        logger.info(f"Applying translated content for chapter '{chapter_id}' from batch task '{task_id}'.")
                        target_chapter.content = html_mapper.html_to_blocks(html_content, translated_book.image_resources, logger)
                    else:
                        logger.warning(f"From batch task {task_id}, found chapter_id '{chapter_id}' which is not in the book map.")
            except json.JSONDecodeError:
                logger.error(f"Failed to decode JSON from batch task {task_id}. Skipping this batch.")
            except Exception as e:
                logger.error(f"An unexpected error occurred while processing batch task {task_id}: {e}", exc_info=True)

        # 策略二：僅收集被拆分的大章節部分，以便後續統一重組
        elif task_type == 'split_part':
            original_chapter_id = source_data['original_chapter_id']
            if original_chapter_id not in grouped_split_parts:
                grouped_split_parts[original_chapter_id] = []
            grouped_split_parts[original_chapter_id].append(result)
        
        else:
            logger.warning(f"Unknown task type '{task_type}' in result for task ID {task_id}.")

    # STAGE 3: 重組並應用被拆分的大章節
    for chapter_id, parts in grouped_split_parts.items():
        if logger: logger.info(f"Re-assembling {len(parts)} split parts for chapter '{chapter_id}'...")
        parts.sort(key=lambda p: p['source_data']['part_number'])
        
        # 【數據清洗】同樣應用於拆分部分
        cleaned_parts_html = [re.sub(r'(<a href=\\"\\\"></a>)+', '', p['translated_text']) for p in parts]
        full_html_content = "".join(cleaned_parts_html)
        
        if chapter_id in chapter_map:
            target_chapter = chapter_map[chapter_id]
            logger.info(f"Applying re-assembled content for split chapter '{chapter_id}'.")
            target_chapter.content = html_mapper.html_to_blocks(full_html_content, translated_book.image_resources, logger)
        else:
            logger.warning(f"Could not find original chapter '{chapter_id}' to apply re-assembled split parts.")

    # STAGE 4 & 5 (提取標題和修正目錄) ... 保持不變 ...
    logger.info("Extracting authoritative titles from translated content...")
    for chapter in translated_book.chapters:
        new_title = ""
        for block in chapter.content:
            if isinstance(block, HeadingBlock):
                # 在html_to_blocks中，content_source被優先填充
                new_title = block.content_source 
                break
        if new_title:
            chapter.title_target = new_title
            # logger.info(f"  - Set title for '{chapter.id}': '{new_title}'")
        elif chapter.title:
            # logger.warning(f"  - Could not find a heading in chapter '{chapter.id}'. Using original title '{chapter.title}' as fallback.")
            chapter.title_target = chapter.title # Fallback

    final_chapter_id_map = {ch.id: ch for ch in translated_book.chapters}
    _patch_toc_titles(translated_book, final_chapter_id_map, logger)
    
    logger.info("Final translated Book object created successfully.")
    return translated_book