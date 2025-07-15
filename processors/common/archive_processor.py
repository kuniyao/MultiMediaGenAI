# processors/common/archive_processor.py

import logging
import json
from pathlib import Path
from typing import AsyncGenerator

from genai_processors.processor import Processor
from genai_processors.content_api import ProcessorPart
from common_utils.output_manager import OutputManager
from llm_utils.translator import TranslatorProcessor

class ArchiveProcessor(Processor):
    """
    一个通用的归档处理器。
    - 为任务创建结构化的输出目录。
    - 将该目录路径注入到 Part 的元数据中，供下游使用。
    - 通过依赖注入，收集并写入通用的 LLM 交互日志。
    """

    def __init__(self, translator: TranslatorProcessor, output_dir: str = "GlobalWorkflowOutputs"):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.translator = translator
        self.output_manager = OutputManager(output_dir, self.logger)
        self._is_archived = False # 确保只归档一次

    def _archive_outputs(self, part: ProcessorPart) -> Path:
        """
        执行一次性的归档任务：创建目录并写入 .jsonl 文件。
        返回创建好的任务目录路径。
        """
        # 从 Part 元数据中提取任务名
        # 我们假设上游 Part 的元数据中总会有一个 'original_file' 键
        original_filepath = Path(part.metadata.get("original_file", "untitled_task"))
        workflow_dirname = original_filepath.stem
        
        # 1. 创建任务专属的输出目录
        workflow_output_dir = self.output_manager.base_output_dir / workflow_dirname
        self.logger.info(f"Preparing archive directory at: {workflow_output_dir}")
        workflow_output_dir.mkdir(parents=True, exist_ok=True)

        # 2. 写入LLM响应日志
        self.logger.info("Writing LLM responses to llm_responses.jsonl...")
        llm_output_path = self.output_manager.get_workflow_output_path(workflow_dirname, "llm_responses.jsonl")
        try:
            with open(llm_output_path, 'w', encoding='utf-8') as f:
                # 从注入的 TranslatorProcessor 实例中获取缓存的响应
                for resp_part in self.translator.llm_responses:
                    # 我们假设 resp_part 是一个有 .metadata 和 .text 属性的对象
                    data_to_write = {
                        "metadata": resp_part.metadata,
                        "translated_text": resp_part.translated_text, # 使用 .translated_text
                        "source_text": resp_part.source_text,
                    }
                    f.write(json.dumps(data_to_write, ensure_ascii=False) + '\n')
            self.logger.info(f"Successfully saved LLM responses to {llm_output_path}")
        except Exception as e:
            self.logger.error(f"Failed to write LLM responses to {llm_output_path}: {e}")
        
        return workflow_output_dir

    async def call(self, stream: AsyncGenerator[ProcessorPart, None]) -> AsyncGenerator[ProcessorPart, None]:
        """
        处理输入流，执行归档操作，并将增强后的 Part 传递给下游。
        """
        async for part in stream:
            # 这个处理器只在第一次接收到 Part 时执行一次归档操作
            if not self._is_archived:
                workflow_output_dir = self._archive_outputs(part)
                # 关键：将创建好的目录路径，添加到 Part 的元数据中
                part.metadata["output_dir"] = str(workflow_output_dir)
                self.logger.debug(f"Injected 'output_dir' into Part metadata: {workflow_output_dir}")
                self._is_archived = True

            # 将（可能被增强了元数据的）Part 传递给下游
            yield part