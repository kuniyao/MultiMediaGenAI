# tests/llm_utils/test_translator_processor.py

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from llm_utils.translator import TranslatorProcessor
from workflows.parts import ApiRequestPart, TranslatedTextPart

# 輔助異步函式，用於模擬返回協程
async def async_return(value):
    return value

# 異步測試需要 pytest-asyncio
@pytest.mark.asyncio
async def test_translator_processor_successful_translation():
    """
    測試 TranslatorProcessor 在成功翻譯時的行為。
    """
    # --- 設定 ---
    # 1. 模擬 LLM 客戶端
    mock_llm_client = MagicMock()
    mock_llm_client.initialize = AsyncMock()
    # 修正：讓 call_api_async 返回一個協程
    mock_llm_client.call_api_async.return_value = async_return(("Translated Hello", "log_string"))

    # 2. 實例化處理器，並注入模擬的客戶端
    processor = TranslatorProcessor(client=mock_llm_client)

    # 3. 準備輸入數據流
    input_metadata = {
        "llm_processing_id": "test_id_1",
        "source_text": "Hello"
    }
    input_part = ApiRequestPart(
        messages=[{"role": "user", "content": "Translate: Hello"}],
        metadata=input_metadata
    )
    
    async def stream_generator():
        yield input_part

    # --- 執行 ---
    # 執行處理器的 call 方法
    output_parts = [part async for part in processor.call(stream_generator())]

    # --- 驗證 ---
    # 1. 驗證客戶端的 initialize 方法是否被調用了一次
    mock_llm_client.initialize.assert_called_once()

    # 2. 驗證 call_api_async 方法是否以正確的參數被調用
    mock_llm_client.call_api_async.assert_called_once_with(
        messages=[{"role": "user", "content": "Translate: Hello"}],
        task_id="test_id_1"
    )

    # 3. 驗證輸出的 Part 是否符合預期
    assert len(output_parts) == 1
    output_part = output_parts[0]
    assert isinstance(output_part, TranslatedTextPart)
    assert output_part.translated_text == "Translated Hello"
    assert output_part.source_text == "Hello"
    assert output_part.metadata == input_metadata

@pytest.mark.asyncio
async def test_translator_processor_api_failure():
    """
    測試當底層 API 調用失敗時，TranslatorProcessor 的行為。
    """
    # --- 設定 ---
    # 1. 模擬一個會引發異常的 LLM 客戶端
    mock_llm_client = MagicMock()
    mock_llm_client.initialize = AsyncMock()
    # 模擬 call_api_async 在被調用時引發一個異常
    mock_llm_client.call_api_async.side_effect = Exception("API Error")

    # 2. 實例化處理器
    processor = TranslatorProcessor(client=mock_llm_client)

    # 3. 準備輸入數據
    input_metadata = {
        "llm_processing_id": "test_id_2",
        "source_text": "World"
    }
    input_part = ApiRequestPart(
        messages=[{"role": "user", "content": "Translate: World"}],
        metadata=input_metadata
    )
    
    async def stream_generator():
        yield input_part

    # --- 執行 ---
    output_parts = [part async for part in processor.call(stream_generator())]

    # --- 驗證 ---
    # 1. 驗證客戶端的方法仍然被調用
    mock_llm_client.initialize.assert_called_once()
    mock_llm_client.call_api_async.assert_called_once()

    # 2. 驗證輸出 Part 反映了失敗狀態
    assert len(output_parts) == 1
    output_part = output_parts[0]
    assert isinstance(output_part, TranslatedTextPart)
    # 檢查翻譯文本是否包含失敗信息
    assert "[TRANSLATION_FAILED]" in output_part.translated_text
    assert "API Error" in output_part.translated_text
    assert output_part.source_text == "World"
    assert output_part.metadata == input_metadata

@pytest.mark.asyncio
async def test_translator_processor_initialization_failure():
    """
    測試當客戶端初始化失敗時，處理器的行為。
    """
    # --- 設定 ---
    # 1. 模擬一個在初始化時就會失敗的客戶端
    mock_llm_client = MagicMock()
    mock_llm_client.initialize = AsyncMock(side_effect=Exception("Initialization Failed"))

    # 2. 實例化處理器
    processor = TranslatorProcessor(client=mock_llm_client)

    # 3. 準備輸入數據流
    async def stream_generator():
        yield ApiRequestPart(messages=[], metadata={})

    # --- 執行 & 驗證 ---
    # 由於初始化失敗會直接引發異常，我們預期 `call` 方法會中斷並傳播這個異常
    with pytest.raises(Exception, match="Initialization Failed"):
        _ = [part async for part in processor.call(stream_generator())]

    # 驗證 initialize 被嘗試調用
    mock_llm_client.initialize.assert_called_once()
    # 驗證 call_api_async 從未被調用
    mock_llm_client.call_api_async.assert_not_called()
