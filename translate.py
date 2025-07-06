import argparse
import asyncio
import os
import sys
import logging
from datetime import datetime
from pathlib import Path

# --- 统一导入 ---
# 导入管道和数据契约
from workflows.pipeline import Pipeline
from workflows.dto import PipelineContext

# 导入所有处理器
from processors.base_processor import BaseProcessor
# 字幕工作流处理器
from processors.data_fetch_processor import DataFetchProcessor
from processors.modeling_processor import ModelingProcessor
from processors.translation_prep_processor import TranslationPrepProcessor
from processors.translation_core_processor import TranslationCoreProcessor
from processors.output_gen_processor import OutputGenProcessor
# 【新】导入EPUB工作流处理器
from processors.epub_parsing_processor import EpubParsingProcessor
from processors.chapter_extraction_processor import ChapterExtractionProcessor
from processors.book_translation_processor import BookTranslationProcessor
from processors.validation_repair_processor import ValidationAndRepairProcessor
from processors.book_build_processor import BookBuildProcessor
from processors.epub_writing_processor import EpubWritingProcessor
# 【修改】将FileWriteProcessor重命名为更具体的SubtitleFileWriteProcessor
from processors.file_write_processor import FileWriteProcessor as SubtitleFileWriteProcessor

# --- 统一导入结束 ---

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import config
from common_utils.log_config import setup_task_logger

def is_youtube_url(url: str) -> bool:
    """Checks if the given string is a valid YouTube URL."""
    return "youtube.com/watch?v=" in url or "youtu.be/" in url

async def main():
    """The main entry point for the unified translation workflow."""
    # 参数解析部分保持不变
    parser = argparse.ArgumentParser(description="Unified Translation Workflow for subtitles and e-books.")
    parser.add_argument("input", help="The source to translate: a YouTube URL, or a local file path (.srt, .epub).")
    parser.add_argument("--target_lang", help="Target language for translation.", default=config.DEFAULT_TARGET_TRANSLATION_LANGUAGE)
    parser.add_argument("--output_dir", help="Base directory for all output.", default="GlobalWorkflowOutputs")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrency limit for API requests (used by e-book workflow).")
    parser.add_argument("--prompts", type=str, default="prompts.json", help="Path to a JSON file with prompt templates.")
    parser.add_argument("--glossary", type=str, default=None, help="Optional path to a JSON glossary file.")
    parser.add_argument("--max_chapters", type=int, default=None, help="Maximum number of chapters to translate (for testing).")
    parser.add_argument("--log_level", help="Set the logging level.", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    parser.add_argument("--save_llm_logs", action="store_true", help="Save raw LLM response logs to the output directory.")
    args = parser.parse_args()

    # 日志设置保持不变
    logs_dir = Path(project_root) / config.LOGS_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file_name = f"run_translation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_file_path = logs_dir / log_file_name
    root_logger = setup_task_logger("RootLogger", str(log_file_path), level=getattr(logging, args.log_level.upper(), logging.INFO))

    # --- 核心逻辑：组装与运行 ---
    file_extension = os.path.splitext(args.input)[1].lower()
    
    # 准备初始化的上下文“货箱”
    initial_context = PipelineContext(
        source_input=args.input,
        target_lang=args.target_lang,
        output_dir=args.output_dir,
        concurrency=args.concurrency, # 传递并发数
        glossary=args.glossary     # 传递术语表路径 (后续处理器会加载)
    )

    processors: list[BaseProcessor] = []

    # 【修改】: 根据输入类型，组装不同的处理器流水线
    if file_extension == '.epub':
        root_logger.info("Assembling EPUB Translation Pipeline...")
        epub_processors = [
            EpubParsingProcessor(root_logger),
            ChapterExtractionProcessor(root_logger, max_chapters=args.max_chapters),
            BookTranslationProcessor(root_logger),
            ValidationAndRepairProcessor(root_logger),
            BookBuildProcessor(root_logger),
            EpubWritingProcessor(root_logger),
        ]
        processors = epub_processors
        
    elif is_youtube_url(args.input) or file_extension in ['.srt', '.vtt', '.ass']:
        root_logger.info("Assembling Subtitle Translation Pipeline...")
        subtitle_processors = [
            DataFetchProcessor(root_logger),
            ModelingProcessor(root_logger),
            TranslationPrepProcessor(root_logger),
            TranslationCoreProcessor(root_logger),
            OutputGenProcessor(root_logger),
            SubtitleFileWriteProcessor(root_logger), # 使用重命名后的类
        ]
        processors = subtitle_processors

    else:
        root_logger.error(f"Error: Input '{args.input}' is not a supported file type or a valid YouTube URL.")
        sys.exit(1)
        
    # 创建并运行管道
    if processors:
        pipeline = Pipeline(processors, root_logger)
        final_context = await pipeline.run(initial_context) # await 异步管道

        # 根据最终的上下文状态报告结果
        if final_context.is_successful:
            root_logger.info("✅ Workflow completed successfully!")
        else:
            root_logger.error(f"❌ Workflow failed. Final error: {final_context.error_message}")
    else:
        root_logger.error("No valid pipeline could be assembled for the given input.")


if __name__ == "__main__":
    asyncio.run(main())