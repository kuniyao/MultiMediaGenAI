from .base_source import DataSource
from format_converters.epub_parser import EpubParser
from format_converters.book_schema import Book

class EpubSource(DataSource):
    def __init__(self, file_path: str, logger):
        self.source = file_path
        self.logger = logger

    def get_data(self) -> Book:
        self.logger.info(f"正在從EPUB檔案解析數據: {self.source}")
        parser = EpubParser(self.source, self.logger)
        return parser.to_book()
        
    def get_segments(self):
        # This is part of the DataSource interface, but not used by EpubOrchestrator.
        # Returning empty values to satisfy the abstract class requirements.
        self.logger.warning("get_segments is not implemented for EpubSource and should not be called.")
        return [], "", "epub"

    def get_metadata(self):
        # This is part of the DataSource interface, but not used by EpubOrchestrator.
        self.logger.warning("get_metadata is not implemented for EpubSource and should not be called.")
        return {} 