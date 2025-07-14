# processors/book/book_build_processor.py

import logging
from copy import deepcopy
from typing import Dict, List
from genai_processors import processor
from workflows.book.parts import TranslatedChapterPart, TranslatedBookPart, EpubBookPart
from format_converters.book_schema import Book, Chapter, HeadingBlock

class BookBuildProcessor(processor.Processor):
    """
    一個接收多個 TranslatedChapterPart 和一個 EpubBookPart，
    將它們智能地重組、拼接成一本完整的書，
    並在流結束時輸出一個 TranslatedBookPart 的處理器。
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def call(self, stream):
        """
        處理傳入的數據流，收集所有數據，並在流結束時執行組裝。
        """
        original_book_part: EpubBookPart | None = None
        
        # 用於存儲從批處理任務中直接獲得的、完整的翻譯章節
        complete_translated_chapters: Dict[str, Chapter] = {}
        # 用於收集一個長章節被切分後的所有翻譯部分
        split_chapter_parts: Dict[str, List[TranslatedChapterPart]] = {}

        async for part in stream:
            if isinstance(part, EpubBookPart):
                self.logger.info("BookBuildProcessor: Captured the original book structure.")
                original_book_part = part
                continue

            if not isinstance(part, TranslatedChapterPart):
                self.logger.warning(f"BookBuildProcessor received an unexpected part type: {type(part)}")
                continue
            
            # 根據元數據判斷這個Part是來自批處理還是切分
            source_metadata = part.metadata
            chapter_id = part.translated_chapter.id
            
            # 如果 part_number 存在，說明它是一個被切分的塊
            if "part_number" in source_metadata:
                if chapter_id not in split_chapter_parts:
                    split_chapter_parts[chapter_id] = []
                split_chapter_parts[chapter_id].append(part)
            # 否則，它是一個來自批處理的、完整的章節
            else:
                complete_translated_chapters[chapter_id] = part.translated_chapter

        # --- 流結束，開始組裝 ---
        if not original_book_part:
            self.logger.error("BookBuildProcessor did not receive the original book structure. Cannot build final book.")
            return
        
        original_book = deepcopy(original_book_part.book)
        unzip_dir = original_book_part.unzip_dir

        self.logger.info("All parts received. Assembling final translated book...")
        
        # 1. 重組所有被切分的長章節
        for chapter_id, parts in split_chapter_parts.items():
            self.logger.debug(f"Re-assembling {len(parts)} split parts for chapter '{chapter_id}'...")
            # 按 part_number 排序，確保順序正確
            parts.sort(key=lambda p: p.metadata.get("part_number", 0))
            
            full_content = []
            for p in parts:
                full_content.extend(p.translated_chapter.content)
            
            # 創建一個新的、完整的章節對象
            reassembled_chapter = Chapter(id=chapter_id, content=full_content)
            complete_translated_chapters[chapter_id] = reassembled_chapter

        # 2. 用翻譯好的章節內容，更新原始書籍結構
        for i, original_chapter in enumerate(original_book.chapters):
            if original_chapter.id in complete_translated_chapters:
                translated_version = complete_translated_chapters[original_chapter.id]
                # 將翻譯好的內容和ID，賦值給原始章節的副本
                original_chapter.content = translated_version.content
                # 從翻譯好的內容中提取標題
                found_title = False
                for block in original_chapter.content:
                    if isinstance(block, HeadingBlock):
                        original_chapter.title_target = block.content_source
                        found_title = True
                        break
                if not found_title:
                    original_chapter.title_target = original_chapter.title
                
                self.logger.debug(f"Applied translated content for chapter '{original_chapter.id}'.")
            else:
                self.logger.warning(f"Chapter '{original_chapter.id}' not found in translated parts. Keeping original.")
                # 如果沒有翻譯版本，則將原文作爲“翻譯”結果
                original_chapter.title_target = original_chapter.title

        # 3. 產出最終的、完整的 TranslatedBookPart
        final_metadata = original_book_part.metadata.copy()
        final_metadata["title"] = original_book.metadata.title_source + " (Translated)"
        
        yield TranslatedBookPart(
            book=original_book,
            unzip_dir=unzip_dir,
            metadata=final_metadata
        )
        self.logger.info("Successfully built and yielded the final TranslatedBookPart.")
        
        # 4. 【关键修复】将原始的 EpubBookPart 也传递下去
        yield original_book_part