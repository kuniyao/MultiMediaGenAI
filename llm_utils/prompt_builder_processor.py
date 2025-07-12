# llm_utils/prompt_builder_processor.py

from genai_processors import processor
from workflows.parts import TranslationRequestPart, ApiRequestPart
from .prompt_builder import PromptBuilder


class PromptBuilderProcessor(processor.Processor):
    """一個根據翻譯請求構建 API 消息的處理器。"""

    def _determine_task_type(self, part: TranslationRequestPart) -> str:
        """根據請求元數據中的 ID 判斷任務類型。"""
        task_id = part.metadata.get("llm_processing_id", "")
        if "json_subtitle_batch" in task_id:
            return "json_subtitle_batch"
        if task_id.startswith("batch::"):
            return "json_batch"
        if task_id.startswith("file::"):
            return "text_file"
        if "html_part" in task_id:
            return "html_part"
        # 可以添加一個默認或錯誤處理
        raise ValueError(f"無法從 ID '{task_id}' 確定任務類型。")

    async def call(self, stream):
        async for part in stream:
            if not isinstance(part, TranslationRequestPart):
                continue

            try:
                # 1. 確定任務類型
                task_type = self._determine_task_type(part)

                # 2. 實例化 PromptBuilder
                builder = PromptBuilder(
                    source_lang=part.source_lang,
                    target_lang=part.target_lang
                    # 在這裡可以選擇性地傳入術語表 (glossary)
                )

                # 3. 構建消息
                messages = builder.build_messages(
                    task_type=task_type,
                    task_string=part.text_to_translate
                )

                # 4. 產��包含 API 請求和原始元數據的 Part
                yield ApiRequestPart(
                    messages=messages,
                    metadata=part.metadata
                )

            except (ValueError, KeyError) as e:
                # 在實際應用中，可以產生一個 ErrorPart
                print(f"處理任務時出錯 (metadata: {part.metadata}): {e}")
