import re
import logging
import config

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

def merge_segments_intelligently(transcript_segments, logger=None):
    """
    Merges raw transcript segments based on duration, length, and intelligent punctuation analysis.
    This is a sophisticated method designed to handle messy, non-standard ASR outputs.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    if not transcript_segments:
        logger_to_use.info("merge_segments_intelligently: Received empty list. Returning empty list.")
        return []
    logger_to_use.debug(f"merge_segments_intelligently: Starting with {len(transcript_segments)} raw segments.")

    initial_cleaned_entries = []
    for entry_obj in transcript_segments:
        # Handle both dict and object access
        is_dict = isinstance(entry_obj, dict)
        text = entry_obj['text'] if is_dict else entry_obj.text
        start = entry_obj['start'] if is_dict else entry_obj.start
        
        cleaned_text = text.replace('\n', ' ').strip()
        if cleaned_text:
            # Ensure duration is present, calculating from 'end' if necessary
            if is_dict:
                if 'duration' not in entry_obj and 'end' in entry_obj:
                    duration = entry_obj['end'] - start
                else:
                    duration = entry_obj.get('duration', 0)
            else: # Is object
                duration = getattr(entry_obj, 'duration', 0)

            initial_cleaned_entries.append({
                'text': cleaned_text,
                'start': start,
                'duration': duration,
                'original_text_length': len(cleaned_text)
            })

    if not initial_cleaned_entries:
        return []
    
    logger_to_use.debug(f"\n--- Starting Intelligent Segment Merging ---")
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
                estimated_duration = (len_sub_segment / original_text_len) * original_duration if original_text_len > 0 else 0
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
                    estimated_duration = (remaining_len / original_text_len) * original_duration if original_text_len > 0 else 0
                    fine_grained_entries.append({
                        'text': text_to_process,
                        'start': current_sub_segment_start_time,
                        'duration': estimated_duration 
                    })
                text_to_process = ""
        
    logger_to_use.debug(f"Pass 2: Pre-splitting complete. {len(fine_grained_entries)} fine-grained entries generated.")

    logger_to_use.debug(f"\nPass 3: Merging fine-grained entries...")
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
        
        if segment_duration < 0:
            logger_to_use.warning(f"Negative duration detected ({segment_duration:.3f}s) for final segment. Correcting to 0. Text: '{segment_text}'")
            segment_duration = 0

        final_merged_segments.append({
            'text': segment_text,
            'start': segment_start_time,
            'duration': segment_duration
        })
    
    for seg in final_merged_segments:
        seg['end'] = seg['start'] + seg['duration']

    logger_to_use.debug(f"--- Intelligent Segment Merging Finished. Total segments: {len(final_merged_segments)} ---")
    return final_merged_segments

def load_and_merge_srt_segments(file_path, logger):
    """
    Loads segments from an SRT file and merges them intelligently
    to provide better context for translation.

    Args:
        file_path (Path): The path to the SRT file.
        logger: A logger instance for logging messages.

    Returns:
        A list of merged subtitle segments, or None if the file is empty.
    """
    from .srt_handler import srt_to_segments  # Local import to avoid circular dependency
    
    logger.info(f"Reading and formatting SRT file: {file_path}")
    raw_subtitle_segments = srt_to_segments(file_path)
    if not raw_subtitle_segments:
        logger.error("No segments found in the SRT file. Aborting.")
        return None
        
    logger.info(f"Loaded {len(raw_subtitle_segments)} raw segments from SRT file.")

    # Merge subtitles for better translation context using the new intelligent merger
    merged_segments = merge_segments_intelligently(raw_subtitle_segments, logger=logger)
    logger.info(f"Merged into {len(merged_segments)} segments for translation.")
    return merged_segments