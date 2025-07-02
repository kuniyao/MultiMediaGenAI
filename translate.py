import argparse
import asyncio
import os
import sys
from urllib.parse import urlparse
import logging
from datetime import datetime
from pathlib import Path

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Subtitle/Youtube workflow components
from workflows.orchestrator import TranslationOrchestrator
from data_sources.local_file_source import LocalFileSource
from data_sources.youtube_source import YouTubeSource

# E-book workflow components
from data_sources.epub_source import EpubSource
from workflows.epub_orchestrator import EpubOrchestrator

import config
from common_utils.log_config import setup_task_logger

def is_youtube_url(url: str) -> bool:
    """Checks if the given string is a valid YouTube URL."""
    parsed = urlparse(url)
    return parsed.netloc.endswith('youtube.com') or parsed.netloc.endswith('youtu.be')

async def main():
    """The main entry point for the unified translation workflow."""
    parser = argparse.ArgumentParser(description="Unified Translation Workflow for subtitles and e-books.")
    parser.add_argument("input", help="The source to translate: a YouTube URL, or a local file path (.srt, .epub).")
    parser.add_argument("--target_lang", help="Target language for translation.", default=config.DEFAULT_TARGET_TRANSLATION_LANGUAGE)
    
    # Subtitle/YouTube specific arguments
    parser.add_argument("--output_dir", help="Base directory for all output (used by subtitle/YouTube workflow).", default="GlobalWorkflowOutputs")
    
    # E-book specific arguments
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrency limit for API requests (used by e-book workflow).")
    parser.add_argument("--prompts", type=str, default="prompts.json", help="Path to a JSON file with prompt templates (used by e-book workflow).")
    parser.add_argument("--glossary", type=str, default=None, help="Optional path to a JSON glossary file (used by e-book workflow).")
    parser.add_argument("--max_chapters", type=int, default=None, help="Maximum number of chapters to translate (for testing).")
    
    # General arguments
    parser.add_argument("--log_level", help="Set the logging level.", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    parser.add_argument("--save_llm_logs", action="store_true", help="Save raw LLM response logs to the output directory.")
    args = parser.parse_args()

    # Setup global logger for the application
    logs_dir = Path(project_root) / config.LOGS_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file_name = f"run_translation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_file_path = logs_dir / log_file_name
    root_logger = setup_task_logger("RootLogger", str(log_file_path), level=getattr(logging, args.log_level.upper(), logging.INFO))

    # Determine workflow based on input
    file_extension = os.path.splitext(args.input)[1].lower()
    
    orchestrator = None

    if file_extension == '.epub':
        root_logger.info("Detected EPUB file input. Starting e-book translation workflow.")
        data_source = EpubSource(args.input, root_logger)
        orchestrator = EpubOrchestrator(
            data_source=data_source,
            target_lang=args.target_lang,
            concurrency=args.concurrency,
            prompts_path=args.prompts,
            glossary_path=args.glossary,
            logger=root_logger,
            output_dir=args.output_dir,
            save_llm_logs=args.save_llm_logs,
            max_chapters=args.max_chapters
        )
    elif is_youtube_url(args.input) or file_extension in ['.srt', '.vtt', '.ass']: # Support more subtitle formats
        root_logger.info("Detected YouTube URL or subtitle file input. Starting subtitle translation workflow.")
        data_source = None
        if os.path.isfile(args.input):
            root_logger.info(f"Detected local file input: {args.input}")
            data_source = LocalFileSource(args.input, root_logger)
        elif is_youtube_url(args.input):
            root_logger.info(f"Detected YouTube URL input: {args.input}")
            data_source = YouTubeSource(args.input, root_logger)
        
        if not data_source:
             root_logger.error(f"Error: Input '{args.input}' is not a valid file path or YouTube URL.")
             sys.exit(1)

        orchestrator = TranslationOrchestrator(
            data_source=data_source,
            target_lang=args.target_lang,
            output_dir=args.output_dir,
            log_level=args.log_level,
            save_llm_logs=args.save_llm_logs
        )
    else:
        root_logger.error(f"Error: Input '{args.input}' is not a supported file type or a valid YouTube URL.")
        sys.exit(1)
        
    if orchestrator:
        await orchestrator.run()

if __name__ == "__main__":
    # The main function is now async, so we need to run it with asyncio.
    asyncio.run(main())