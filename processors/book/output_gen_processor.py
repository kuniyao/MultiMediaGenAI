import logging
import json
from pathlib import Path
from typing import AsyncGenerator, List, Optional, Dict, Any

from genai_processors.processor import Processor
from genai_processors.content_api import ProcessorPart

from common_utils.output_manager import OutputManager
from workflows.book.parts import EpubBookPart, TranslatedBookPart
from workflows.parts import TranslatedTextPart
from llm_utils.translator import TranslatorProcessor
from .artifact_writers import BaseArtifactWriter


class OutputGenerationProcessor(Processor):
    """
    一个通用的输出生成处理器。
    - 使用OutputManager创建结构化的输出目录。
    - 使用注入的ArtifactWriter策略来写入最终产物（如EPUB, SRT）。
    - 收集所有TranslatedTextPart，并将其内容写入一个JSONL文件。
    - 在工作流结束时（call方法结束时）触发所有文件写入操作。
    """

    def __init__(self, artifact_writer: BaseArtifactWriter, translator: TranslatorProcessor, output_dir: str = "GlobalWorkflowOutputs"):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.artifact_writer = artifact_writer
        self.translator = translator
        self.output_manager = OutputManager(output_dir, self.logger)

        # 用于存储过程性数据的容器
        self.final_part: Optional[TranslatedBookPart] = None
        self.original_book_part: Optional[EpubBookPart] = None

    async def _process(self, part: ProcessorPart) -> AsyncGenerator[ProcessorPart, None]:
        """收集工作流中流动的各种Parts，以备后用。"""
        if isinstance(part, TranslatedBookPart):
            self.logger.debug(f"Captured final part: {part}")
            self.final_part = part
        elif isinstance(part, EpubBookPart) and not self.original_book_part:
            self.logger.debug(f"Captured original book part: {part}")
            self.original_book_part = part
        
        # 将所有part直接传递下去，本处理器只在最后进行写操作
        yield part

    def _write_outputs(self):
        """执行所有文件写入操作。"""
        if not self.final_part:
            self.logger.warning("No final part (e.g., TranslatedBookPart) received. Skipping output generation.")
            return

        # 使用正确的键 "original_file"
        if "original_file" not in self.final_part.metadata:
            self.logger.error("Could not find 'original_file' in final part's metadata. Cannot determine output path.")
            if self.original_book_part:
                self.logger.error(f"Final part metadata dump: {self.final_part.metadata}")
            return

        original_filepath = Path(self.final_part.metadata.get("original_file"))
        workflow_dirname = original_filepath.stem
        workflow_output_dir = self.output_manager.base_output_dir / workflow_dirname
        self.logger.info(f"Creating output directory for workflow '{workflow_dirname}' at: {workflow_output_dir}")
        workflow_output_dir.mkdir(parents=True, exist_ok=True)

        # 1. 使用注入的写入器写入主要产物
        self.logger.info(f"Writing final artifact using {self.artifact_writer.__class__.__name__}...")
        self.artifact_writer.write(self.final_part, workflow_output_dir, workflow_dirname)

        # 2. 写入LLM响应
        self.logger.info("Writing LLM responses to llm_responses.jsonl...")
        llm_output_path = self.output_manager.get_workflow_output_path(workflow_dirname, "llm_responses.jsonl")
        try:
            with open(llm_output_path, 'w', encoding='utf-8') as f:
                # 从 TranslatorProcessor 的缓存中获取响应
                for resp_part in self.translator.llm_responses:
                    data_to_write = {
                        "metadata": resp_part.metadata,
                        "translated_text": resp_part.text,
                    }
                    f.write(json.dumps(data_to_write, ensure_ascii=False) + '\n')
            self.logger.info(f"Successfully saved LLM responses to {llm_output_path}")
        except Exception as e:
            self.logger.error(f"Failed to write LLM responses to {llm_output_path}: {e}")

    async def call(self, stream: AsyncGenerator[ProcessorPart, None]) -> AsyncGenerator[ProcessorPart, None]:
        """处理输入流，并在流结束后写入所有输出文件。"""
        async for part in stream:
            async for p in self._process(part):
                yield p
        
        # 在流处理完全结束后，执行文件写入
        self._write_outputs() 