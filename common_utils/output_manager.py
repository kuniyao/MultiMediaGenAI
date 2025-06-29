import os
from pathlib import Path
import logging

class OutputManager:
    def __init__(self, base_output_dir: str, logger: logging.Logger):
        self.base_output_dir = Path(base_output_dir)
        self.logger = logger
        self.base_output_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Output directory set to: {self.base_output_dir}")

    def get_workflow_output_path(self, workflow_name: str, filename: str) -> Path:
        """Constructs a full output path for a given workflow and filename."""
        workflow_dir = self.base_output_dir / workflow_name
        workflow_dir.mkdir(parents=True, exist_ok=True)
        return workflow_dir / filename

    def save_file(self, file_path: Path, content: str):
        """Saves content to a specified file path."""
        try:
            file_path.write_text(content, encoding='utf-8')
            self.logger.info(f"File saved successfully: {file_path}")
        except Exception as e:
            self.logger.error(f"Error saving file {file_path}: {e}")
            raise
