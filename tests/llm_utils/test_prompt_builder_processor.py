# tests/llm_utils/test_prompt_builder_processor.py

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from llm_utils.prompt_builder_processor import PromptBuilderProcessor
from workflows.parts import TranslationRequestPart, ApiRequestPart

# 使用 pytest.mark.asyncio 來標記這是一個異步測試函式
@pytest.mark.asyncio
@patch('llm_utils.prompt_builder_processor.PromptBuilder')
async def test_process_html_part_successfully(MockPromptBuilder):
    """
    測試 PromptBuilderProcessor 是否能成功處理 HTML 類型的任務。
    """
    # --- 設定 ---
    # 模擬 PromptBuilder 的實例和其方法
    mock_builder_instance = MagicMock()
    mock_builder_instance.build_messages.return_value = [{"role": "user", "content": "Translate this HTML"}]
    MockPromptBuilder.return_value = mock_builder_instance

    processor = PromptBuilderProcessor()

    # 建立輸入數據
    input_metadata = {"llm_processing_id": "some_id::html_part::1", "custom_key": "value"}
    input_part = TranslationRequestPart(
        text_to_translate="<p>Hello</p>",
        source_lang="en",
        target_lang="zh",
        metadata=input_metadata
    )
    
    # 將輸入數據放入一個異步流中
    async def stream_generator():
        yield input_part

    # --- 執行 ---
    output_parts = [part async for part in processor.call(stream_generator())]

    # --- 驗證 ---
    # 1. 驗證 PromptBuilder 是否以正確的參數被初始化
    MockPromptBuilder.assert_called_once_with(source_lang="en", target_lang="zh")

    # 2. 驗證 build_messages 方法是否以正確的參數被呼叫
    mock_builder_instance.build_messages.assert_called_once_with(
        task_type="html_part",
        task_string="<p>Hello</p>"
    )

    # 3. 驗證輸出是否符合預期
    assert len(output_parts) == 1
    output_part = output_parts[0]
    assert isinstance(output_part, ApiRequestPart)
    assert output_part.messages == [{"role": "user", "content": "Translate this HTML"}]
    assert output_part.metadata == input_metadata

@pytest.mark.asyncio
@patch('llm_utils.prompt_builder_processor.PromptBuilder')
async def test_process_subtitle_batch_successfully(MockPromptBuilder):
    """
    測試 PromptBuilderProcessor 是否能成功處理 json_subtitle_batch 類型的任務。
    """
    # --- 設定 ---
    mock_builder_instance = MagicMock()
    mock_builder_instance.build_messages.return_value = [{"role": "user", "content": "Translate subtitles"}]
    MockPromptBuilder.return_value = mock_builder_instance

    processor = PromptBuilderProcessor()
    input_metadata = {"llm_processing_id": "json_subtitle_batch_1", "file": "test.srt"}
    input_part = TranslationRequestPart(
        text_to_translate="[...]",
        source_lang="en",
        target_lang="jp",
        metadata=input_metadata
    )
    
    async def stream_generator():
        yield input_part

    # --- 執行 ---
    output_parts = [part async for part in processor.call(stream_generator())]

    # --- 驗證 ---
    MockPromptBuilder.assert_called_once_with(source_lang="en", target_lang="jp")
    mock_builder_instance.build_messages.assert_called_once_with(
        task_type="json_subtitle_batch",
        task_string="[...]"
    )
    assert len(output_parts) == 1
    output_part = output_parts[0]
    assert isinstance(output_part, ApiRequestPart)
    assert output_part.messages == [{"role": "user", "content": "Translate subtitles"}]
    assert output_part.metadata == input_metadata

@pytest.mark.asyncio
async def test_raises_value_error_for_unknown_task_id():
    """
    測試當提供未知的 task_id 時，處理器是否會正確處理錯誤並且不產生任何輸出。
    """
    # --- 設定 ---
    processor = PromptBuilderProcessor()
    input_metadata = {"llm_processing_id": "an_unknown_task_id"}
    input_part = TranslationRequestPart(
        text_to_translate="Some text",
        source_lang="en",
        target_lang="de",
        metadata=input_metadata
    )
    
    async def stream_generator():
        yield input_part

    # --- 執行 & 驗證 ---
    # 由於 call 方法中的 try-except 會捕捉 ValueError 並打印，
    # 我們預期不會有任何 part 被 yield 出來。
    output_parts = [part async for part in processor.call(stream_generator())]
    assert len(output_parts) == 0

@pytest.mark.asyncio
async def test_ignores_non_translation_request_parts():
    """
    測試處理器是否會忽略不是 TranslationRequestPart 的物件。
    """
    # --- 設定 ---
    processor = PromptBuilderProcessor()
    
    # 一個無關的物件
    class OtherPart:
        pass

    async def stream_generator():
        yield OtherPart()

    # --- 執行 ---
    output_parts = [part async for part in processor.call(stream_generator())]

    # --- 驗證 ---
    assert len(output_parts) == 0
