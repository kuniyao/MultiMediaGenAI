# tests/processors/book/test_epub_writing_processor.py

import pytest
import asyncio
from pathlib import Path
from ebooklib import epub

from processors.book.epub_writing_processor import EpubWritingProcessor
from workflows.book.parts import TranslatedBookPart

@pytest.mark.asyncio
async def test_epub_writing_processor_writes_epub_correctly(tmp_path):
    """
    測試 EpubWritingProcessor 是否能成功將 TranslatedBookPart 寫入為 EPUB 文件。
    """
    # --- 設定 ---
    processor = EpubWritingProcessor()

    # 準備輸入的 Part
    translated_chapters = [
        {"id": "c1", "title": "Chapitre Un", "translated_content": "<h1>Chapitre 1</h1><p>Contenu français.</p>"},
        {"id": "c2", "title": "Chapitre Deux", "translated_content": "<h2>Chapitre 2</h2><p>Plus de contenu.</p>"}
    ]
    
    input_part = TranslatedBookPart(
        title="Livre Traduit",
        author="Auteur",
        translated_chapters=translated_chapters,
        metadata={
            "output_dir": str(tmp_path),
            "original_file": "original.epub",
            "target_lang": "fr"
        }
    )

    async def stream_generator():
        yield input_part

    # --- 執行 ---
    # 我們不關心它的輸出，只關心副作用（文件寫入）
    async for _ in processor.call(stream_generator()):
        pass

    # --- 驗證 ---
    # 1. 構建預期的輸出文件路徑
    expected_file = tmp_path / "epub_translated" / "original_fr.epub"

    # 2. 驗證文件是否存在
    assert expected_file.exists()

    # 3. 讀取並驗證 EPUB 文件的內容
    read_book = epub.read_epub(expected_file)
    
    # 驗證元數據
    assert read_book.get_metadata('DC', 'title')[0][0] == "Livre Traduit"
    assert read_book.get_metadata('DC', 'creator')[0][0] == "Auteur"
    
    # 驗證章節數量
    items = list(read_book.get_items_of_type(9)) # 9 for XHTML
    # 預期有 2 個章節 + 1 個導航文件
    assert len(items) == 3 
    
    # 驗證章節內容 (抽樣檢查)
    chapter_1_content = items[1].get_content().decode('utf-8')
    assert "<h1>Chapitre 1</h1><p>Contenu français.</p>" in chapter_1_content
