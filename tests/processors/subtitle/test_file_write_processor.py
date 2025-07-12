# tests/processors/subtitle/test_file_write_processor.py

import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

from processors.subtitle.file_write_processor import FileWriterProcessor
from workflows.parts import TranslatedTextPart

# 使用 pytest 的 tmp_path fixture 來創建一個臨時目錄進行測試
@pytest.mark.asyncio
async def test_file_writer_processor_writes_file_successfully(tmp_path):
    """
    測試 FileWriterProcessor 是否能根據傳入的 Part 成功寫入文件。
    """
    # --- 設定 ---
    # 1. 定義輸出目錄和處理器
    output_dir = tmp_path
    processor = FileWriterProcessor(output_dir=output_dir)

    # 2. 準備輸入的 Part
    input_metadata = {
        "title": "My Test Project",
        "original_file": "/path/to/source/document.txt",
        "target_lang": "fr"
    }
    input_part = TranslatedTextPart(
        translated_text="Bonjour le monde",
        source_text="Hello World",
        metadata=input_metadata
    )

    # 3. 準備輸入流
    async def stream_generator():
        yield input_part

    # --- 執行 ---
    # 執行處理器，但我們不關心它的輸出
    async for _ in processor.call(stream_generator()):
        pass

    # --- 驗證 ---
    # 1. 構建預期的輸出路徑
    # 預期路徑: <tmp_path>/my-test-project/translations/document_fr.txt
    expected_dir = output_dir / "my-test-project" / "translations"
    expected_file = expected_dir / "document_fr.txt"

    # 2. 檢查文件是否存在
    assert expected_file.exists()

    # 3. 檢查文件內容是否正確
    assert expected_file.read_text(encoding='utf-8') == "Bonjour le monde"

@pytest.mark.asyncio
async def test_file_writer_processor_handles_other_parts(tmp_path):
    """
    測試 FileWriterProcessor 是否會忽略不相關的 Part。
    """
    # --- 設定 ---
    output_dir = tmp_path
    processor = FileWriterProcessor(output_dir=output_dir)

    # 一個不相關的 Part
    class OtherPart:
        pass
    
    input_part = OtherPart()

    async def stream_generator():
        yield input_part

    # --- 執行 ---
    output_parts = [part async for part in processor.call(stream_generator())]

    # --- 驗證 ---
    # 1. 驗證處理器是否將不相關的 Part 又重新 yield 出來
    assert len(output_parts) == 1
    assert output_parts[0] is input_part

    # 2. 驗證沒有任何文件被創建
    # list(tmp_path.iterdir()) 會列出 tmp_path 下的所有文件和目錄
    assert not any(tmp_path.iterdir())

@pytest.mark.asyncio
@patch('common_utils.output_manager.OutputManager.save_file')
async def test_file_writer_processor_handles_exception(mock_save_file, tmp_path):
    """
    測試當文件寫入失敗時，處理器是否能正常處理異常。
    """
    # --- 設定 ---
    # 1. 讓 save_file 在被調用時引發異常
    mock_save_file.side_effect = IOError("Disk full")

    # 2. 設置處理器
    output_dir = tmp_path
    processor = FileWriterProcessor(output_dir=output_dir)

    # 3. 準備輸入數據
    input_metadata = {
        "title": "Error Project",
        "original_file": "error.txt",
        "target_lang": "de"
    }
    input_part = TranslatedTextPart(
        translated_text="Hallo Welt",
        source_text="Hello World",
        metadata=input_metadata
    )

    async def stream_generator():
        yield input_part

    # --- 執行 & 驗證 ---
    # 我們預期處理器會捕捉異常並記錄日誌，但不會讓整個程序崩潰
    # 並且不會有任何 Part 被 yield 出來
    try:
        output_parts = [part async for part in processor.call(stream_generator())]
        assert len(output_parts) == 0 # 發生異常時，不應該有任何輸出
    except Exception:
        pytest.fail("Processor should not raise exceptions, but handle them gracefully.")
