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

def get_youtube_transcript(video_url_or_id, logger=None):
    """
    Fetches the transcript for a given YouTube video ID or URL.
    Prioritizes manually created transcripts, then falls back to generated ones.
    Languages are prioritized based on config.py, then any available.
    Includes a retry mechanism for fetching.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    max_retries = 2  # Retry up to 2 times after the initial attempt (total 3 attempts)
    retry_delay_seconds = 5 

    video_id = video_url_or_id
    if "youtube.com/watch?v=" in video_url_or_id:
        video_id = video_url_or_id.split("watch?v=")[1].split("&")[0]
    elif "youtu.be/" in video_url_or_id:
        video_id = video_url_or_id.split("youtu.be/")[1].split("?")[0]

    last_exception = None # To store the last exception if all retries fail

    for attempt in range(max_retries + 1):
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            preferred_langs = config.PREFERRED_TRANSCRIPT_LANGUAGES
            if attempt == 0: # Log initial attempt only once
                logger_to_use.debug(f"Attempting to find manual transcript in preferred languages: {preferred_langs} for video {video_id}")

            for lang in preferred_langs:
                try:
                    transcript = transcript_list.find_manually_created_transcript([lang])
                    logger_to_use.debug(f"Found manually created transcript in '{lang}' for video {video_id}.")
                    return transcript.fetch(), lang, "manual" # Attempt to fetch
                except NoTranscriptFound:
                    continue
            if attempt == 0:
                 logger_to_use.debug(f"No manually created transcript found in preferred languages for video {video_id}.")

            if attempt == 0:
                logger_to_use.debug(f"Attempting to find auto-generated transcript in preferred languages: {preferred_langs} for video {video_id}")
            for lang in preferred_langs:
                try:
                    transcript = transcript_list.find_generated_transcript([lang])
                    logger_to_use.debug(f"Found auto-generated transcript in '{lang}' for video {video_id}.")
                    return transcript.fetch(), lang, "generated" # Attempt to fetch
                except NoTranscriptFound:
                    continue
            if attempt == 0:
                logger_to_use.debug(f"No auto-generated transcript found in preferred languages for video {video_id}.")

            available_manual = transcript_list._manually_created_transcripts
            if available_manual:
                first_available_manual_lang = list(available_manual.keys())[0]
                if attempt == 0:
                    logger_to_use.debug(f"Attempting to find first available manual transcript ('{first_available_manual_lang}') for video {video_id}.")
                try:
                    transcript = transcript_list.find_manually_created_transcript([first_available_manual_lang])
                    logger_to_use.debug(f"Found manually created transcript in '{first_available_manual_lang}' (first available) for video {video_id}.")
                    return transcript.fetch(), first_available_manual_lang, "manual"
                except NoTranscriptFound:
                    logger_to_use.warning(f"Key '{first_available_manual_lang}' existed in available_manual but NoTranscriptFound was raised.", exc_info=True)
                    pass 
            if attempt == 0:
                logger_to_use.debug(f"No manually created transcript found in any language for video {video_id}.")

            available_generated = transcript_list._generated_transcripts
            if available_generated:
                first_available_generated_lang = list(available_generated.keys())[0]
                if attempt == 0:
                    logger_to_use.debug(f"Attempting to find first available auto-generated transcript ('{first_available_generated_lang}') for video {video_id}.")
                try:
                    transcript = transcript_list.find_generated_transcript([first_available_generated_lang])
                    logger_to_use.debug(f"Found auto-generated transcript in '{first_available_generated_lang}' (first available) for video {video_id}.")
                    return transcript.fetch(), first_available_generated_lang, "generated"
                except NoTranscriptFound:
                     logger_to_use.warning(f"Key '{first_available_generated_lang}' existed in available_generated but NoTranscriptFound was raised.", exc_info=True)
                     pass
            if attempt == 0:
                 logger_to_use.debug(f"No auto-generated transcript found in any language for video {video_id}.")
            
            logger_to_use.error(f"No suitable transcript found to fetch for video {video_id} even after listing available.")
            return None, None, None # No suitable transcript type found to even attempt fetching

        except TranscriptsDisabled:
            logger_to_use.error(f"Transcripts are disabled for video {video_id}.", exc_info=True)
            return None, None, None # No point in retrying if disabled
        except (ET.ParseError, CouldNotRetrieveTranscript) as e: # Catch specific errors for retry
            last_exception = e
            logger_to_use.warning(f"Attempt {attempt + 1} to fetch transcript for {video_id} failed: {e}")
            if attempt < max_retries:
                logger_to_use.info(f"Retrying in {retry_delay_seconds} seconds...")
                time.sleep(retry_delay_seconds)
            else:
                logger_to_use.error(f"All {max_retries + 1} attempts to fetch transcript for {video_id} failed.")
        except Exception as e: # Catch other unexpected errors from list_transcripts or other parts
            logger_to_use.error(f"An unexpected error occurred while trying to list/find transcript for {video_id} on attempt {attempt + 1}: {e}", exc_info=True)
            last_exception = e # Store it
            if attempt < max_retries: # Also retry on generic errors during listing, could be temp network
                 logger_to_use.info(f"Retrying generic error in {retry_delay_seconds} seconds...")
                 time.sleep(retry_delay_seconds)
            else:
                logger_to_use.error(f"All {max_retries + 1} attempts failed due to unexpected errors for {video_id}.")

    logger_to_use.error(f"Failed to fetch transcript for {video_id} after all retries. Last error: {last_exception}", exc_info=True if last_exception else False)
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