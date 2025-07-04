from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple
from format_converters.book_schema import Book

class SegmentedDataSource(ABC):
    """
    Abstract base class for segment-based data sources (e.g., subtitles).
    It defines the contract for sources that provide time-stamped segments.
    """

    @abstractmethod
    def get_segments(self) -> Tuple[List[Dict[str, Any]], str, str]:
        """
        The primary method to get subtitle segments from the source.

        Returns:
            A tuple containing:
            - A list of subtitle segments.
            - The detected language code of the source.
            - The type of the source.
        """
        pass

    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """
        Returns a dictionary of metadata about the source,
        such as title, author, etc.
        """
        pass

class BookDataSource(ABC):
    """
    Abstract base class for book-like data sources (e.g., EPUB, other documents).
    It defines the contract for sources that can be parsed into a Book object.
    """

    @abstractmethod
    def get_book(self) -> Book:
        """
        Parses the source and converts it into a structured Book object.
        """
        pass