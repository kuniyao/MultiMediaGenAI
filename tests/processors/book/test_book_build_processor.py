# tests/processors/book/test_book_build_processor.py

import pytest
import asyncio

from processors.book.book_build_processor import BookBuildProcessor
from workflows.parts import TranslatedTextPart
from workflows.book.parts import TranslatedBookPart

@pytest.mark.asyncio
async def test_book_build_processor_builds_book_correctly():
    """
    測試 BookBuildProcessor 是否能成功將 TranslatedTextPart 的流組裝成一本書。
    """
    # --- 設定 ---
    processor = BookBuildProcessor()

    # 準備輸入的 Part 流
    input_parts = [
        TranslatedTextPart(
            translated_text="<p>Contenu du chapitre 1</p>",
            source_text="",
            metadata={
                "book_title": "Le Grand Livre",
                "book_author": "Auteur Anonyme",
                "chapter_id": "c1",
                "title": "Chapitre 1"
            }
        ),
        TranslatedTextPart(
            translated_text="<h2>Chapitre 2</h2>",
            source_text="",
            metadata={
                "book_title": "Le Grand Livre",
                "book_author": "Auteur Anonyme",
                "chapter_id": "c2",
                "title": "Chapitre 2"
            }
        )
    ]

    async def stream_generator():
        for part in input_parts:
            yield part

    # --- 執行 ---
    output_parts = [part async for part in processor.call(stream_generator())]

    # --- 驗證 ---
    # 1. 驗證是否只輸出了一個 Part
    assert len(output_parts) == 1
    output_part = output_parts[0]

    # 2. 驗證輸出的 Part 是正確的類型
    assert isinstance(output_part, TranslatedBookPart)

    # 3. 驗證 Part 中的內容是否符合預期
    assert output_part.title == "Le Grand Livre"
    assert output_part.author == "Auteur Anonyme"
    assert len(output_part.translated_chapters) == 2
    
    # 4. 驗證章節內容
    chapter1 = output_part.translated_chapters[0]
    assert chapter1["id"] == "c1"
    assert chapter1["translated_content"] == "<p>Contenu du chapitre 1</p>"

    chapter2 = output_part.translated_chapters[1]
    assert chapter2["id"] == "c2"
    assert chapter2["translated_content"] == "<h2>Chapitre 2</h2>"
