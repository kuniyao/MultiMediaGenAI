# llm_utils/book_processor.py (FINAL VERSION)

from __future__ import annotations
from bs4 import BeautifulSoup, Tag
from format_converters import html_mapper
from format_converters.book_schema import Chapter, Book, AnyBlock, TextItem, HeadingBlock, ParagraphBlock, ImageBlock, ListBlock
from typing import List, Dict, Any, Tuple, Optional
import config
import pathlib
import re
import copy
import json

# --- (已有輔助函數) ---
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

# --- (extract_translatable_chapters 的新輔助函數) ---

def _prepare_chapter_content(chapter: Chapter, logger) -> Tuple[List[AnyBlock], bool]:
    """
    專門處理"無頭內容"的標題注入。
    返回一個元組，包含"用於處理的內容塊列表"和一個布林值"是否注入了標題"。
    """
    content_for_processing = chapter.content
    was_heading_injected = False
    
    has_heading = any(isinstance(block, HeadingBlock) for block in chapter.content)
    if not has_heading and chapter.title:
        if logger: logger.info(f"Chapter '{chapter.id}' is headless. Injecting title: '{chapter.title}'")
        temp_heading = HeadingBlock(level=1, content_source=chapter.title, id=f"temp-heading-{chapter.id}", type='heading')
        content_for_processing = [temp_heading] + chapter.content
        was_heading_injected = True
        
    return content_for_processing, was_heading_injected

def _finalize_batch(batch_payload: List[Dict], translation_tasks: List[Dict], logger):
    """將當前的批次（batch）打包成一個任務，並添加到總任務列表中。"""
    if not batch_payload:
        return
        
    if logger: logger.info(f"Finalizing batch of {len(batch_payload)} chapters.")
    batch_task_id = f"batch::{batch_payload[0]['id']}::to::{batch_payload[-1]['id']}"
    batch_json_string = json.dumps(batch_payload, ensure_ascii=False)
    translation_tasks.append({
        "llm_processing_id": batch_task_id,
        "text_to_translate": batch_json_string,
        "source_data": {"type": "json_batch", "chapter_count": len(batch_payload)}
    })

def _split_large_chapter(chapter: Chapter, content_to_process: List[AnyBlock], was_injected: bool, 
                         translation_tasks: List[Dict], soup: BeautifulSoup, target_token_per_chunk: int, logger):
    """
    接收一個被判斷為"過大"的章節，將其內容拆分成多個 split_part 任務，
    並直接添加到總任務列表中。
    """
    if logger: logger.info(f"Chapter '{chapter.id}' is too large, applying splitting strategy.")
    part_number = 0
    current_split_blocks = []
    current_split_tokens = 0

    for block in content_to_process:
        block_html = _serialize_blocks_to_html([block], soup)
        block_tokens = len(block_html) // 3
        
        if current_split_tokens + block_tokens > target_token_per_chunk and current_split_blocks:
            chunk_html = _serialize_blocks_to_html(current_split_blocks, soup)
            task_id = f"split::{chapter.id}::part_{part_number}"
            source_data = {"type": "split_part", "original_chapter_id": chapter.id, "part_number": part_number}
            if was_injected and part_number == 0:
                source_data["injected_heading"] = True
            translation_tasks.append({ "llm_processing_id": task_id, "text_to_translate": chunk_html, "source_data": source_data})
            part_number += 1
            current_split_blocks = [block]
            current_split_tokens = block_tokens
        else:
            current_split_blocks.append(block)
            current_split_tokens += block_tokens
    
    if current_split_blocks:
        chunk_html = _serialize_blocks_to_html(current_split_blocks, soup)
        task_id = f"split::{chapter.id}::part_{part_number}"
        source_data = {"type": "split_part", "original_chapter_id": chapter.id, "part_number": part_number}
        if was_injected and part_number == 0:
             source_data["injected_heading"] = True
        translation_tasks.append({ "llm_processing_id": task_id, "text_to_translate": chunk_html, "source_data": source_data})

# --- (重構後的 extract_translatable_chapters) ---
def extract_translatable_chapters(book: Book, logger=None) -> list:
    """
    將 Book 物件轉換為翻譯任務列表。
    - 為無頭章節注入標題。
    - 將過大的章節拆分為多個部分。
    - 將較小的章節批處理在一起。
    """
    effective_input_limit = config.OUTPUT_TOKEN_LIMIT / config.LANGUAGE_EXPANSION_FACTOR
    target_token_per_chunk = int(effective_input_limit * config.SAFETY_MARGIN)
    if logger: logger.info(f"Target tokens per LLM chunk calculated: {target_token_per_chunk}")

    translation_tasks = []
    current_batch_payload: List[Dict[str, Any]] = []
    current_batch_tokens = 0
    soup = BeautifulSoup('', 'html.parser')

    for chapter_index, chapter in enumerate(book.chapters):
        if not chapter.content:
            if logger: logger.info(f"Skipping chapter '{chapter.id}' as it has no content.")
            continue
        
        for block_index, block in enumerate(chapter.content):
                    block.mmg_id = f"chp{chapter_index}-blk{block_index}"

        content_to_process, was_injected = _prepare_chapter_content(chapter, logger)
        chapter_html = _serialize_blocks_to_html(content_to_process, soup)
        token_count = len(chapter_html) // 3

        if token_count > target_token_per_chunk:
            # 1. 如果遇到大章節，先將當前批次最終化
            _finalize_batch(current_batch_payload, translation_tasks, logger)
            current_batch_payload = []
            current_batch_tokens = 0
            
            # 2. 專門處理大章節
            _split_large_chapter(chapter, content_to_process, was_injected, translation_tasks, soup, target_token_per_chunk, logger)
        else:
            # 3. 處理小章節和批次管理
            if current_batch_payload and (current_batch_tokens + token_count > target_token_per_chunk):
                _finalize_batch(current_batch_payload, translation_tasks, logger)
                current_batch_payload = []
                current_batch_tokens = 0
            
            if logger: logger.info(f"Adding chapter '{chapter.id}' ({token_count} tokens) to current batch.")
            chapter_payload: Dict[str, Any] = {"id": chapter.id, "html_content": chapter_html}
            if was_injected:
                chapter_payload["injected_heading"] = True
            current_batch_payload.append(chapter_payload)
            current_batch_tokens += token_count

    # 處理最後剩餘的批次
    _finalize_batch(current_batch_payload, translation_tasks, logger)
    
    if logger: logger.info(f"Extracted {len(book.chapters)} chapters into {len(translation_tasks)} translation tasks.")
    return translation_tasks

# --- (TOC 修正輔助函數，無需修改) ---
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


# --- (apply_translations_to_book 的新輔助函數) ---

def _extract_title_from_injected_heading(blocks: List[AnyBlock], was_injected: bool, logger) -> Tuple[str | None, List[AnyBlock]]:
    """
    如果標題被注入，則從內容塊列表中提取標題並返回剩餘的塊。
    返回 (提取的標題, 剩餘的內容塊)。
    """
    if was_injected and blocks and isinstance(blocks[0], HeadingBlock):
        title = blocks[0].content_source
        if logger: logger.debug(f"Extracted injected title: '{title}'")
        return title, blocks[1:]
    
    if was_injected:
         if logger: logger.warning(f"Content was marked with injected_heading, but no leading HeadingBlock found.")

    return None, blocks

def _apply_batch_result(result: Dict, chapter_map: Dict[str, Chapter], image_resources: Dict, logger):
    """處理一個完整的 json_batch 類型的翻譯結果，並增加對非標準JSON響應的穩健解析。"""
    task_id = result["llm_processing_id"]
    translated_text = result["translated_text"]
    json_content_to_parse = None

    # 策略一：使用正則表達式尋找被Markdown包裹的JSON代碼塊
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', translated_text, re.DOTALL)
    if match:
        logger.debug(f"Found JSON content wrapped in markdown for task {task_id}.")
        json_content_to_parse = match.group(1).strip()
    else:
        # 策略二：如果沒有找到代碼塊，嘗試從文本中找到第一個有效JSON對象/數組的邊界
        start_brace = translated_text.find('{')
        start_bracket = translated_text.find('[')
        
        # 找到第一個 JSON 開始符號
        if start_brace == -1:
            start_pos = start_bracket
        elif start_bracket == -1:
            start_pos = start_brace
        else:
            start_pos = min(start_brace, start_bracket)
            
        if start_pos != -1:
            logger.debug(f"No markdown block found. Assuming JSON starts at position {start_pos} for task {task_id}.")
            json_content_to_parse = translated_text[start_pos:]
        else:
            # Fallback to the original text if no JSON structure is discernible
            json_content_to_parse = translated_text

    try:
        if not json_content_to_parse:
            raise json.JSONDecodeError("Content for JSON parsing is empty.", "", 0)

        # 【數據清洗】
        cleaned_json_text = re.sub(r'(<a href=\\"\\\"></a>)+', '', json_content_to_parse)
        
        translated_chapters = json.loads(cleaned_json_text)

        for translated_chapter in translated_chapters:
            chapter_id = translated_chapter.get('id')
            if not chapter_id:
                logger.warning("Found a chapter object in batch without an 'id'. Skipping.")
                continue

            if chapter_id not in chapter_map:
                logger.warning(f"From batch task {task_id}, found chapter_id '{chapter_id}' which is not in the book map.")
                continue

            target_chapter = chapter_map[chapter_id]
            logger.info(f"Applying translated content for chapter '{chapter_id}' from batch task '{task_id}'.")
            
            html_content = translated_chapter.get('html_content', '')
            injected_heading = translated_chapter.get('injected_heading', False)
            blocks = html_mapper.html_to_blocks(html_content, image_resources, logger)
            
            title, remaining_blocks = _extract_title_from_injected_heading(blocks, injected_heading, logger)
            if title:
                target_chapter.title_target = title
            target_chapter.content = remaining_blocks

    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON from batch task {task_id}. Error: {e}. Skipping this batch.")
        # 打印出用於調試的原始文本和嘗試解析的內容
        logger.debug(f"--- START RAW RESPONSE for {task_id} ---\n{translated_text}\n--- END RAW RESPONSE ---")
        if json_content_to_parse:
            logger.debug(f"--- START PARSED CONTENT for {task_id} ---\n{json_content_to_parse}\n--- END PARSED CONTENT ---")

    except Exception as e:
        logger.error(f"An unexpected error occurred while processing batch task {task_id}: {e}", exc_info=True)

def _reassemble_and_apply_split_results(chapter_id: str, parts: List[Dict], chapter_map: Dict[str, Chapter], image_resources: Dict, logger):
    """將一個章節的所有拆分翻譯結果（parts）重組，並應用回對應的章節。"""
    if chapter_id not in chapter_map:
        logger.warning(f"Could not find original chapter '{chapter_id}' to apply re-assembled split parts.")
        return

    logger.info(f"Re-assembling {len(parts)} split parts for chapter '{chapter_id}'...")
    parts.sort(key=lambda p: p['source_data']['part_number'])
    
    full_blocks = []
    for i, part in enumerate(parts):
        part_html = re.sub(r'(<a href=\\"\\\"></a>)+', '', part['translated_text'])
        part_blocks = html_mapper.html_to_blocks(part_html, image_resources, logger)
        
        is_first_part = (i == 0)
        injected_heading = part['source_data'].get('injected_heading', False)

        if is_first_part and injected_heading:
            title, remaining_blocks = _extract_title_from_injected_heading(part_blocks, injected_heading, logger)
            if title:
                chapter_map[chapter_id].title_target = title
            full_blocks.extend(remaining_blocks)
        else:
            full_blocks.extend(part_blocks)

    target_chapter = chapter_map[chapter_id]
    logger.info(f"Applying re-assembled content for split chapter '{chapter_id}'.")
    target_chapter.content = full_blocks

def _apply_fix_batch_result(result: Dict, translated_book: Book, image_resources: Dict, logger):
    """
    处理一个 'fix_batch' 类型的修复结果，将其中的内容精确地应用回 translated_book 中。
    """
    task_id = result["llm_processing_id"]
    logger.info(f"Applying fix_batch patch from task '{task_id}'...")

    # 1. 解析修复后的HTML，得到修复后的 Block 对象列表
    repaired_html = result["translated_text"]
    repaired_blocks = html_mapper.html_to_blocks(repaired_html, image_resources, logger)

    if not repaired_blocks:
        logger.warning(f"Could not parse any blocks from the fix_batch result of task '{task_id}'. Skipping patch.")
        return

    # 2. 为了高效查找，创建一个 mmg_id -> 修复后Block 的映射
    repaired_block_map = {block.mmg_id: block for block in repaired_blocks if block.mmg_id}

    # 3. 遍历原始的 translated_book，用修复后的 Block 替换掉旧的 Block
    # 这是一个比较耗费资源的操作，但能确保替换的准确性
    for chapter in translated_book.chapters:
        new_content_list = []
        replaced_in_chapter = False
        for i, original_block in enumerate(chapter.content):
            # 检查当前块的 mmg_id 是否在我们的修复映射中
            if original_block.mmg_id and original_block.mmg_id in repaired_block_map:
                repaired_block = repaired_block_map[original_block.mmg_id]
                new_content_list.append(repaired_block) # 用修复后的新块替换
                logger.info(f"  -> Patched block {original_block.mmg_id} in chapter '{chapter.id}'.")
                replaced_in_chapter = True
            else:
                new_content_list.append(original_block) # 保留原始块
        
        # 如果本章有内容被替换，则更新章节的内容列表
        if replaced_in_chapter:
            chapter.content = new_content_list

def _extract_final_titles(translated_book: Book, logger):
    """遍歷所有章節，從內容中提取最終標題。"""
    logger.info("Extracting authoritative titles from translated content...")
    for chapter in translated_book.chapters:
        if hasattr(chapter, 'title_target') and chapter.title_target:
            if logger: logger.debug(f"Title for '{chapter.id}' already set to '{chapter.title_target}', skipping extraction from content.")
            continue

        new_title = ""
        for block in chapter.content:
            if isinstance(block, HeadingBlock):
                new_title = block.content_source 
                break
        
        if new_title:
            chapter.title_target = new_title
        elif chapter.title:
            if logger: logger.warning(f"Could not find a heading in chapter '{chapter.id}'. Using original title '{chapter.title}' as fallback.")
            chapter.title_target = chapter.title

# --- (重構後的 apply_translations_to_book) ---
def apply_translations_to_book(original_book: Book, translated_results: list[dict], logger) -> Book:
    """
    將翻譯結果應用回Book對象，重建完整的翻譯書籍。
    - 分發處理批處理和拆分任務。
    - 重組被拆分的章節。
    - 進行全局的標題提取和目錄修正。
    """
    if logger: logger.info("Applying all translations to create the final Book object...")
    
    translated_book = copy.deepcopy(original_book)
    chapter_map = {ch.id: ch for ch in translated_book.chapters}
    grouped_split_parts: Dict[str, List[Dict]] = {} 

    # STAGE 1: 遍歷結果，分發處理或分組
    for result in translated_results:
        if "[TRANSLATION_FAILED]" in result["translated_text"]:
            logger.warning(f"Translation failed for task {result['llm_processing_id']}. Skipping application.")
            continue

        task_type = result["source_data"].get("type")
        if task_type == 'json_batch':
            _apply_batch_result(result, chapter_map, translated_book.image_resources, logger)
        elif task_type == 'split_part':
            original_chapter_id = result['source_data']['original_chapter_id']
            if original_chapter_id not in grouped_split_parts:
                grouped_split_parts[original_chapter_id] = []
            grouped_split_parts[original_chapter_id].append(result)
        elif task_type == 'fix_batch':
            _apply_fix_batch_result(result, translated_book, translated_book.image_resources, logger)
        else:
            logger.warning(f"Unknown task type '{task_type}' in result for task ID {result['llm_processing_id']}.")

    # STAGE 2: 重組並應用被拆分的大章節
    for chapter_id, parts in grouped_split_parts.items():
        _reassemble_and_apply_split_results(chapter_id, parts, chapter_map, translated_book.image_resources, logger)

    # STAGE 3: 後處理 - 標題提取和目錄修正
    _extract_final_titles(translated_book, logger)
    final_chapter_id_map = {ch.id: ch for ch in translated_book.chapters}
    _patch_toc_titles(translated_book, final_chapter_id_map, logger)
    
    logger.info("Final translated Book object created successfully.")
    return translated_book

# ==============================================================================
#  【新增】STEP 2: VALIDATION AND REPAIR FUNCTIONS
# ==============================================================================

def _get_block_by_mmg_id(book: Book, mmg_id: str) -> Optional[AnyBlock]:
    """一个辅助函数，根据 mmg_id 在 Book 对象中快速查找一个块。"""
    if not mmg_id:
        return None
    for chapter in book.chapters:
        for block in chapter.content:
            if block.mmg_id == mmg_id:
                return block
    return None

def _get_source_text_from_block(block: AnyBlock) -> str:
    """从一个块对象中提取其最主要的源文纯文本。"""
    if isinstance(block, (HeadingBlock, ParagraphBlock, ImageBlock)):
        return block.content_source
    elif isinstance(block, ListBlock):
        # 修正：直接从列表项的 content 中提取文本，而不是尝试将其序列化为块。
        # item.content 对于 ListBlock 来说是 RichContentItem 的列表，可以直接字符串化。
        return " ".join(
            str(item.content) for item in block.items_source
        )
    # 可以根据需要为其他块类型添加更多逻辑
    return ""

def validate_and_extract_fixes(
    original_book: Book,
    translated_results: list[dict],
    image_resources: dict,
    logger
) -> list[dict]:
    """
    Validates the translated book against the original to find blocks that were missed
    or failed during translation. Returns a list of new 'fix' tasks.
    """
    logger.info("Starting validation and fix extraction...")
    
    # 构建一个从 mmg_id 到原始块文本的映射
    source_map = {}
    for chapter in original_book.chapters:
        for block in chapter.content:
            if hasattr(block, 'mmg_id'):
                source_map[block.mmg_id] = _get_source_text_from_block(block)

    # 在翻译结果中找到所有被标记为失败的块
    failed_block_ids = set()
    for result in translated_results:
        text = result.get("translated_text", "")
        # 寻找被标记为失败的特定 ID
        matches = re.findall(r"\[TRANSLATION_FAILED: (chp\d+-blk\d+)\]", text)
        failed_block_ids.update(matches)

    fix_payloads = []
    for mmg_id in failed_block_ids:
        if mmg_id in source_map:
            source_html = source_map[mmg_id]
            # 直接创建修复任务
            fix_payloads.append({
                "llm_processing_id": f"fix::{mmg_id}",
                "text_to_translate": source_html,
                "source_data": {
                    "type": "fix_batch",
                    "original_mmg_id": mmg_id,
                }
            })

    if fix_payloads:
        logger.warning(f"Found {len(fix_payloads)} blocks needing repair. Creating fix tasks.")
    else:
        logger.info("Validation complete. No blocks require fixing.")
        
    return fix_payloads