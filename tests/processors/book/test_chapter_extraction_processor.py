# tests/processors/book/test_chapter_extraction_processor.py

import pytest
import asyncio

from processors.book.chapter_extraction_processor import ChapterExtractionProcessor
from workflows.book.parts import EpubBookPart, ChapterPart

@pytest.mark.asyncio
async def test_chapter_extraction_processor_extracts_chapters():
    """
    測試 ChapterExtractionProcessor 是否能成功從 EpubBookPart 中提取章節。
    """
    # --- 設定 ---
    processor = ChapterExtractionProcessor()

    # 準備一個假的章節列表
    fake_chapters = [
        {"id": "chap1", "file_name": "c1.xhtml", "content": "<p>Chapter 1 content</p>"},
        {"id": "chap2", "file_name": "c2.xhtml", "content": "<h2>Chapter 2</h2>"},
    ]

    # 準備輸入的 Part
    input_part = EpubBookPart(
        title="Test Book",
        author="Test Author",
        chapters=fake_chapters,
        metadata={"source_file": "test.epub"}
    )

    async def stream_generator():
        yield input_part

    # --- 執行 ---
    output_parts = [part async for part in processor.call(stream_generator())]

    # --- 驗證 ---
    # 1. 驗證輸出的 Part 數量是否與章節數量相同
    assert len(output_parts) == 2

    # 2. 驗證第一個 Part
    part1 = output_parts[0]
    assert isinstance(part1, ChapterPart)
    assert part1.chapter_id == "chap1"
    assert part1.html_content == "<p>Chapter 1 content</p>"
    assert part1.metadata["book_title"] == "Test Book"
    assert part1.metadata["source_file"] == "test.epub"

    # 3. 驗證第二個 Part
    part2 = output_parts[1]
    assert isinstance(part2, ChapterPart)
    assert part2.chapter_id == "chap2"
    assert part2.html_content == "<h2>Chapter 2</h2>"
    assert part2.metadata["book_author"] == "Test Author"

@pytest.mark.asyncio
async def test_chapter_extraction_with_max_chapters_limit():
    """
    測試當設置了 max_chapters 限制時，處理器是否只提取指定數量的章節。
    """
    # --- 設定 ---
    # 限制只提取一個章節
    processor = ChapterExtractionProcessor(max_chapters=1)

    fake_chapters = [
        {"id": "chap1", "content": "Content 1"},
        {"id": "chap2", "content": "Content 2"},
    ]
    input_part = EpubBookPart(title="Limited Book", author="Limiter", chapters=fake_chapters)

    async def stream_generator():
        yield input_part

    # --- 執行 ---
    output_parts = [part async for part in processor.call(stream_generator())]

    # --- 驗證 ---
    assert len(output_parts) == 1
    assert output_parts[0].chapter_id == "chap1"
