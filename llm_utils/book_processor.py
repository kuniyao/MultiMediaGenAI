# llm_utils/book_processor.py (FINAL VERSION)

from __future__ import annotations
from bs4 import BeautifulSoup, Tag
from format_converters import html_mapper
from format_converters.book_schema import Chapter, Book, AnyBlock, TextItem, HeadingBlock
from typing import List, Dict, Any
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
    # 性能優化：不再需要通過API調用來計數，因此移除模型客戶端初始化
    # if logger: logger.info("Initializing model client for token counting...")
    # model = get_model_client(logger=logger)
    # if not model:
    #     if logger: logger.critical("Failed to initialize the model client. Cannot proceed. Aborting.")
    #     return []

    effective_input_limit = config.OUTPUT_TOKEN_LIMIT / config.LANGUAGE_EXPANSION_FACTOR
    target_token_per_chunk = int(effective_input_limit * config.SAFETY_MARGIN)
    if logger: logger.info(f"Target tokens per LLM chunk calculated: {target_token_per_chunk}")

    translation_tasks = []
    current_batch_chapters_payload: List[Dict[str, Any]] = []
    current_batch_tokens = 0
    soup_for_serialization = BeautifulSoup('', 'html.parser')

    for chapter in book.chapters:
        if not chapter.content:
            if logger: logger.info(f"Skipping chapter '{chapter.id}' as it has no content.")
            continue
        
        # --- 注入標題 START ---
        # 檢查是否存在標題塊
        has_heading = any(isinstance(block, HeadingBlock) for block in chapter.content)
        temp_heading_injected = False
        content_for_processing = chapter.content

        # 如果沒有標題塊，但章節對象中有從TOC繼承的標題，則注入它
        if not has_heading and chapter.title:
            if logger: logger.info(f"Chapter '{chapter.id}' is headless. Injecting title: '{chapter.title}'")
            # 我們創建一個臨時的 HeadingBlock
            temp_heading = HeadingBlock(level=1, content_source=chapter.title, id=f"temp-heading-{chapter.id}", type='heading')
            content_for_processing = [temp_heading] + chapter.content
            temp_heading_injected = True
        # --- 注入標題 END ---

        chapter_html = _serialize_blocks_to_html(content_for_processing, soup_for_serialization)
        # 性能優化：使用字符數估算Token，取代緩慢的API調用
        token_count = len(chapter_html) // 3
        # try:
        #     token_count = model.count_tokens(chapter_html).total_tokens
        # except Exception as e:
        #     if logger: logger.warning(f"Token count API failed for chapter {chapter.id}. Falling back to char estimation. Error: {e}")
        #     token_count = len(chapter_html) // 3

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
            for block in content_for_processing: # 使用更新後的 content_for_processing
                block_html = _serialize_blocks_to_html([block], soup_for_serialization)
                # 性能優化：使用字符數估算Token
                block_tokens = len(block_html) // 3
                # try:
                #     block_tokens = model.count_tokens(block_html).total_tokens
                # except:
                #     block_tokens = len(block_html) // 3
                
                if current_split_tokens + block_tokens > target_token_per_chunk and current_split_blocks:
                    chunk_html = _serialize_blocks_to_html(current_split_blocks, soup_for_serialization)
                    task_id = f"split::{chapter.id}::part_{part_number}"
                    source_data = {"type": "split_part", "original_chapter_id": chapter.id, "part_number": part_number}
                    if temp_heading_injected and part_number == 0:
                        source_data["injected_heading"] = True
                    translation_tasks.append({ "llm_processing_id": task_id, "text_to_translate": chunk_html, "source_data": source_data})
                    part_number += 1
                    current_split_blocks = [block]
                    current_split_tokens = block_tokens
                else:
                    current_split_blocks.append(block)
                    current_split_tokens += block_tokens
            
            if current_split_blocks:
                chunk_html = _serialize_blocks_to_html(current_split_blocks, soup_for_serialization)
                task_id = f"split::{chapter.id}::part_{part_number}"
                source_data = {"type": "split_part", "original_chapter_id": chapter.id, "part_number": part_number}
                if temp_heading_injected and part_number == 0:
                     source_data["injected_heading"] = True
                translation_tasks.append({ "llm_processing_id": task_id, "text_to_translate": chunk_html, "source_data": source_data})
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
            chapter_payload: Dict[str, Any] = {"id": chapter.id, "html_content": chapter_html}
            if temp_heading_injected:
                chapter_payload["injected_heading"] = True
            current_batch_chapters_payload.append(chapter_payload)
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
                    injected_heading = translated_chapter.get('injected_heading', False)

                    if chapter_id in chapter_map:
                        target_chapter = chapter_map[chapter_id]
                        if logger: logger.info(f"Applying translated content for chapter '{chapter_id}' from batch task '{task_id}'.")
                        
                        blocks = html_mapper.html_to_blocks(html_content, translated_book.image_resources, logger)
                        
                        if injected_heading:
                            if blocks and isinstance(blocks[0], HeadingBlock):
                                if logger: logger.debug(f"Extracted injected title for '{chapter_id}': '{blocks[0].content_source}'")
                                target_chapter.title_target = blocks[0].content_source
                                target_chapter.content = blocks[1:]
                            else:
                                if logger: logger.warning(f"Chapter '{chapter_id}' was marked with injected_heading, but no leading HeadingBlock found.")
                                target_chapter.content = blocks
                        else:
                            target_chapter.content = blocks
                    else:
                        if logger: logger.warning(f"From batch task {task_id}, found chapter_id '{chapter_id}' which is not in the book map.")
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
        
        full_blocks = []
        for i, part in enumerate(parts):
            part_html = re.sub(r'(<a href=\\"\\\"></a>)+', '', part['translated_text'])
            part_blocks = html_mapper.html_to_blocks(part_html, translated_book.image_resources, logger)
            
            # 檢查第一部分是否有注入的標題
            is_first_part = (i == 0)
            injected_heading = part['source_data'].get('injected_heading', False)

            if is_first_part and injected_heading:
                if part_blocks and isinstance(part_blocks[0], HeadingBlock):
                    if logger: logger.debug(f"Extracted injected title for split chapter '{chapter_id}': '{part_blocks[0].content_source}'")
                    # 直接在 chapter map 中找到對應章節並設置標題
                    if chapter_id in chapter_map:
                        chapter_map[chapter_id].title_target = part_blocks[0].content_source
                    full_blocks.extend(part_blocks[1:])
                else:
                    if logger: logger.warning(f"Split chapter '{chapter_id}' was marked with injected_heading, but no leading HeadingBlock found in part 0.")
                    full_blocks.extend(part_blocks)
            else:
                full_blocks.extend(part_blocks)

        if chapter_id in chapter_map:
            target_chapter = chapter_map[chapter_id]
            if logger: logger.info(f"Applying re-assembled content for split chapter '{chapter_id}'.")
            target_chapter.content = full_blocks
        else:
            if logger: logger.warning(f"Could not find original chapter '{chapter_id}' to apply re-assembled split parts.")

    # STAGE 4 & 5 (提取標題和修正目錄) ... 保持不變 ...
    logger.info("Extracting authoritative titles from translated content...")
    for chapter in translated_book.chapters:
        # 如果 title_target 已經通過注入的標題設置過了，就跳過
        if hasattr(chapter, 'title_target') and chapter.title_target:
            if logger: logger.debug(f"Title for '{chapter.id}' already set to '{chapter.title_target}', skipping extraction from content.")
            continue

        new_title = ""
        for block in chapter.content:
            if isinstance(block, HeadingBlock):
                # 在html_to_blocks中，content_source被優先填充
                new_title = block.content_source 
                break
        if new_title:
            chapter.title_target = new_title
        elif chapter.title and not (hasattr(chapter, 'title_target') and chapter.title_target):
            if logger: logger.warning(f"  - Could not find a heading in chapter '{chapter.id}'. Using original title '{chapter.title}' as fallback.")
            chapter.title_target = chapter.title # Fallback

    final_chapter_id_map = {ch.id: ch for ch in translated_book.chapters}
    _patch_toc_titles(translated_book, final_chapter_id_map, logger)
    
    logger.info("Final translated Book object created successfully.")
    return translated_book