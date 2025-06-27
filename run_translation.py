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

from workflows.orchestrator import TranslationOrchestrator
from data_sources.local_file_source import LocalFileSource
from data_sources.youtube_source import YouTubeSource
import config
from common_utils.log_config import setup_task_logger

def is_youtube_url(url: str) -> bool:
    """Checks if the given string is a valid YouTube URL."""
    parsed = urlparse(url)
    return parsed.netloc.endswith('youtube.com') or parsed.netloc.endswith('youtu.be')

def main():
    """The main entry point for the unified translation workflow."""
    parser = argparse.ArgumentParser(description="Unified Translation Workflow for Subtitles.")
    parser.add_argument("input", help="The source to translate: a YouTube URL or a local file path.")
    parser.add_argument("--target_lang", help="Target language for translation.", default=config.DEFAULT_TARGET_TRANSLATION_LANGUAGE)
    parser.add_argument("--output_dir", help="Base directory for all output.", default="GlobalWorkflowOutputs")
    parser.add_argument("--log_level", help="Set the logging level.", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    args = parser.parse_args()

    # Setup global logger for the application
    # The orchestrator will then create a task-specific logger
    logs_dir = Path(project_root) / config.LOGS_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file_name = f"run_translation_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log"
    log_file_path = logs_dir / log_file_name
    root_logger = setup_task_logger("RootLogger", str(log_file_path), level=getattr(logging, args.log_level.upper(), logging.INFO))

    # Determine the data source based on the input
    data_source = None
    if os.path.isfile(args.input):
        root_logger.info("Detected local file input.")
        data_source = LocalFileSource(args.input, root_logger)
    elif is_youtube_url(args.input):
        root_logger.info("Detected YouTube URL input.")
        data_source = YouTubeSource(args.input, root_logger)
    else:
        root_logger.error(f"Error: Input '{args.input}' is not a valid file path or YouTube URL.")
        sys.exit(1)

    # Initialize and run the orchestrator
    orchestrator = TranslationOrchestrator(
        data_source=data_source,
        target_lang=args.target_lang,
        output_dir=args.output_dir,
        log_level=args.log_level
    )
    
    asyncio.run(orchestrator.run())

if __name__ == "__main__":
    main()