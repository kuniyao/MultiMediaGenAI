# tests/processors/book/test_epub_parsing_processor.py

import pytest
import asyncio
from pathlib import Path
from ebooklib import epub

from processors.book.epub_parsing_processor import EpubParsingProcessor
from workflows.parts import TranslationRequestPart
from workflows.book.parts import EpubBookPart

# 輔助函式，用於創建一個假的 EPUB 文件
def create_fake_epub(path: Path, title: str, author: str, chapter_content: str):
    book = epub.EpubBook()
    book.set_identifier('id123456')
    book.set_title(title)
    book.set_language('en')
    book.add_author(author)

    # 創建一個章節
    c1 = epub.EpubHtml(title='Intro', file_name='chap_01.xhtml', lang='en')
    c1.content = chapter_content

    book.add_item(c1)
    book.toc = (epub.Link('chap_01.xhtml', 'Introduction', 'intro'),)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # 定義書的骨架
    book.spine = ['nav', c1]

    # 寫入文件
    epub.write_epub(path, book, {})

@pytest.fixture
def fake_epub_path(tmp_path):
    """一個 pytest fixture，用於創建一個假的 EPUB 文件並返回其路徑。"""
    epub_path = tmp_path / "fake_book.epub"
    create_fake_epub(
        path=epub_path,
        title="My Fake Book",
        author="Dr. Seuss",
        chapter_content="<h1>Chapter 1</h1><p>This is a test.</p>"
    )
    return epub_path

@pytest.mark.asyncio
async def test_epub_parsing_processor_successfully_parses_epub(fake_epub_path):
    """
    測試 EpubParsingProcessor 是否能成功剖析一個 EPUB 文件。
    """
    # --- 設定 ---
    processor = EpubParsingProcessor()
    
    # 準備輸入 Part
    input_part = TranslationRequestPart(
        text_to_translate=str(fake_epub_path),
        source_lang="en",
        target_lang="fr",
        metadata={"original_file": str(fake_epub_path)}
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
    assert isinstance(output_part, EpubBookPart)

    # 3. 驗證 Part 中的內容是否符合預期
    assert output_part.title == "My Fake Book"
    assert output_part.author == "Dr. Seuss"
    assert len(output_part.chapters) == 1
    
    # 4. 驗證章節內容
    chapter = output_part.chapters[0]
    assert "<h1>Chapter 1</h1>" in chapter["content"]
    assert "<p>This is a test.</p>" in chapter["content"]
    
    # 5. 驗證元數據是否被正確傳遞
    assert output_part.metadata["original_file"] == str(fake_epub_path)
