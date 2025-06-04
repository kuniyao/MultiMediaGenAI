import argparse
import os # Added for .env
import logging # Added for logging
import logging.handlers # Added for potential future use like rotating file handler
from datetime import datetime # Added for timestamp in log filename
from dotenv import load_dotenv # Added for .env

# pytubefix import should be here if not already present from previous steps
from pytubefix import YouTube # Make sure this line is present and correct

from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled, CouldNotRetrieveTranscript
# from pytube import YouTube # Commented out original pytube import
import shutil # Added for safe filename
import config # Added for config.py
import google.generativeai as genai # Added for Gemini
import time # Added for time.sleep if using batch delays
import json # Added for new translation flow
import re # For normalizing timestamp IDs
import string # Added for sanitize_filename
import xml.etree.ElementTree as ET # Added for specific exception handling

# --- Global Logger for general script messages (console output) ---
global_logger = logging.getLogger("GlobalYoutubeTranslator")
global_logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - GLOBAL - %(message)s')
console_handler.setFormatter(console_formatter)
if not global_logger.handlers:
    global_logger.addHandler(console_handler)
global_logger.propagate = False # Prevent messages from being passed to the root logger
# --- End of Global Logger Setup ---

def setup_video_logger(logger_name, log_file_path, level=logging.INFO):
    """Sets up a specific logger for a video processing task, outputting to a file."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    # Prevent duplicate handlers if this function might be called multiple times 
    # for the same logger instance with the same name (which it shouldn't in our case
    # as logger_name will be unique per video task run).
    if logger.hasHandlers():
        logger.handlers.clear()

    # File Handler
    file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    
    # Format: TIMESTAMP - LOGGER_NAME - LEVEL - FUNCTION_NAME - LINENO - MESSAGE
    log_format = '%(asctime)s - %(name)s - %(levelname)s - (%(module)s.%(funcName)s:%(lineno)d) - %(message)s'
    formatter = logging.Formatter(log_format)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

def get_youtube_transcript(video_url_or_id, logger=None):
    """
    Fetches the transcript for a given YouTube video ID or URL.
    Prioritizes manually created transcripts, then falls back to generated ones.
    Languages are prioritized based on config.py, then any available.
    Includes a retry mechanism for fetching.
    """
    logger_to_use = logger if logger else global_logger
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
                logger_to_use.info(f"Attempting to find manual transcript in preferred languages: {preferred_langs} for video {video_id}")

            for lang in preferred_langs:
                try:
                    transcript = transcript_list.find_manually_created_transcript([lang])
                    logger_to_use.info(f"Found manually created transcript in '{lang}' for video {video_id}.")
                    return transcript.fetch(), lang, "manual" # Attempt to fetch
                except NoTranscriptFound:
                    continue
            if attempt == 0:
                 logger_to_use.info(f"No manually created transcript found in preferred languages for video {video_id}.")

            if attempt == 0:
                logger_to_use.info(f"Attempting to find auto-generated transcript in preferred languages: {preferred_langs} for video {video_id}")
            for lang in preferred_langs:
                try:
                    transcript = transcript_list.find_generated_transcript([lang])
                    logger_to_use.info(f"Found auto-generated transcript in '{lang}' for video {video_id}.")
                    return transcript.fetch(), lang, "generated" # Attempt to fetch
                except NoTranscriptFound:
                    continue
            if attempt == 0:
                logger_to_use.info(f"No auto-generated transcript found in preferred languages for video {video_id}.")

            available_manual = transcript_list._manually_created_transcripts
            if available_manual:
                first_available_manual_lang = list(available_manual.keys())[0]
                if attempt == 0:
                    logger_to_use.info(f"Attempting to find first available manual transcript ('{first_available_manual_lang}') for video {video_id}.")
                try:
                    transcript = transcript_list.find_manually_created_transcript([first_available_manual_lang])
                    logger_to_use.info(f"Found manually created transcript in '{first_available_manual_lang}' (first available) for video {video_id}.")
                    return transcript.fetch(), first_available_manual_lang, "manual"
                except NoTranscriptFound:
                    logger_to_use.warning(f"Key '{first_available_manual_lang}' existed in available_manual but NoTranscriptFound was raised.", exc_info=True)
                    pass 
            if attempt == 0:
                logger_to_use.info(f"No manually created transcript found in any language for video {video_id}.")

            available_generated = transcript_list._generated_transcripts
            if available_generated:
                first_available_generated_lang = list(available_generated.keys())[0]
                if attempt == 0:
                    logger_to_use.info(f"Attempting to find first available auto-generated transcript ('{first_available_generated_lang}') for video {video_id}.")
                try:
                    transcript = transcript_list.find_generated_transcript([first_available_generated_lang])
                    logger_to_use.info(f"Found auto-generated transcript in '{first_available_generated_lang}' (first available) for video {video_id}.")
                    return transcript.fetch(), first_available_generated_lang, "generated"
                except NoTranscriptFound:
                     logger_to_use.warning(f"Key '{first_available_generated_lang}' existed in available_generated but NoTranscriptFound was raised.", exc_info=True)
                     pass
            if attempt == 0:
                 logger_to_use.info(f"No auto-generated transcript found in any language for video {video_id}.")
            
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
                # Optionally re-raise the last exception or handle it as before
                # For now, log and fall through to the generic exception handler or return None
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
                # Fall through to return None, None, None after logging the final error

    # If all retries fail and we fall out of the loop
    logger_to_use.error(f"Failed to fetch transcript for {video_id} after all retries. Last error: {last_exception}", exc_info=True if last_exception else False)
    return None, None, None

def get_youtube_video_title(video_url_or_id, logger=None):
    """
    Fetches the title of a YouTube video.
    """
    logger_to_use = logger if logger else global_logger
    video_url_for_pytube = video_url_or_id
    if not video_url_for_pytube.startswith("http"):
        video_url_for_pytube = f"https://www.youtube.com/watch?v={video_url_or_id}"
    
    logger_to_use.info(f"Attempting to fetch video title for: {video_url_or_id} (using URL: {video_url_for_pytube})")
    try:
        yt = YouTube(video_url_for_pytube)
        title = yt.title
        logger_to_use.info(f"Successfully fetched video title: '{title}' for {video_url_or_id}")
        return title
    except Exception as e:
        logger_to_use.error(f"Error fetching video title for '{video_url_or_id}': {e}", exc_info=True)
        # Fallback: extract video_id if it was a URL, or return the ID itself
        video_id_fallback = video_url_or_id
        if "youtube.com/watch?v=" in video_url_or_id:
            video_id_fallback = video_url_or_id.split("watch?v=")[1].split("&")[0]
        elif "youtu.be/" in video_url_or_id:
            video_id_fallback = video_url_or_id.split("youtu.be/")[1].split("?")[0]
        return video_id_fallback # Return ID as fallback title

def sanitize_filename(filename):
    """
    Sanitizes a string to be a valid filename.
    Removes or replaces invalid characters.
    """
    if not filename:
        return "untitled"
    # Replace problematic characters with underscores
    valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    sanitized_name = ''.join(c if c in valid_chars else '_' for c in filename)
    # Replace multiple underscores with a single one
    sanitized_name = re.sub(r'__+', '_', sanitized_name)
    # Remove leading/trailing underscores or spaces
    sanitized_name = sanitized_name.strip('_ ')
    # Limit length (optional, but good practice)
    max_len = 100 
    if len(sanitized_name) > max_len:
        sanitized_name = sanitized_name[:max_len].rsplit('_', 1)[0] # try to cut at a separator
        if not sanitized_name : # if rsplit removed everything
             sanitized_name = filename[:max_len//2] # fallback to a hard cut of original
    if not sanitized_name: # If all else fails
        return "untitled_video"
    return sanitized_name

def format_time(seconds_val):
    """Converts seconds to SRT time format (HH:MM:SS,ms)"""
    # Separate integer and fractional parts of seconds
    integer_seconds = int(seconds_val)
    fractional_seconds = seconds_val - integer_seconds

    # Calculate milliseconds, round, and handle carry-over to seconds
    millis = int(round(fractional_seconds * 1000))

    if millis >= 1000:
        integer_seconds += millis // 1000  # Add carried-over second(s)
        millis %= 1000                     # Remainder is the new milliseconds

    # Calculate HH, MM, SS from the (potentially adjusted) integer_seconds
    hours = integer_seconds // 3600
    remainder_after_hours = integer_seconds % 3600
    minutes = remainder_after_hours // 60
    final_seconds_part = remainder_after_hours % 60
    
    return f"{hours:02d}:{minutes:02d}:{final_seconds_part:02d},{millis:03d}"

def preprocess_and_merge_segments(raw_transcript_data, logger=None):
    """
    Merges raw transcript segments based on duration, length, and punctuation.
    Also cleans up newlines within segments.
    """
    logger_to_use = logger if logger else global_logger
    if not raw_transcript_data:
        logger_to_use.info("preprocess_and_merge_segments: Received empty raw_transcript_data. Returning empty list.")
        return []
    logger_to_use.info(f"preprocess_and_merge_segments: Starting with {len(raw_transcript_data)} raw entries.")

    # --- Pass 1: Initial Cleaning from API data --- 
    initial_cleaned_entries = []
    for entry_obj in raw_transcript_data: # entry_obj is FetchedTranscriptSnippet here
        cleaned_text = entry_obj.text.replace('\n', ' ').strip()
        if cleaned_text:
            initial_cleaned_entries.append({
                'text': cleaned_text,
                'start': entry_obj.start,    
                'duration': entry_obj.duration,
                'original_text_length': len(cleaned_text) # Store original length for proportional duration later
            })

    if not initial_cleaned_entries:
        return []
    
    # --- Helper function to check for actual sentence ending (handles decimals and common host/file patterns) ---
    def _is_actual_sentence_end_char(text_segment, char_index_in_segment, sentence_end_punctuations_config):
        char_to_check = text_segment[char_index_in_segment]

        if char_to_check == '.':
            # Rule 1: Decimal point detection (e.g., "2.5", ".5")
            is_prev_digit = (char_index_in_segment > 0 and text_segment[char_index_in_segment - 1].isdigit())
            is_next_digit = (char_index_in_segment < len(text_segment) - 1 and text_segment[char_index_in_segment + 1].isdigit())
            
            if is_prev_digit and is_next_digit: # e.g., "2.5"
                return False 
            if not is_prev_digit and is_next_digit: # e.g., ".5"
                if not (char_index_in_segment > 0 and text_segment[char_index_in_segment - 1] == '.'):
                    return False 

            prev_char_is_alnum = (char_index_in_segment > 0 and text_segment[char_index_in_segment - 1].isalnum())
            next_char_is_alnum = (char_index_in_segment < len(text_segment) - 1 and text_segment[char_index_in_segment + 1].isalnum())

            if prev_char_is_alnum and next_char_is_alnum:
                idx_after_alnum_dot_alnum = char_index_in_segment + 2 
                
                if idx_after_alnum_dot_alnum < len(text_segment) -1:
                    if text_segment[idx_after_alnum_dot_alnum] == ' ' and text_segment[idx_after_alnum_dot_alnum + 1].isupper():
                        return True 
                    else:
                        return False 
                else:
                    return False 

            return True
            
        elif char_to_check in sentence_end_punctuations_config: 
            return True
            
        return False
    # --- End of Helper --- 

    logger_to_use.debug(f"\n--- Starting Pre-segmentation and Merging Logic ---")
    logger_to_use.debug(f"Pass 1: Initial cleaning complete. {len(initial_cleaned_entries)} entries.")

    # --- Pass 2: Pre-splitting entries with internal punctuations --- 
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
            # Find the *first* sentence-ending punctuation from the start of text_to_process
            for punc_char_idx, char_in_text in enumerate(text_to_process):
                # Use the helper function here
                if _is_actual_sentence_end_char(text_to_process, punc_char_idx, config.SENTENCE_END_PUNCTUATIONS):
                    found_punc_at = punc_char_idx
                    break
            
            if found_punc_at != -1:
                sub_segment_text = text_to_process[:found_punc_at + 1]
                len_sub_segment = len(sub_segment_text)
                # Estimate duration proportionally to the original segment's duration
                # This is an estimate; final segment duration is recalculated later.
                estimated_duration = (len_sub_segment / original_text_len) * original_duration
                
                fine_grained_entries.append({
                    'text': sub_segment_text,
                    'start': current_sub_segment_start_time,
                    'duration': estimated_duration
                })
                current_sub_segment_start_time += estimated_duration
                text_to_process = text_to_process[found_punc_at + 1:].lstrip() # Process remainder
            else:
                # No more sentence-ending punctuations in the remainder of this original entry
                if text_to_process: # If there's any text left
                    remaining_len = len(text_to_process)
                    # Estimate duration for the remainder
                    estimated_duration = (remaining_len / original_text_len) * original_duration
                    # Ensure total duration of pieces doesn't wildly exceed original from this one entry
                    # This is tricky; a simpler approach is to just use proportional as well, or remaining original duration. 
                    # For now, proportional. The main merge logic re-calculates final segment duration.

                    fine_grained_entries.append({
                        'text': text_to_process,
                        'start': current_sub_segment_start_time,
                        'duration': estimated_duration 
                    })
                text_to_process = "" # All processed for this original entry
        
    logger_to_use.debug(f"Pass 2: Pre-splitting complete. {len(fine_grained_entries)} fine-grained entries generated.")

    # --- Pass 3: Merge fine-grained entries based ONLY on SENTENCE_END_PUNCTUATIONS at the very end --- 
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
            
            final_merged_segments.append({
                'text': current_segment_text,
                'start': segment_start_time,
                'duration': segment_duration
            })
            current_accumulated_fine_grained_entries = [] 
        else:
            pass # Explicitly passing if no action needed

    if current_accumulated_fine_grained_entries:
        logger_to_use.debug(f"\n  Pass 3 - Finalizing remaining accumulated fine-grained entries as the last segment.")
        segment_text = " ".join(e['text'] for e in current_accumulated_fine_grained_entries)
        segment_start_time = current_accumulated_fine_grained_entries[0]['start']
        segment_end_time = current_accumulated_fine_grained_entries[-1]['start'] + current_accumulated_fine_grained_entries[-1]['duration']
        segment_duration = segment_end_time - segment_start_time
        
        final_merged_segments.append({
            'text': segment_text,
            'start': segment_start_time,
            'duration': segment_duration
        })
    
    logger_to_use.info(f"--- Pre-segmentation and Merging Logic Finished. Total segments: {len(final_merged_segments)} ---")
    return final_merged_segments

def transcript_to_markdown(transcript_data, lang_code, source_type, video_id, logger=None):
    """Converts transcript data (list of dicts) to Markdown with timestamps."""
    logger_to_use = logger if logger else global_logger
    md_content = [f"# YouTube Video Transcript: {video_id}\n"]
    md_content.append(f"**Source Language:** {lang_code}")
    md_content.append(f"**Source Type:** {source_type} subtitles\n")
    
    for entry in transcript_data:
        start_time = format_time(entry['start'])
        # Duration might not always be perfectly accurate for end time with some APIs,
        # but youtube-transcript-api provides start and duration.
        end_time = format_time(entry['start'] + entry['duration'])
        text = entry['text']
        md_content.append(f"## {start_time} --> {end_time}\n{text}\n")
    return "\n".join(md_content)

def _parse_time_part(time_str_part):
    """Helper to parse a single time string like HH:MM:SS,ms or MM:SS,ms etc."""
    h, m, s, ms = 0, 0, 0, 0
    try:
        main_and_ms = time_str_part.split(',')
        if len(main_and_ms) != 2:
            # print(f"DEBUG: _parse_time_part: Invalid main/ms split for '{time_str_part}'")
            return None
        ms = int(main_and_ms[1])
        
        hms_parts = main_and_ms[0].split(':')
        if len(hms_parts) == 3: # HH:MM:SS
            h = int(hms_parts[0])
            m = int(hms_parts[1])
            s = int(hms_parts[2])
        elif len(hms_parts) == 2: # MM:SS
            m = int(hms_parts[0])
            s = int(hms_parts[1])
        elif len(hms_parts) == 1: # SS
            s = int(hms_parts[0])
        else:
            # print(f"DEBUG: _parse_time_part: Invalid h/m/s part count for '{main_and_ms[0]}'")
            return None
        
        # Basic validation for parsed values (optional, but good practice)
        if not (0 <= h <= 99 and 0 <= m <= 59 and 0 <= s <= 59 and 0 <= ms <= 999):
            # print(f"DEBUG: _parse_time_part: Parsed time values out of range for '{time_str_part}'")
            return None
            
        return h, m, s, ms
    except ValueError:
        # print(f"DEBUG: _parse_time_part: ValueError during int conversion for '{time_str_part}'")
        return None
    except Exception as e:
        # print(f"DEBUG: _parse_time_part: Generic error for '{time_str_part}': {e}")
        return None

def _normalize_timestamp_id(id_str):
    """Normalizes a timestamp ID string like 'HH:MM:SS,ms --> HH:MM:SS,ms' to a consistent format."""
    if not id_str or not isinstance(id_str, str):
        return f"ERROR_NORM_INVALID_INPUT_TYPE__{id_str}"
    
    id_str_stripped = id_str.strip()
    parts = id_str_stripped.split("-->")
    if len(parts) != 2:
        return f"ERROR_NORM_NO_ARROW_SEPARATOR__{id_str_stripped}"
        
    start_parsed = _parse_time_part(parts[0].strip())
    end_parsed = _parse_time_part(parts[1].strip())
    
    if not start_parsed:
        return f"ERROR_NORM_START_PARSE_FAILED__{id_str_stripped}"
    if not end_parsed:
        return f"ERROR_NORM_END_PARSE_FAILED__{id_str_stripped}"
        
    sh, sm, ss, sms = start_parsed
    eh, em, es, ems = end_parsed
    
    return (f"{sh:02d}:{sm:02d}:{ss:02d},{sms:03d} --> "
            f"{eh:02d}:{em:02d}:{es:02d},{ems:03d}")

def translate_text_segments(transcript_data_processed, 
                            source_lang_code, 
                            target_lang="zh-CN",
                            video_specific_output_path=None,
                            logger=None,
                            global_logger_for_console=None):
    """
    Translates a list of processed transcript segments (with text, start, duration)
    using the configured LLM provider, via batched JSON objects.
    """
    logger_to_use = logger if logger else global_logger
    # Use a local reference to global_logger_for_console or a dummy logger if None
    console_logger = global_logger_for_console if global_logger_for_console else logging.getLogger("DummyConsole")
    if global_logger_for_console is None : # Setup dummy logger to do nothing if not passed
        console_logger.addHandler(logging.NullHandler())

    logger_to_use.info(f"--- LLM Provider from config: {config.LLM_PROVIDER} ---")
    
    if not transcript_data_processed:
        logger_to_use.info("No segments to translate.")
        return []

    json_segments_to_translate = []
    for item in transcript_data_processed:
        original_raw_id = format_time(item['start']) + " --> " + format_time(item['start'] + item['duration'])
        json_segments_to_translate.append({
            "id": original_raw_id, 
            "text_en": item['text'] 
        })

    translations_map = {} 

    raw_llm_responses_log_file = None
    if video_specific_output_path:
        log_filename = f"llm_raw_responses_{target_lang.lower().replace('-', '_')}.jsonl"
        raw_llm_responses_log_file = os.path.join(video_specific_output_path, log_filename)
        # Ensure the directory exists (it should be created by main, but good to be safe)
        os.makedirs(video_specific_output_path, exist_ok=True)
        logger_to_use.info(f"Raw LLM API responses will be logged to: {raw_llm_responses_log_file}")

    if config.LLM_PROVIDER == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger_to_use.error("GEMINI_API_KEY not found. Translation will be skipped.")
            return [f"[SKIPPED_NO_KEY] {s['text_en']}" for s in json_segments_to_translate]

        try:
            genai.configure(api_key=api_key)
            generation_config = genai.types.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.0
            )
            model = genai.GenerativeModel(
                config.LLM_MODEL_GEMINI,
                generation_config=generation_config
            ) 
            logger_to_use.info(f"Using Gemini model: {config.LLM_MODEL_GEMINI} for translation from '{source_lang_code}' to '{target_lang}' (JSON mode, temperature=0.0)." )
            logger_to_use.info(f"Target prompt tokens per batch: {config.TARGET_PROMPT_TOKENS_PER_BATCH}, Max segments per batch: {config.MAX_SEGMENTS_PER_GEMINI_JSON_BATCH}")

            output_text_field_key = f"text_{target_lang.lower().replace('-', '_')}" 

            def _construct_prompt_string_for_batch(segments_list_for_payload, src_lang, tgt_lang, out_text_key, use_simplified_ids=False):
                if use_simplified_ids:
                    example_id_format = "seg_N (e.g., 'seg_0', 'seg_1', ... 'seg_99')"
                    id_preservation_instruction = (
                        f"CRITICAL ID PRESERVATION: The 'id' field is a simplified segment identifier (format: {example_id_format}). "
                        f"You MUST return this 'id' string EXACTLY as it was provided in the input for each segment. DO NOT alter or omit the 'id'. "
                        "The 'id' ensures segments are correctly mapped back after translation."
                    )
                else: # Original behavior
                    example_id_format = "HH:MM:SS,mmm --> HH:MM:SS,mmm (e.g., '00:01:23,456 --> 00:01:25,789')"
                    id_preservation_instruction = (
                        f"CRITICAL ID PRESERVATION: The 'id' field is a precise timestamp string (format: {example_id_format}). "
                        f"You MUST return this 'id' string EXACTLY as it was provided in the input for each segment. DO NOT alter, reformat, or change any part of the 'id' string, including numbers, colons, commas, spaces, or the '-->' separator. "
                    )
                
                instruction_text_for_payload = (
                    f"Objective: Translate the 'text_en' field of each segment object from {src_lang} to {tgt_lang}. "
                    f"Output Format: A JSON object with a single key 'translated_segments'. This key's value must be an array of objects. "
                    f"Each object in this output array must retain the original 'id' from the input segment and include the translated text in a new field named '{out_text_key}'."
                    f"{id_preservation_instruction} " # Use the chosen instruction
                    "The segments are ordered chronologically and provide context for each other. "
                    "Ensure the number of objects in the 'translated_segments' array exactly matches the number of input segments."
                )
                json_payload_for_prompt = {
                    "source_language": src_lang,
                    "target_language": tgt_lang,
                    "instructions": instruction_text_for_payload, 
                    "segments": segments_list_for_payload
                }
                return (
                    f"Your task is to process the following JSON request. The 'instructions' field within the JSON details the primary objective: "
                    f"to translate text segments from {src_lang} to {tgt_lang}. "
                    "You MUST return a single, valid JSON object that strictly follows the output structure described in the 'instructions' field of the request. "
                    "Pay EXTREME ATTENTION to the ID PRESERVATION requirement detailed in the instructions: the 'id' field for each segment in your response MUST be an IDENTICAL, UNCHANGED copy of the 'id' field from the input segment.\\n\\n"
                    f"JSON Request:\\n```json\\n{json.dumps(json_payload_for_prompt, indent=2, ensure_ascii=False)}\\n```"
                )

            all_batches = []
            current_batch_input_segments = [] 

            # Flag to control the ID strategy
            USE_SIMPLIFIED_IDS_EXPERIMENTAL = True
            if USE_SIMPLIFIED_IDS_EXPERIMENTAL:
                logger_to_use.info("Using SIMPLIFIED IDs (seg_N) for translation batches.")

            for seg_obj in json_segments_to_translate:
                potential_segments_for_this_batch = current_batch_input_segments + [seg_obj]
                
                # Token counting prompt generation will use original IDs for now.
                # This is a slight overestimation if simplified IDs are shorter, which is generally safe.
                # To be extremely precise, this prompt construction would also need to be aware of USE_SIMPLIFIED_IDS_EXPERIMENTAL
                # and create a temporary list with simplified IDs for counting if that flag is True.
                # For now, we keep it as is, as the impact is likely small.
                prompt_if_added = _construct_prompt_string_for_batch(
                    potential_segments_for_this_batch, 
                    source_lang_code, 
                    target_lang, 
                    output_text_field_key,
                    use_simplified_ids=False # For token counting, assume original ID format complexity
                )
                try:
                    num_tokens_if_added = model.count_tokens(prompt_if_added).total_tokens
                except Exception as e_count:
                    logger_to_use.warning(f"Token counting failed for a potential batch. Error: {e_count}. Proceeding with segment count only for this decision.", exc_info=True)
                    if len(potential_segments_for_this_batch) > 10: 
                         num_tokens_if_added = config.TARGET_PROMPT_TOKENS_PER_BATCH + 1 
                    else:
                         num_tokens_if_added = 1 

                if current_batch_input_segments and \
                   (num_tokens_if_added > config.TARGET_PROMPT_TOKENS_PER_BATCH or \
                    len(potential_segments_for_this_batch) > config.MAX_SEGMENTS_PER_GEMINI_JSON_BATCH):
                    
                    all_batches.append(list(current_batch_input_segments))
                    current_batch_input_segments = [seg_obj]
                else:
                    current_batch_input_segments.append(seg_obj)
            
            if current_batch_input_segments:
                all_batches.append(list(current_batch_input_segments))

            # logger_to_use.info(f"Prepared {len(json_segments_to_translate)} segments into {len(all_batches)} batches for translation based on token/segment limits.")
            if all_batches:
                console_logger.info(f"Prepared {len(all_batches)} batches for translation.") # Console message for batch count
            else:
                console_logger.info("No batches to translate.") 

            for batch_idx, actual_batch_segments in enumerate(all_batches):
                if not actual_batch_segments:
                    continue
                # logger_to_use.info(f"Translating Batch {batch_idx + 1}/{len(all_batches)} with {len(actual_batch_segments)} segments...") # File log only due to propagate=False
                console_logger.info(f"Translating batch {batch_idx + 1}/{len(all_batches)}...") # Console message for batch progress
                
                segments_for_payload_this_batch = []
                if USE_SIMPLIFIED_IDS_EXPERIMENTAL:
                    for i, seg_data in enumerate(actual_batch_segments):
                        segments_for_payload_this_batch.append({
                            "id": f"seg_{i}",
                            "text_en": seg_data["text_en"]
                        })
                else:
                    segments_for_payload_this_batch = actual_batch_segments # Use as is

                prompt_to_send = _construct_prompt_string_for_batch(
                    segments_for_payload_this_batch, 
                    source_lang_code, 
                    target_lang, 
                    output_text_field_key,
                    use_simplified_ids=USE_SIMPLIFIED_IDS_EXPERIMENTAL # Pass the flag
                )
                
                try:
                    response = model.generate_content(prompt_to_send)
                    
                    # Log the raw response text immediately after receiving it
                    if raw_llm_responses_log_file:
                        try:
                            # Ensure response.text exists and is not empty before writing
                            raw_text_to_log = response.text if hasattr(response, 'text') and response.text else None
                            if raw_text_to_log:
                                with open(raw_llm_responses_log_file, 'a', encoding='utf-8') as f_raw:
                                    f_raw.write(raw_text_to_log + '\n')
                            else:
                                # Log a placeholder if response.text is empty or missing, but response object exists
                                with open(raw_llm_responses_log_file, 'a', encoding='utf-8') as f_raw:
                                    placeholder_log = {"batch_index": batch_idx + 1, "status": "EMPTY_RESPONSE_TEXT", "has_parts": bool(response.parts if hasattr(response, 'parts') else False)}
                                    f_raw.write(json.dumps(placeholder_log) + '\n')
                        except Exception as e_log:
                            logger_to_use.warning(f"Could not write raw LLM response for batch {batch_idx + 1} to log file: {e_log}", exc_info=True)

                    if not response.parts:
                         logger_to_use.warning(f"Gemini response for batch {batch_idx+1} has no parts. Using originals.")
                         for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[NO_TRANSLATION_EMPTY_RESPONSE] {seg['text_en']}"
                         continue
                    try:
                        translated_json_str = response.text 
                        # --- Attempt to fix extra trailing curly brace --- 
                        cleaned_json_str = translated_json_str.strip()
                        if cleaned_json_str.startswith('{') and cleaned_json_str.endswith('}'):
                            # Count braces to see if there is an imbalance favouring closing braces at the very end
                            if cleaned_json_str.count('}') == cleaned_json_str.count('{') + 1:
                                logger_to_use.warning("Attempting to fix a potential extra trailing curly brace in JSON response.")
                                # Remove the last character if it's a brace and counts are off by one
                                cleaned_json_str = cleaned_json_str[:-1]
                        # --- End of fix attempt ---
                        
                        translated_data = json.loads(cleaned_json_str) # Use the cleaned string
                        if 'translated_segments' not in translated_data or not isinstance(translated_data['translated_segments'], list):
                            logger_to_use.warning(f"  Warning: 'translated_segments' array not found/invalid in response for batch {batch_idx+1}. Raw: {cleaned_json_str[:200] if cleaned_json_str else 'EMPTY'}... Using originals.")
                            for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[NO_TRANSLATION_BAD_JSON_STRUCTURE] {seg['text_en']}"
                            continue
                        translated_batch_segments_from_response = translated_data['translated_segments']
                        if len(translated_batch_segments_from_response) != len(actual_batch_segments):
                            logger_to_use.warning(f"Mismatch in translated segments for batch {batch_idx+1} (expected {len(actual_batch_segments)}, got {len(translated_batch_segments_from_response)}). Using originals for this batch.")
                            for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[NO_TRANSLATION_SEG_COUNT_MISMATCH] {seg['text_en']}"
                            continue
                        
                        # Revised loop for processing translated segments
                        for i, translated_seg_item in enumerate(translated_batch_segments_from_response):
                            original_complex_id_from_actual_batch = actual_batch_segments[i]["id"]
                            text_en_from_actual_batch = actual_batch_segments[i]["text_en"]
                            
                            map_key = _normalize_timestamp_id(original_complex_id_from_actual_batch)

                            if USE_SIMPLIFIED_IDS_EXPERIMENTAL:
                                expected_simple_id = f"seg_{i}"
                                model_returned_simple_id = translated_seg_item.get("id")

                                if not model_returned_simple_id:
                                    logger_to_use.warning(f"ID missing in translated segment. Batch {batch_idx+1}. Expected simple ID '{expected_simple_id}' (for original: '{original_complex_id_from_actual_batch}'). Skipping.")
                                    translations_map[map_key] = f"[NO_TRANSLATION_ID_MISSING_IN_RESPONSE] {text_en_from_actual_batch}"
                                    continue
                                if model_returned_simple_id != expected_simple_id:
                                    logger_to_use.warning(f"Simple ID mismatch from model. Batch {batch_idx+1}.\n     Expected: '{expected_simple_id}' (for original: '{original_complex_id_from_actual_batch}')\n     Model Returned: '{model_returned_simple_id}'. Skipping.")
                                    translations_map[map_key] = f"[NO_TRANSLATION_SIMPLE_ID_MISMATCH] {text_en_from_actual_batch}"
                                    continue
                                # If we are here, simple ID from model is correct and matches expected.
                            else: # Original (complex) ID logic
                                translated_id_from_model = translated_seg_item.get("id")
                                if not translated_id_from_model:
                                    logger_to_use.warning(f"ID missing in translated segment for original ID '{original_complex_id_from_actual_batch}' in batch {batch_idx+1}. Skipping.")
                                    translations_map[map_key] = f"[NO_TRANSLATION_ID_MISSING_IN_RESPONSE] {text_en_from_actual_batch}"
                                    continue

                                normalized_translated_id = _normalize_timestamp_id(translated_id_from_model)
                                
                                if map_key != normalized_translated_id: # map_key is already the normalized original complex ID
                                    logger_to_use.warning(f"ID mismatch after attempting to normalize model response. Batch {batch_idx+1}.\n     Original (Normalized): '{map_key}'\n     Model Output Raw : '{translated_id_from_model}'\n     Model OutputNormd: '{normalized_translated_id}'. Skipping segment.")
                                    translations_map[map_key] = f"[NO_TRANSLATION_ID_MISMATCH_NORM_FAILED_OR_VALUE_DIFF] {text_en_from_actual_batch}"
                                    continue
                            
                            # Common logic for checking text field and storing translation
                            if output_text_field_key not in translated_seg_item:
                                id_for_error_msg = f"seg_{i}" if USE_SIMPLIFIED_IDS_EXPERIMENTAL else original_complex_id_from_actual_batch
                                logger_to_use.warning(f"Expected field '{output_text_field_key}' not found for ID '{id_for_error_msg}' in batch {batch_idx+1}. Using original.")
                                translations_map[map_key] = f"[NO_TRANSLATION_MISSING_TEXT_FIELD] {text_en_from_actual_batch}"
                                continue
                            
                            translations_map[map_key] = translated_seg_item[output_text_field_key]
                        logger_to_use.info(f"Batch {batch_idx + 1} translated successfully.")
                    except json.JSONDecodeError as e_json:
                        logger_to_use.error(f"  Error decoding JSON response from Gemini for batch {batch_idx+1}: {e_json}. Cleaned Raw Attempt: {(cleaned_json_str[:500] if cleaned_json_str else 'EMPTY_STRING_FOR_DECODE')}", exc_info=True)
                        for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[ERROR_JSON_DECODE] {seg['text_en']}"
                    except Exception as e_resp_proc:
                        logger_to_use.error(f"Error processing response from Gemini for batch {batch_idx+1}: {e_resp_proc}", exc_info=True)
                        for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[ERROR_RESP_PROCESSING] {seg['text_en']}"
                except Exception as e_api_call:
                    logger_to_use.error(f"An error occurred during Gemini API call for batch {batch_idx+1}: {e_api_call}. This might be due to the batch size exceeding model limits even after token counting.", exc_info=True)
                    if raw_llm_responses_log_file:
                        try:
                            with open(raw_llm_responses_log_file, 'a', encoding='utf-8') as f_raw:
                                error_info = {
                                    "batch_index": batch_idx + 1, 
                                    "status": "API_CALL_ERROR", 
                                    "error_message": str(e_api_call)
                                }
                                f_raw.write(json.dumps(error_info) + '\n')
                        except Exception as e_log_err:
                            logger_to_use.warning(f"Could not write API call error to log file for batch {batch_idx + 1}: {e_log_err}", exc_info=True)
                    for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[ERROR_API_CALL] {seg['text_en']}"
                
                delay_seconds = getattr(config, 'LLM_REQUEST_DELAY', 0)
                if delay_seconds > 0 and batch_idx < len(all_batches) - 1 :
                    logger_to_use.info(f"Waiting for {delay_seconds}s before next batch...")
                    time.sleep(delay_seconds)

            final_translated_texts = []
            for seg_obj_orig in json_segments_to_translate:
                # Normalize the ID from the original segment list before looking up in the map
                normalized_key_to_lookup = _normalize_timestamp_id(seg_obj_orig["id"])
                
                # Prepare a more informative default message if translation is not found
                default_not_found_message = (
                    f"[TRANSLATION_NOT_FOUND_FOR_ID:{seg_obj_orig['id']}] "
                    f"[NORMALIZED_AS:{normalized_key_to_lookup}] "
                    f"{seg_obj_orig['text_en']}"
                )

                final_translated_texts.append(
                    translations_map.get(normalized_key_to_lookup, default_not_found_message)
                )
            
            if len(final_translated_texts) != len(json_segments_to_translate):
                 logger_to_use.critical(f"Final translated segment count ({len(final_translated_texts)}) MISMATCHES original segment count ({len(json_segments_to_translate)}).")
            
            logger_to_use.info(f"--- Gemini JSON translation processing complete. ---")
            return final_translated_texts
        except Exception as e:
            logger_to_use.critical(f"A critical error occurred during Gemini JSON setup or outer processing loop: {e}", exc_info=True)
            console_logger.error(f"A critical error occurred during translation setup: {e}") # Also to console
            # Log this critical error to the .jsonl file as well if possible
            if raw_llm_responses_log_file:
                try:
                    with open(raw_llm_responses_log_file, 'a', encoding='utf-8') as f_raw:
                        error_info = {
                            "batch_index": batch_idx + 1, 
                            "status": "CRITICAL_ERROR_TRANSLATING", 
                            "error_message": str(e)
                        }
                        f_raw.write(json.dumps(error_info) + '\n')
                except Exception as e_log_crit:
                    logger_to_use.warning(f"Could not write critical outer processing error to log file: {e_log_crit}", exc_info=True)
            return [f"[CRITICAL_ERROR_TRANSLATING] {s['text_en']}" for s in json_segments_to_translate]
    else:
        logger_to_use.warning(f"Unsupported or misconfigured LLM_PROVIDER: {config.LLM_PROVIDER}. Using simulated translation.")
        simulated_translated_segments = []
        if raw_llm_responses_log_file: # Log simulation info
            try:
                with open(raw_llm_responses_log_file, 'a', encoding='utf-8') as f_raw:
                    error_info = {
                        "batch_index": batch_idx + 1, 
                        "status": "SIMULATED_TRANSLATION", 
                        "error_message": "Simulated translation used as no valid LLM_PROVIDER configured"
                    }
                    f_raw.write(json.dumps(error_info) + '\n')
            except Exception as e_log_sim:
                logger_to_use.warning(f"Could not write simulation info to log file: {e_log_sim}", exc_info=True)

        for seg_obj in json_segments_to_translate: 
            translated_text = f"[译] {seg_obj['text_en']}" 
            simulated_translated_segments.append(translated_text)
        logger_to_use.info("--- Simulated translation complete ---")
        return simulated_translated_segments

def reconstruct_translated_srt(original_transcript_data, translated_texts, logger=None):
    """Reconstructs SRT from original timestamps and translated texts."""
    logger_to_use = logger if logger else global_logger
    if len(original_transcript_data) != len(translated_texts):
        logger_to_use.warning("Mismatch between original transcript entries and translated texts count in reconstruct_translated_srt.")
        # Pad or truncate translated_texts if necessary, or handle error more gracefully
        # For now, we'll proceed but this might lead to incorrect SRT.
        # A robust solution would be to ensure the translation function returns a list of the same length.
    
    srt_content = []
    min_len = min(len(original_transcript_data), len(translated_texts))
    for i in range(min_len):
        entry = original_transcript_data[i]
        start_time = format_time(entry['start'])
        end_time = format_time(entry['start'] + entry['duration'])
        text = translated_texts[i]
        srt_content.append(f"{i+1}\n{start_time} --> {end_time}\n{text}\n")
    return "\n".join(srt_content)

def reconstruct_translated_markdown(original_transcript_data, translated_texts, original_lang, source_type, target_lang="zh-CN", video_id="", logger=None):
    """Reconstructs Markdown from original timestamps (list of dicts) and translated texts."""
    logger_to_use = logger if logger else global_logger
    if len(original_transcript_data) != len(translated_texts):
        logger_to_use.warning("Mismatch between original transcript entries and translated texts count during MD reconstruction.")

    md_content = [f"# YouTube Video Translation: {video_id}\n"]
    md_content.append(f"**Original Language:** {original_lang} ({source_type})")
    md_content.append(f"**Translated Language:** {target_lang}\n")
    
    min_len = min(len(original_transcript_data), len(translated_texts))
    for i in range(min_len):
        entry = original_transcript_data[i]
        start_time = format_time(entry['start'])
        end_time = format_time(entry['start'] + entry['duration'])
        text = translated_texts[i]
        md_content.append(f"## {start_time} --> {end_time}\n{text}\n")
    return "\n".join(md_content)

def save_to_file(content, filename, logger=None):
    """Saves content to a file."""
    logger_to_use = logger if logger else global_logger
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        logger_to_use.info(f"Successfully saved to {filename}")
    except IOError as e:
        logger_to_use.error(f"Error saving file {filename}: {e}", exc_info=True)

def get_video_id(url_or_id):
    if "youtube.com/watch?v=" in url_or_id:
        return url_or_id.split("watch?v=")[1].split("&")[0]
    elif "youtu.be/" in url_or_id:
        return url_or_id.split("youtu.be/")[1].split("?")[0]
    return url_or_id # Assume it's already an ID if no common URL patterns match

def main():
    # Determine the script's directory and the desired default output directory
    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path)
    project_parent_dir = os.path.dirname(script_dir)
    default_output_folder_name = "output_translations"
    default_output_dir_path = os.path.join(project_parent_dir, default_output_folder_name)

    parser = argparse.ArgumentParser(description="Translate YouTube video subtitles.")
    parser.add_argument("video_url_or_id", help="The URL or ID of the YouTube video.")
    parser.add_argument("--output_basename", help="Basename for output files (e.g., 'my_video'). Overrides fetched video title for naming.", default=None)
    parser.add_argument("--target_lang", help="Target language for translation (e.g., 'zh-CN', 'zh-Hans').", default=config.DEFAULT_TARGET_TRANSLATION_LANGUAGE)
    parser.add_argument("--output_dir", help=f"Base directory for all output. Default: Creates '{default_output_folder_name}\' alongside the project directory.", default=default_output_dir_path)
    parser.add_argument("--log_level", help="Set the logging level for the video-specific log file (DEBUG, INFO, WARNING, ERROR, CRITICAL)", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])

    args = parser.parse_args()
    load_dotenv()

    # This basicConfig will affect the root logger, sending messages to console.
    # We will create a more specific file logger for the video task later.
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - CONSOLE - %(message)s', force=True)

    print(f"--- YouTube Translator script started for input: {args.video_url_or_id} ---") # Changed from logging.info
    # These initial logging.info messages will now only go to console if their level is WARNING or higher, 
    # or if a specific handler (like global_logger's) is configured for INFO and they use that logger.
    # They will be captured by video_logger later for the file log.
    # logging.info(f"Target language: {args.target_lang}, Requested log level: {args.log_level}") # Example: will not show on console
    # logging.info(f"Base output directory for all videos: {args.output_dir}") # Example: will not show on console

    video_id_for_transcript = get_video_id(args.video_url_or_id)
    # logging.info(f"Processing Video ID: {video_id_for_transcript}") # Example: will not show on console

    # Get video title (using the existing function, which now might use pytubefix)
    # The first call to get_youtube_video_title uses global_logger by default if logger is None
    # This ensures the initial title fetching attempt is logged to console via global_logger.
    video_title = get_youtube_video_title(args.video_url_or_id, logger=None) 
    sanitized_title = sanitize_filename(video_title)

    specific_output_dir_name = sanitized_title
    if video_title == video_id_for_transcript: # title fetch likely failed, used ID as fallback
        logging.warning(f"Could not fetch a distinct video title; using video ID '{video_id_for_transcript}' for directory and filenames.")

    file_basename_prefix = sanitize_filename(args.output_basename) if args.output_basename else specific_output_dir_name

    video_output_path = os.path.join(args.output_dir, specific_output_dir_name)
    try:
        os.makedirs(video_output_path, exist_ok=True)
        logging.info(f"Video-specific output directory: {video_output_path}")
    except OSError as e_mkdir:
        logging.critical(f"CRITICAL: Could not create video-specific output directory: {video_output_path}. Error: {e_mkdir}", exc_info=True)
        return # Critical error, cannot proceed

    # --- Setup video-specific file logger ---
    log_file_name_base = sanitized_title if sanitized_title and sanitized_title != video_id_for_transcript else video_id_for_transcript
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_name = f"{sanitize_filename(log_file_name_base)}_{timestamp_str}.log"
    log_file_full_path = os.path.join(video_output_path, log_file_name)

    numeric_log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    # Create a unique logger name for each video task to avoid conflicts if script is run multiple times
    video_logger_name = f"VideoTask.{sanitize_filename(log_file_name_base)}.{timestamp_str}"
    video_logger = setup_video_logger(video_logger_name, log_file_full_path, level=numeric_log_level)
    
    video_logger.info(f"Video-specific logger initialized. Logging to file: {log_file_full_path}")
    video_logger.info(f"Processing Video URL: {args.video_url_or_id}")
    video_logger.info(f"Video ID for transcript: {video_id_for_transcript}")
    video_logger.info(f"Fetched video title (used for naming): '{video_title}'")
    video_logger.info(f"Target language for translation: {args.target_lang}")
    video_logger.info(f"Output files will be prefixed with: '{file_basename_prefix}'")
    # --- End of Video Logger Setup ---
    
    # Now, subsequent operations should use video_logger
    raw_transcript_data, lang_code, source_type = get_youtube_transcript(video_id_for_transcript, logger=video_logger)

    if not raw_transcript_data:
        video_logger.error("Could not retrieve transcript. Exiting process for this video.") # Error will still show on console
        return
    # video_logger.info(f"Successfully fetched raw transcript in '{lang_code}' ({source_type}). Original segment count: {len(raw_transcript_data)}.")
    global_logger.info(f"Successfully fetched {source_type} transcript in '{lang_code}'.") # Console message
    
    # video_logger.info("Starting preprocessing and merging of transcript segments...") # File log only due to propagate=False
    merged_transcript_data = preprocess_and_merge_segments(raw_transcript_data, logger=video_logger)

    if not merged_transcript_data:
        video_logger.error("Transcript data is empty after preprocessing and merging. Exiting process for this video.")
        return
    # video_logger.info(f"Preprocessing complete. Merged into {len(merged_transcript_data)} segments.")
    global_logger.info(f"Preprocessing complete. Merged into {len(merged_transcript_data)} segments.") # Console message
    transcript_data_for_processing = merged_transcript_data
    
    original_md_filename = os.path.join(video_output_path, f"{file_basename_prefix}_original_merged_{lang_code}.md")
    original_md = transcript_to_markdown(transcript_data_for_processing, lang_code, source_type, video_id_for_transcript, logger=video_logger)
    save_to_file(original_md, original_md_filename, logger=video_logger)
    
    # video_logger.info(f"Starting translation from '{lang_code}' to '{args.target_lang}' using JSON method...") # File log only
    global_logger.info(f"Starting translation from '{lang_code}' to '{args.target_lang}'...") # Console message
    translated_texts = translate_text_segments(
        transcript_data_for_processing, 
        lang_code,                      
        args.target_lang,
        video_output_path, # Pass the video_output_path here for logging raw LLM responses
        logger=video_logger,
        global_logger_for_console=global_logger # Pass global_logger for console updates
    )

    if not translated_texts :
        video_logger.error("Translation failed or returned no segments. Exiting process for this video.")
        return
    global_logger.info("Translation processing complete.") # Console message

    if len(translated_texts) != len(transcript_data_for_processing):
         video_logger.warning(f"Number of translated segments ({len(translated_texts)}) does not match original ({len(transcript_data_for_processing)}). Results might be incomplete or misaligned.")

    translated_md_filename = os.path.join(video_output_path, f"{file_basename_prefix}_translated_{args.target_lang}.md")
    translated_md_content = reconstruct_translated_markdown(transcript_data_for_processing, translated_texts, lang_code, source_type, args.target_lang, video_id_for_transcript, logger=video_logger)
    save_to_file(translated_md_content, translated_md_filename, logger=video_logger)

    translated_srt_filename = os.path.join(video_output_path, f"{file_basename_prefix}_translated_{args.target_lang}.srt")
    translated_srt_content = reconstruct_translated_srt(transcript_data_for_processing, translated_texts, logger=video_logger)
    save_to_file(translated_srt_content, translated_srt_filename, logger=video_logger)

    video_logger.info("All tasks completed for this video!")
    print(f"--- YouTube Translator script finished for input: {args.video_url_or_id} ---") # Changed from logging.info
    
    # The following print statements remain for direct console feedback in addition to logs.
    print("\nAll tasks completed!")
    print(f"Original transcript (MD): {original_md_filename}")
    print(f"Translated transcript (MD): {translated_md_filename}")
    print(f"Translated transcript (SRT): {translated_srt_filename}")
    raw_llm_log_expected_filename = os.path.join(video_output_path, f"llm_raw_responses_{args.target_lang.lower().replace('-', '_')}.jsonl")
    if os.path.exists(raw_llm_log_expected_filename):
        print(f"Raw LLM responses log: {raw_llm_log_expected_filename}")
    # Print path to the new video-specific log file
    if log_file_full_path and os.path.exists(log_file_full_path):
        print(f"Video processing log: {log_file_full_path}")

if __name__ == "__main__":
    main()