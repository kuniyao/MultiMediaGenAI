from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple

class DataSource(ABC):
    """
    Abstract base class for all data sources.
    It defines the contract that all concrete data source implementations must follow.
    """

    @abstractmethod
    def get_segments(self) -> Tuple[List[Dict[str, Any]], str, str]:
        """
        The primary method to get subtitle segments from the source.

        Returns:
            A tuple containing:
            - A list of subtitle segments, where each segment is a dictionary.
            - The detected language code of the source (e.g., 'en').
            - The type of the source (e.g., 'youtube', 'local_file').
        """
        pass

    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """
        Returns a dictionary of metadata about the source,
        such as title, author, etc. This is used for naming output files
        and directories.
        """
        pass
