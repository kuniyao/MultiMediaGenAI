from typing import List, Dict, Any, Tuple

from .base_source import SegmentedDataSource
from youtube_utils.data_fetcher import get_video_id, get_youtube_video_title, fetch_and_prepare_transcript

class YouTubeSource(SegmentedDataSource):
    """
    Data source implementation for handling YouTube videos.
    """
    def __init__(self, video_url_or_id: str, logger):
        self.video_url_or_id = video_url_or_id
        self.logger = logger
        self.video_id = get_video_id(video_url_or_id)
        self.video_title = get_youtube_video_title(video_url_or_id, logger)

    def get_segments(self) -> Tuple[List[Dict[str, Any]], str, str]:
        """
        Fetches transcript from YouTube and processes it using the intelligent merger.
        """
        self.logger.info(f"Processing YouTube source: {self.video_url_or_id}")
        
        # The fetch_and_prepare_transcript function already handles the merging.
        # We directly return its result.
        return fetch_and_prepare_transcript(
            video_id=self.video_id,
            logger=self.logger
        )

    def get_metadata(self) -> Dict[str, Any]:
        """
        Returns metadata for the YouTube video.
        """
        return {
            "title": self.video_title,
            "video_id": self.video_id
        }
