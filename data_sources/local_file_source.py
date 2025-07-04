import os
from pathlib import Path
from typing import List, Dict, Any, Tuple

from .base_source import SegmentedDataSource
from format_converters import load_and_merge_srt_segments

class LocalFileSource(SegmentedDataSource):
    """
    Data source implementation for handling local SRT files.
    """
    def __init__(self, file_path: str, logger):
        self.file_path = Path(file_path)
        self.logger = logger
        if not self.file_path.is_file():
            self.logger.error(f"File not found: {self.file_path}")
            raise FileNotFoundError(f"The specified file was not found: {self.file_path}")

    def get_segments(self) -> Tuple[List[Dict[str, Any]], str, str]:
        """
        Loads segments from the local SRT file and processes them.
        """
        self.logger.info(f"Processing local file source: {self.file_path}")
        # Here we use our robust, intelligent merging function
        merged_segments = load_and_merge_srt_segments(self.file_path, self.logger)
        if not merged_segments:
            return [], "unknown", "local_file"
        
        # For local files, we assume the language is unknown and let the translator detect it.
        return merged_segments, "auto", "local_srt_file"

    def get_metadata(self) -> Dict[str, Any]:
        """
        Extracts metadata from the file path.
        """
        return {
            "title": self.file_path.stem,
            "filename": self.file_path.name
        }
