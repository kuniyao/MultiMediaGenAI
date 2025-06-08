import logging
import time
import xml.etree.ElementTree as ET
from pytubefix import YouTube
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled, CouldNotRetrieveTranscript
import config # Assuming config.py is in the PYTHONPATH or project root

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

        except (ET.ParseError, CouldNotRetrieveTranscript) as e: # Catch specific errors for retry
            last_exception = e
            logger_to_use.warning(f"Attempt {attempt + 1} to fetch transcript for {video_id} failed: {e}")
            if attempt < max_retries:
                logger_to_use.info(f"Retrying in {retry_delay_seconds} seconds...")
                time.sleep(retry_delay_seconds)
            else:
                logger_to_use.error(f"All {max_retries + 1} attempts to fetch transcript for {video_id} failed.")
        except TranscriptsDisabled:
            logger_to_use.error(f"Transcripts are disabled for video {video_id}.", exc_info=True)
            return None, None, None # No point in retrying if disabled
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

def preprocess_and_merge_segments(raw_transcript_data, logger=None):
    """
    Merges raw transcript segments based on duration, length, and punctuation.
    Also cleans up newlines within segments.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    if not raw_transcript_data:
        logger_to_use.info("preprocess_and_merge_segments: Received empty raw_transcript_data. Returning empty list.")
        return []
    logger_to_use.debug(f"preprocess_and_merge_segments: Starting with {len(raw_transcript_data)} raw entries.")

    initial_cleaned_entries = []
    for entry_obj in raw_transcript_data:
        cleaned_text = entry_obj.text.replace('\n', ' ').strip()
        if cleaned_text:
            initial_cleaned_entries.append({
                'text': cleaned_text,
                'start': entry_obj.start,    
                'duration': entry_obj.duration,
                'original_text_length': len(cleaned_text)
            })

    if not initial_cleaned_entries:
        return []
    
    def _is_actual_sentence_end_char(text_segment, char_index_in_segment, sentence_end_punctuations_config):
        char_to_check = text_segment[char_index_in_segment]
        if char_to_check == '.':
            is_prev_digit = (char_index_in_segment > 0 and text_segment[char_index_in_segment - 1].isdigit())
            is_next_digit = (char_index_in_segment < len(text_segment) - 1 and text_segment[char_index_in_segment + 1].isdigit())
            if is_prev_digit and is_next_digit: return False 
            if not is_prev_digit and is_next_digit: 
                if not (char_index_in_segment > 0 and text_segment[char_index_in_segment - 1] == '.'): return False 
            prev_char_is_alnum = (char_index_in_segment > 0 and text_segment[char_index_in_segment - 1].isalnum())
            next_char_is_alnum = (char_index_in_segment < len(text_segment) - 1 and text_segment[char_index_in_segment + 1].isalnum())
            if prev_char_is_alnum and next_char_is_alnum:
                idx_after_alnum_dot_alnum = char_index_in_segment + 2 
                if idx_after_alnum_dot_alnum < len(text_segment) -1:
                    if text_segment[idx_after_alnum_dot_alnum] == ' ' and text_segment[idx_after_alnum_dot_alnum + 1].isupper(): return True 
                    else: return False 
                else: return False 
            return True
        elif char_to_check in sentence_end_punctuations_config: return True
        return False

    logger_to_use.debug(f"\n--- Starting Pre-segmentation and Merging Logic ---")
    logger_to_use.debug(f"Pass 1: Initial cleaning complete. {len(initial_cleaned_entries)} entries.")

    fine_grained_entries = []
    for i, entry_dict in enumerate(initial_cleaned_entries):
        text_to_process = entry_dict['text']
        original_start_time = entry_dict['start']
        original_duration = entry_dict['duration']
        original_text_len = entry_dict['original_text_length']
        if original_text_len == 0: continue
        current_sub_segment_start_time = original_start_time
        while text_to_process:
            found_punc_at = -1
            for punc_char_idx, char_in_text in enumerate(text_to_process):
                if _is_actual_sentence_end_char(text_to_process, punc_char_idx, config.SENTENCE_END_PUNCTUATIONS):
                    found_punc_at = punc_char_idx
                    break
            if found_punc_at != -1:
                sub_segment_text = text_to_process[:found_punc_at + 1]
                len_sub_segment = len(sub_segment_text)
                estimated_duration = (len_sub_segment / original_text_len) * original_duration
                fine_grained_entries.append({
                    'text': sub_segment_text,
                    'start': current_sub_segment_start_time,
                    'duration': estimated_duration
                })
                current_sub_segment_start_time += estimated_duration
                text_to_process = text_to_process[found_punc_at + 1:].lstrip()
            else:
                if text_to_process:
                    remaining_len = len(text_to_process)
                    estimated_duration = (remaining_len / original_text_len) * original_duration
                    fine_grained_entries.append({
                        'text': text_to_process,
                        'start': current_sub_segment_start_time,
                        'duration': estimated_duration 
                    })
                text_to_process = ""
        
    logger_to_use.debug(f"Pass 2: Pre-splitting complete. {len(fine_grained_entries)} fine-grained entries generated.")

    logger_to_use.debug(f"\nPass 3: Merging fine-grained entries (Punctuation ONLY at end of accumulation)...")
    logger_to_use.debug(f"Configured Sentence End Punctuations: {config.SENTENCE_END_PUNCTUATIONS}\n")

    final_merged_segments = []
    current_accumulated_fine_grained_entries = [] 
    for i, fg_entry_dict in enumerate(fine_grained_entries):
        current_accumulated_fine_grained_entries.append(fg_entry_dict)
        current_segment_text = " ".join(e['text'] for e in current_accumulated_fine_grained_entries)
        if current_segment_text and _is_actual_sentence_end_char(current_segment_text, len(current_segment_text)-1, config.SENTENCE_END_PUNCTUATIONS):
            segment_start_time = current_accumulated_fine_grained_entries[0]['start']
            segment_end_time = current_accumulated_fine_grained_entries[-1]['start'] + current_accumulated_fine_grained_entries[-1]['duration']
            segment_duration = segment_end_time - segment_start_time
            
            # Fix for negative duration issue caused by ASR timestamp errors
            if segment_duration < 0:
                logger_to_use.warning(f"Negative duration detected ({segment_duration:.3f}s) for segment. Correcting to 0. Text: '{current_segment_text}'")
                segment_duration = 0

            final_merged_segments.append({
                'text': current_segment_text,
                'start': segment_start_time,
                'duration': segment_duration
            })
            current_accumulated_fine_grained_entries = [] 
        else:
            pass

    if current_accumulated_fine_grained_entries:
        logger_to_use.debug(f"\n  Pass 3 - Finalizing remaining accumulated fine-grained entries as the last segment.")
        segment_text = " ".join(e['text'] for e in current_accumulated_fine_grained_entries)
        segment_start_time = current_accumulated_fine_grained_entries[0]['start']
        segment_end_time = current_accumulated_fine_grained_entries[-1]['start'] + current_accumulated_fine_grained_entries[-1]['duration']
        segment_duration = segment_end_time - segment_start_time
        
        # Fix for negative duration issue caused by ASR timestamp errors
        if segment_duration < 0:
            logger_to_use.warning(f"Negative duration detected ({segment_duration:.3f}s) for final segment. Correcting to 0. Text: '{segment_text}'")
            segment_duration = 0

        final_merged_segments.append({
            'text': segment_text,
            'start': segment_start_time,
            'duration': segment_duration
        })
    
    logger_to_use.debug(f"--- Pre-segmentation and Merging Logic Finished. Total segments: {len(final_merged_segments)} ---")
    return final_merged_segments

def get_video_id(url_or_id):
    if "youtube.com/watch?v=" in url_or_id:
        return url_or_id.split("watch?v=")[1].split("&")[0]
    elif "youtu.be/" in url_or_id:
        return url_or_id.split("youtu.be/")[1].split("?")[0]
    return url_or_id 