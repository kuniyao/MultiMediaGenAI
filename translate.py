import argparse
import asyncio
import os
import sys
import logging
from datetime import datetime
from pathlib import Path

# --- genai-processors 导入 ---
from workflows.parts import TranslationRequestPart
from llm_utils.translator import TranslatorProcessor

# --- EPUB 工作流导入 (新方案) ---
from processors.book.epub_parsing_processor import EpubParsingProcessor
from processors.book.chapter_preparation_processor import ChapterPreparationProcessor # 【新】
from processors.book.html_to_chapter_processor import HtmlToChapterProcessor
from processors.book.book_build_processor import BookBuildProcessor
from processors.book.epub_writing_processor import EpubWritingProcessor
from processors.book.temp_dir_cleanup_processor import TempDirCleanupProcessor
# --- 结束导入 ---

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import config
from common_utils.log_config import setup_task_logger

# 輔助函式，將單一 Part 轉換為非同步串流
async def part_to_stream(part):
    yield part

def create_epub_pipeline():
    """
    构建EPUB书籍翻译的并行流水线 (新方案)。
    该流水线融合了旧工作流的智能切分/打包逻辑和新框架的流式处理能力。
    """
    # 完整的 EPUB 工作流
    return (
        EpubParsingProcessor() +
        # 【新】使用智能預處理器，它會消耗掉 EpubBookPart，
        # 然後產出一系列優化過的 BatchTranslationTaskPart 和 SplitChapterTaskPart
        ChapterPreparationProcessor() +
        # 將翻譯器轉換為一個可以處理多種任務Part的Processor
        TranslatorProcessor().to_processor() +
        # HtmlToChapterProcessor 現在需要處理來自翻譯器的、包含元數據的 TranslatedTextPart
        HtmlToChapterProcessor() +
        # BookBuildProcessor 現在需要處理來自 HtmlToChapterProcessor 的 TranslatedChapterPart
        # 和來自 ChapterPreparationProcessor 的原始 EpubBookPart
        BookBuildProcessor() +
        EpubWritingProcessor() +
        TempDirCleanupProcessor()
    )

async def main():
    """The main entry point for the unified translation workflow."""
    # 参数解析部分
    parser = argparse.ArgumentParser(description="Unified Translation Workflow using genai-processors.")
    parser.add_argument("input", help="The source file to translate (e.g., .txt, .md, .epub).")
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

    # --- 核心逻辑：根据文件类型组装与运行 ---
    input_path = Path(args.input)
    
    if input_path.suffix.lower() == '.epub':
        root_logger.info("Assembling EPUB Translation Pipeline (genai-processors)...")
        pipeline = create_epub_pipeline()
    else:
        # For simplicity, we focus on the EPUB pipeline. 
        # The generic file pipeline would need similar refactoring.
        root_logger.error("Generic file translation is not the focus of this refactoring.")
        return

    # 2. 准备初始 Part
    initial_part = TranslationRequestPart(
        text_to_translate=str(input_path),
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        metadata={
            "title": input_path.stem,
            "original_file": str(input_path),
            "source_lang": args.source_lang, # 传递给 preparation processor
            "target_lang": args.target_lang, # 传递给 preparation processor
            "llm_processing_id": f"file::{input_path.name}",
            "output_dir": args.output_dir
        }
    )

    # 3. 运行管道
    root_logger.info(f"Running translation for '{args.input}' from '{args.source_lang}' to '{args.target_lang}'...")
    async for result_part in pipeline(part_to_stream(initial_part)):
        part_type = type(result_part).__name__
        title = result_part.metadata.get('title', 'N/A')
        root_logger.info(f"Pipeline yielded result: {part_type} for '{title}'")

    root_logger.info("✅ Workflow completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())