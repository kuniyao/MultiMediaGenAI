import logging
import time
import xml.etree.ElementTree as ET
from pytubefix import YouTube
# 修正：根据linter建议，从内部模块导入
from youtube_transcript_api._api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled, CouldNotRetrieveTranscript
import config # Assuming config.py is in the PYTHONPATH or project root
from format_converters.preprocessing import merge_segments_intelligently

# Placeholder for YouTube data fetching logic

def get_video_id(url_or_id):
    """
    Extracts the video ID from a YouTube URL or returns the ID if it's already an ID.
    """
    if "youtube.com/watch?v=" in url_or_id:
        return url_or_id.split("watch?v=")[1].split("&")[0]
    elif "youtu.be/" in url_or_id:
        return url_or_id.split("youtu.be/")[1].split("?")[0]
    # Assume it's already an ID if no URL format matches
    return url_or_id

def _find_transcript(transcript_list, lang_codes, is_generated):
    """
    A helper function to find a transcript for a given list of language codes.
    """
    find_method = transcript_list.find_generated_transcript if is_generated else transcript_list.find_manually_created_transcript
    try:
        return find_method(lang_codes)
    except NoTranscriptFound:
        return None

def _find_best_transcript_for_video(transcript_list, video_id, logger):
    """
    Finds the best available transcript based on a prioritized search strategy.
    
    The strategy is as follows:
    1. Manually created transcript in preferred languages.
    2. Auto-generated transcript in preferred languages.
    3. First available manually created transcript in any language.
    4. First available auto-generated transcript in any language.
    """
    preferred_langs = config.PREFERRED_TRANSCRIPT_LANGUAGES
    
    # Search definitions: (description, is_generated, languages_to_try)
    search_attempts = [
        ("manual transcript in preferred languages", False, preferred_langs),
        ("auto-generated transcript in preferred languages", True, preferred_langs),
        ("first available manual transcript", False, list(transcript_list._manually_created_transcripts.keys())[:1]),
        ("first available auto-generated transcript", True, list(transcript_list._generated_transcripts.keys())[:1])
    ]

    for description, is_generated, langs in search_attempts:
        if not langs:
            continue
            
        logger.debug(f"Attempting to find {description} for video {video_id}...")
        transcript = _find_transcript(transcript_list, langs, is_generated)
        if transcript:
            transcript_type = "generated" if is_generated else "manual"
            logger.debug(f"Success: Found {transcript_type} transcript in '{transcript.language_code}'.")
            return transcript, transcript.language_code, transcript_type
            
    logger.warning(f"No suitable transcript found for video {video_id} after checking all options.")
    return None, None, None


def get_youtube_transcript(video_url_or_id, logger=None):
    """
    Fetches the transcript for a given YouTube video with a retry mechanism.
    
    This function orchestrates the process of finding and fetching the best
    available transcript by delegating the selection logic.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    max_retries = 2
    retry_delay_seconds = 5 
    video_id = get_video_id(video_url_or_id)
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            logger_to_use.debug(f"Attempt {attempt + 1}/{max_retries + 1} to list transcripts for {video_id}")
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            transcript, lang, transcript_type = _find_best_transcript_for_video(transcript_list, video_id, logger_to_use)

            if transcript:
                logger_to_use.debug(f"Fetching content for '{lang}' ({transcript_type}) transcript...")
                return transcript.fetch(), lang, transcript_type
            else:
                logger_to_use.error(f"No suitable transcript found to fetch for video {video_id}.")
                return None, None, None

        except TranscriptsDisabled:
            logger_to_use.error(f"Transcripts are disabled for video {video_id}.", exc_info=True)
            return None, None, None # No point in retrying if disabled
        except (ET.ParseError, CouldNotRetrieveTranscript) as e:
            last_exception = e
            logger_to_use.warning(f"Attempt {attempt + 1} to fetch transcript for {video_id} failed: {e}")
            if attempt < max_retries:
                logger_to_use.info(f"Retrying in {retry_delay_seconds} seconds...")
                time.sleep(retry_delay_seconds)
        except Exception as e:
            last_exception = e
            logger_to_use.error(f"An unexpected error occurred on attempt {attempt + 1} for {video_id}: {e}", exc_info=True)
            if attempt < max_retries:
                 logger_to_use.info(f"Retrying in {retry_delay_seconds} seconds...")
                 time.sleep(retry_delay_seconds)

    logger_to_use.error(f"All {max_retries + 1} attempts to fetch transcript for {video_id} failed. Last error: {last_exception}", exc_info=True if last_exception else False)
    return None, None, None

def get_youtube_video_title(video_url_or_id, logger=None):
    """
    Fetches the title of a YouTube video.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    video_url_for_pytube = video_url_or_id
    if not video_url_for_pytube.startswith("http"):
        video_url_for_pytube = f"https://www.youtube.com/watch?v={video_url_or_id}"
    
    logger_to_use.debug(f"Attempting to fetch video title for: {video_url_or_id} (using URL: {video_url_for_pytube})")
    try:
        yt = YouTube(video_url_for_pytube)
        title = yt.title
        logger_to_use.debug(f"Successfully fetched video title: '{title}' for {video_url_or_id}")
        return title
    except Exception as e:
        logger_to_use.error(f"Error fetching video title for '{video_url_or_id}': {e}", exc_info=True)
        video_id_fallback = video_url_or_id
        if "youtube.com/watch?v=" in video_url_or_id:
            video_id_fallback = video_url_or_id.split("watch?v=")[1].split("&")[0]
        elif "youtu.be/" in video_url_or_id:
            video_id_fallback = video_url_or_id.split("youtu.be/")[1].split("?")[0]
        return video_id_fallback

def fetch_and_prepare_transcript(video_id, logger=None):
    """
    Fetches, processes, and merges the transcript for a YouTube video.

    This is a high-level function that orchestrates the fetching of the
    raw transcript and the subsequent preprocessing and merging of its segments.

    Args:
        video_id (str): The ID of the YouTube video.
        logger: A logger instance for logging messages.

    Returns:
        A tuple containing:
        - list: A list of merged transcript segments.
        - str: The language code of the fetched transcript.
        - str: The source type of the transcript ('manual' or 'generated').
        Returns (None, None, None) if the process fails.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)

    raw_transcript_data, lang_code, source_type = get_youtube_transcript(video_id, logger=logger_to_use)

    if not raw_transcript_data:
        logger_to_use.error("Could not retrieve transcript. Process cannot continue.")
        return None, None, None
    logger_to_use.info(f"Successfully fetched {source_type} transcript in '{lang_code}'.")
    
    # Pass the raw transcript data (list of objects) directly to the merger.
    # The merger will be updated to handle this object format.
    merged_transcript_data = merge_segments_intelligently(raw_transcript_data, logger=logger_to_use)

    if not merged_transcript_data:
        logger_to_use.error("Transcript data is empty after preprocessing and merging. Process cannot continue.")
        return None, None, None
    logger_to_use.info(f"Preprocessing complete. Merged into {len(merged_transcript_data)} segments.")
    
    return merged_transcript_data, lang_code, source_type 