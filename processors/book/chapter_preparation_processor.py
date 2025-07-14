# processors/book/chapter_preparation_processor.py

import logging
import json
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Tuple

from genai_processors import processor
import config
from workflows.book.parts import EpubBookPart, BatchTranslationTaskPart, SplitChapterTaskPart
from format_converters.book_schema import Chapter, Book, AnyBlock, HeadingBlock
from format_converters import html_mapper

# 這個處理器的核心邏輯，是從舊的 book_processor.py 中移植並適配到 genai-processors 框架的。

# --- (移植過來的輔助函數) ---

def _serialize_blocks_to_html(blocks: List[AnyBlock], soup: BeautifulSoup) -> str:
    """將一個塊列表序列化為一個HTML字符串。"""
    body = soup.new_tag('body')
    for block in blocks:
        html_element = html_mapper.map_block_to_html(block, soup)
        if html_element:
            body.append(html_element)
    return ''.join(str(child) for child in body.children)

def _prepare_chapter_content(chapter: Chapter, logger) -> Tuple[List[AnyBlock], bool]:
    """專門處理"無頭內容"的標題注入。"""
    content_for_processing = chapter.content
    was_heading_injected = False
    
    has_heading = any(isinstance(block, HeadingBlock) for block in chapter.content)
    if not has_heading and chapter.title:
        logger.info(f"Chapter '{chapter.id}' is headless. Injecting title: '{chapter.title}'")
        temp_heading = HeadingBlock(level=1, content_source=chapter.title, id=f"temp-heading-{chapter.id}", type='heading')
        content_for_processing = [temp_heading] + chapter.content
        was_heading_injected = True
        
    return content_for_processing, was_heading_injected

# --- (主處理器類) ---

class ChapterPreparationProcessor(processor.Processor):
    """
    一個智能的預處理器，它接收一個完整的EpubBookPart，然後根據策略
    將其轉換為一系列優化過的、用於翻譯的任務Part。
    - 將過大的章節拆分為多個 SplitChapterTaskPart。
    - 將多個較小的章節打包成一個 BatchTranslationTaskPart。
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # 從config中讀取切分和打包的閾值
        self.effective_input_limit = config.OUTPUT_TOKEN_LIMIT / config.LANGUAGE_EXPANSION_FACTOR
        self.target_token_per_chunk = int(self.effective_input_limit * config.SAFETY_MARGIN)

    async def call(self, stream):
        """
        處理傳入的數據流。這個處理器會消耗掉一個 EpubBookPart，
        然後產出多個新的任務 Part。
        """
        self.logger.debug(f"Target tokens per LLM chunk calculated: {self.target_token_per_chunk}")
        
        async for part in stream:
            if not isinstance(part, EpubBookPart):
                # 如果不是我們期望的 Part，直接傳遞下去
                yield part
                continue

            book = part.book
            self.logger.info(f"Preparing translation tasks for book: '{book.metadata.title_source}'")

            current_batch_payload: List[Dict[str, Any]] = []
            current_batch_tokens = 0
            soup = BeautifulSoup('', 'html.parser')

            for chapter_index, chapter in enumerate(book.chapters):
                if not chapter.content:
                    self.logger.warning(f"Skipping chapter '{chapter.id}' as it has no content.")
                    continue
                
                # 為塊分配臨時ID，以便修復流程（如果需要）
                for block_index, block in enumerate(chapter.content):
                    block.mmg_id = f"chp{chapter_index}-blk{block_index}"

                content_to_process, was_injected = _prepare_chapter_content(chapter, self.logger)
                chapter_html = _serialize_blocks_to_html(content_to_process, soup)
                token_count = len(chapter_html) // 3 # 簡單的token估算

                # 策略1: 處理大章節
                if token_count > self.target_token_per_chunk:
                    # 在處理大章節之前，先把當前積攢的批次處理掉
                    if current_batch_payload:
                        self.logger.info(f"Finalizing batch of {len(current_batch_payload)} chapters before splitting a large one.")
                        batch_json_string = json.dumps(current_batch_payload, ensure_ascii=False)
                        yield BatchTranslationTaskPart(
                            json_string=batch_json_string,
                            chapter_count=len(current_batch_payload),
                            metadata=part.metadata
                        )
                        current_batch_payload = []
                        current_batch_tokens = 0
                    
                    # 開始切分大章節
                    self.logger.info(f"Chapter '{chapter.id}' is too large ({token_count} tokens), applying splitting strategy.")
                    for split_part in self._split_large_chapter(chapter, content_to_process, was_injected, soup, part.metadata):
                        yield split_part

                # 策略2: 處理小章節，並將其加入批次
                else:
                    if current_batch_payload and (current_batch_tokens + token_count > self.target_token_per_chunk):
                        self.logger.info(f"Finalizing batch of {len(current_batch_payload)} chapters as it reached token limit.")
                        batch_json_string = json.dumps(current_batch_payload, ensure_ascii=False)
                        yield BatchTranslationTaskPart(
                            json_string=batch_json_string,
                            chapter_count=len(current_batch_payload),
                            metadata=part.metadata
                        )
                        current_batch_payload = []
                        current_batch_tokens = 0
                    
                    self.logger.debug(f"Adding chapter '{chapter.id}' ({token_count} tokens) to current batch.")
                    chapter_payload: Dict[str, Any] = {"id": chapter.id, "html_content": chapter_html}
                    if was_injected:
                        chapter_payload["injected_heading"] = True
                    current_batch_payload.append(chapter_payload)
                    current_batch_tokens += token_count

            # 處理循環結束後最後剩餘的批次
            if current_batch_payload:
                self.logger.info(f"Finalizing the last batch of {len(current_batch_payload)} chapters.")
                batch_json_string = json.dumps(current_batch_payload, ensure_ascii=False)
                yield BatchTranslationTaskPart(
                    json_string=batch_json_string,
                    chapter_count=len(current_batch_payload),
                    metadata=part.metadata
                )
            
            # 關鍵：將原始的 EpubBookPart 也傳遞下去，供 BookBuildProcessor 使用
            self.logger.info("Finished preparing all translation tasks. Yielding original EpubBookPart for final assembly.")
            yield part

    def _split_large_chapter(self, chapter: Chapter, content_to_process: List[AnyBlock], was_injected: bool, 
                             soup: BeautifulSoup, original_metadata: Dict):
        """
        一個生成器，接收一個大章節，並產出多個 SplitChapterTaskPart。
        """
        part_number = 0
        current_split_blocks = []
        current_split_tokens = 0

        for block in content_to_process:
            block_html = _serialize_blocks_to_html([block], soup)
            block_tokens = len(block_html) // 3
            
            if current_split_tokens + block_tokens > self.target_token_per_chunk and current_split_blocks:
                chunk_html = _serialize_blocks_to_html(current_split_blocks, soup)
                yield SplitChapterTaskPart(
                    html_content=chunk_html,
                    original_chapter_id=chapter.id,
                    part_number=part_number,
                    injected_heading=(was_injected and part_number == 0),
                    metadata=original_metadata
                )
                part_number += 1
                current_split_blocks = [block]
                current_split_tokens = block_tokens
            else:
                current_split_blocks.append(block)
                current_split_tokens += block_tokens
        
        if current_split_blocks:
            chunk_html = _serialize_blocks_to_html(current_split_blocks, soup)
            yield SplitChapterTaskPart(
                html_content=chunk_html,
                original_chapter_id=chapter.id,
                part_number=part_number,
                injected_heading=(was_injected and part_number == 0),
                metadata=original_metadata
            )
