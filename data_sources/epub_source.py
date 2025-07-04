from .base_source import BookDataSource
from format_converters.epub_parser import EpubParser
from format_converters.book_schema import Book

class EpubSource(BookDataSource):
    def __init__(self, file_path: str, logger):
        self.source = file_path
        self.logger = logger

    def get_book(self) -> Book:
        self.logger.info(f"正在從EPUB檔案解析數據: {self.source}")
        parser = EpubParser(self.source, self.logger)
        return parser.to_book() 