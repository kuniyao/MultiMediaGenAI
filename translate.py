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
from processors.book.chapter_to_html_processor import ChapterToHtmlProcessor
from processors.book.html_to_chapter_processor import HtmlToChapterProcessor
from processors.book.book_build_processor import BookBuildProcessor
from processors.book.output_gen_processor import OutputGenerationProcessor
from processors.book.artifact_writers import EpubArtifactWriter
from processors.book.temp_dir_cleanup_processor import TempDirCleanupProcessor
from processors.book.log_setup_processor import LogSetupProcessor # 【新】导入日志设置处理器
# from processors.book.epub_writing_processor import EpubWritingProcessor # DEPRECATED
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

def build_book_translation_workflow():
    """
    构建并连接EPUB书籍翻译工作流的所有处理器。
    """
    # 1. 初始化所有需要的处理器
    log_setup_processor = LogSetupProcessor()
    epub_parsing_processor = EpubParsingProcessor()
    chapter_preparation_processor = ChapterPreparationProcessor()
    translation_processor = TranslatorProcessor()
    html_to_chapter_processor = HtmlToChapterProcessor()
    book_build_processor = BookBuildProcessor()
    # 【新】将 translator 实例注入到 output_processor
    output_processor = OutputGenerationProcessor(
        artifact_writer=EpubArtifactWriter(),
        translator=translation_processor
    )
    temp_dir_cleanup_processor = TempDirCleanupProcessor()

    # 2. 将所有处理器连接成一个管道
    # The '+' operator is overloaded to chain processors.
    pipeline = (
        log_setup_processor + # 【新】在最开始设置日志
        epub_parsing_processor +
        chapter_preparation_processor +
        translation_processor +
        html_to_chapter_processor +
        book_build_processor +
        output_processor +
        temp_dir_cleanup_processor
    )
    return pipeline

async def main():
    """The main entry point for the unified translation workflow."""
    # 【终极诊断】打印出Python接收到的最原始的参数列表
    import sys
    print(f"DIAGNOSTIC - sys.argv: {sys.argv}")

    # 参数解析部分
    parser = argparse.ArgumentParser(description="Unified Translation Workflow using genai-processors.")
    parser.add_argument("input", help="The source file to translate (e.g., .txt, .md, .epub).")
    parser.add_argument("--target_lang", help="Target language for translation.", default=config.DEFAULT_TARGET_TRANSLATION_LANGUAGE)
    parser.add_argument("--source_lang", help="Source language for translation.", default="en")
    parser.add_argument("--output_dir", help="Base directory for all output.", default="GlobalWorkflowOutputs")
    # 【诊断性修复】暂时移除 choices 验证，以绕过潜在的 argparse bug
    parser.add_argument("--log_level", help="Set the logging level.", default="INFO")
    args = parser.parse_args()

    # 【修复】初始只设置控制台日志，文件日志由 LogSetupProcessor 在工作流中动态添加
    root_logger = setup_task_logger(
        "RootLogger", 
        console_level=getattr(logging, args.log_level.upper(), logging.INFO)
    )

    # --- 核心逻辑：根据文件类型组装与运行 ---
    input_path = Path(args.input)
    
    if input_path.suffix.lower() == '.epub':
        root_logger.info("Assembling EPUB Translation Pipeline (genai-processors)...")
        pipeline = build_book_translation_workflow()
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