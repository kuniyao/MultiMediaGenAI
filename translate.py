import argparse
import asyncio
import os
import sys
import logging
from datetime import datetime
from pathlib import Path

# --- genai-processors 导入 ---
from workflows.parts import TranslationRequestPart
from data_sources.local_file_source import LocalFileSource
from llm_utils.prompt_builder_processor import PromptBuilderProcessor
from llm_utils.translator import TranslatorProcessor
from processors.subtitle.file_write_processor import FileWriterProcessor
# --- 结束 genai-processors 导入 ---

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import config
from common_utils.log_config import setup_task_logger

# 輔助函式，將單一 Part 轉換為非同步串流
async def part_to_stream(part):
    yield part

async def main():
    """The main entry point for the unified translation workflow."""
    # 参数解析部分
    parser = argparse.ArgumentParser(description="Unified Translation Workflow using genai-processors.")
    parser.add_argument("input", help="The source file to translate (e.g., .txt, .md).")
    parser.add_argument("--target_lang", help="Target language for translation.", default=config.DEFAULT_TARGET_TRANSLATION_LANGUAGE)
    parser.add_argument("--source_lang", help="Source language for translation.", default="en")
    parser.add_argument("--output_dir", help="Base directory for all output.", default="GlobalWorkflowOutputs")
    parser.add_argument("--log_level", help="Set the logging level.", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    args = parser.parse_args()

    # 日志设置
    logs_dir = Path(project_root) / config.LOGS_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file_name = f"run_translation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_file_path = logs_dir / log_file_name
    root_logger = setup_task_logger("RootLogger", str(log_file_path), level=getattr(logging, args.log_level.upper(), logging.INFO))

    # --- 核心逻辑：组装与运行 ---
    root_logger.info("Assembling Generic File Translation Pipeline (genai-processors)...")
    
    # 1. 组装管道
    pipeline = (
        LocalFileSource() +
        PromptBuilderProcessor() +
        TranslatorProcessor() +
        FileWriterProcessor(output_dir=args.output_dir)
    )

    # 2. 准备初始 Part
    initial_part = TranslationRequestPart(
        text_to_translate=args.input, # LocalFileSource 会��取这个路径
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        metadata={
            "title": Path(args.input).stem,
            "original_file": args.input,
            "target_lang": args.target_lang,
            "llm_processing_id": f"file::{Path(args.input).name}" # 构造一个简单的 ID
        }
    )

    # 3. 运行管道
    root_logger.info(f"Running translation for '{args.input}' from '{args.source_lang}' to '{args.target_lang}'...")
    # 使用輔助函式將 Part 轉換為串流
    async for result_part in pipeline(part_to_stream(initial_part)):
        # 在这里，我们可以选择性地处理最终的结果
        root_logger.info(f"Pipeline yielded result: {result_part}")

    root_logger.info("✅ Workflow completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
