# tests/workflows/book/test_chapter_to_translation_request_processor.py

import pytest
import asyncio

from workflows.book.processors import ChapterToTranslationRequestProcessor
from workflows.book.parts import ChapterPart
from workflows.parts import TranslationRequestPart

@pytest.mark.asyncio
async def test_adapter_processor_converts_part_correctly():
    """
    測試 ChapterToTranslationRequestProcessor 是否能成功將 ChapterPart 轉換為 TranslationRequestPart。
    """
    # --- 設定 ---
    processor = ChapterToTranslationRequestProcessor()

    # 準備輸入的 Part
    input_metadata = {
        "book_title": "My Awesome Book",
        "source_lang": "en",
        "target_lang": "es"
    }
    input_part = ChapterPart(
        chapter_id="ch1",
        title="The Beginning",
        html_content="<p>Once upon a time...</p>",
        metadata=input_metadata
    )

    async def stream_generator():
        yield input_part

    # --- 執行 ---
    output_parts = [part async for part in processor.call(stream_generator())]

    # --- 驗證 ---
    # 1. 驗證是否只輸出了一個 Part
    assert len(output_parts) == 1
    output_part = output_parts[0]

    # 2. 驗證輸出的 Part 是正確的類型
    assert isinstance(output_part, TranslationRequestPart)

    # 3. 驗證 Part 的內容和屬性是否被正確轉換
    assert output_part.text_to_translate == "<p>Once upon a time...</p>"
    assert output_part.source_lang == "en"
    assert output_part.target_lang == "es"
    
    # 4. 驗證元數據是否被正確傳遞
    assert output_part.metadata["book_title"] == "My Awesome Book"
    assert output_part.metadata["chapter_id"] == "ch1"
