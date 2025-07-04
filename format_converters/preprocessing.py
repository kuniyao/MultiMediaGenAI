import re
import logging
import config

def merge_segments_intelligently(transcript_segments, logger=None):
    """
    Merges raw transcript segments into semantically coherent sentences
    using regex-based intelligent splitting.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    if not transcript_segments:
        return []

    # 1. Combine all text and create a character-to-timestamp map
    full_text = ""
    char_map = []
    last_time = 0.0

    for segment in transcript_segments:
        is_dict = isinstance(segment, dict)
        text = (segment.get('text', '') if is_dict else getattr(segment, 'text', '')).strip()
        start = segment.get('start', last_time) if is_dict else getattr(segment, 'start', last_time)
        
        # For YouTube transcripts, duration is a property, not in the dict
        if not is_dict and hasattr(segment, 'duration'):
            duration = segment.duration
            end = start + duration
        elif is_dict and 'duration' in segment:
            duration = segment['duration']
            end = start + duration
        else: # Fallback for local files that might be missing duration
            end = segment.get('end', start) if is_dict else getattr(segment, 'end', start)
            duration = end - start

        last_time = start + duration

        if not text:
            continue

        full_text += text + " "
        
        if len(text) > 0:
            time_per_char = duration / len(text)
            for i in range(len(text)):
                char_map.append(start + i * time_per_char)
            char_map.append(end)

    full_text = full_text.strip()
    if not full_text:
        return []

    # 2. Normalize text for better splitting
    normalized_text = re.sub(r'。。+', '...', full_text)
    normalized_text = re.sub(r'(Mr|Mrs|Ms|Dr|St)\.', r'\1<PERIOD>', normalized_text)
    normalized_text = re.sub(r'\s*([.?!]{2,})', r'<SPECIALPUNC>\1<SPECIALPUNC>', normalized_text)

    # 3. Split the text into sentences using a robust regex
    sentences = re.split(r'(?<!<SPECIALPUNC>)([.?!])(?!<SPECIALPUNC>)(?=\s+|$)', normalized_text)

    # 4. Reconstruct segments from the split sentences
    final_segments = []
    current_char_offset_in_full_text = 0
    current_sentence_buffer = ""

    # Define a maximum character limit for a merged segment
    MAX_MERGED_SEGMENT_CHARS = 250 # Adjust this value as needed
    MAX_MERGED_SEGMENT_DURATION = 15 # Max duration in seconds for a merged segment

    def _add_final_segment(text_to_add, start_char_idx, end_char_idx):
        sentence_text = text_to_add.strip()
        sentence_text = sentence_text.replace('<PERIOD>', '.')
        sentence_text = sentence_text.replace('<SPECIALPUNC>', '')

        if not sentence_text:
            return

        # Ensure indices are within bounds of char_map
        start_time = char_map[min(start_char_idx, len(char_map) - 1)] if char_map else 0.0
        end_time = char_map[min(end_char_idx, len(char_map) - 1)] if char_map else 0.0

        final_segments.append({
            'text': sentence_text,
            'start': start_time,
            'end': end_time,
            'duration': end_time - start_time
        })
        logger_to_use.debug(f"Added segment: '{sentence_text[:50]}...' (Chars: {start_char_idx}-{end_char_idx}, Time: {start_time:.2f}-{end_time:.2f})")

    for i, part in enumerate(sentences):
        if not part.strip():
            continue

        current_sentence_buffer += part
        stripped_part = part.strip()
        
        # Determine if a segment should be created
        # Condition 1: End of a natural sentence (based on punctuation)
        # Condition 2: End of the last part in the entire text
        is_natural_sentence_end = (len(stripped_part) == 1 and stripped_part in '.?!')
        is_last_part = (i == len(sentences) - 1)

        # Force split if buffer is too long or too long in duration
        buffer_len = len(current_sentence_buffer)
        if buffer_len > 0:
            start_idx = min(current_char_offset_in_full_text, len(char_map) - 1)
            end_idx = min(current_char_offset_in_full_text + buffer_len - 1, len(char_map) - 1)
            buffer_duration = char_map[end_idx] - char_map[start_idx]
        else:
            buffer_duration = 0

        while buffer_len >= MAX_MERGED_SEGMENT_CHARS or buffer_duration > MAX_MERGED_SEGMENT_DURATION:
            # Find a practical split point
            # Default to the max character limit
            split_point = MAX_MERGED_SEGMENT_CHARS

            # Try to find a space before the character limit to avoid splitting words
            last_space = current_sentence_buffer.rfind(' ', 0, split_point)
            if last_space != -1:
                split_point = last_space
            
            # If the segment is still too long (no space found), force split
            segment_text = current_sentence_buffer[:split_point].strip()
            
            if not segment_text: # Avoid creating empty segments
                break

            # Calculate character indices for this forced segment
            segment_start_char_idx = current_char_offset_in_full_text
            segment_end_char_idx = segment_start_char_idx + len(segment_text) - 1
            
            _add_final_segment(segment_text, segment_start_char_idx, segment_end_char_idx)
            
            # Update buffer and offsets for the next loop iteration
            current_sentence_buffer = current_sentence_buffer[split_point:].strip()
            current_char_offset_in_full_text += len(segment_text) + (len(current_sentence_buffer) - len(current_sentence_buffer.lstrip())) # Account for removed text and leading spaces

            # Recalculate length and duration for the while condition
            buffer_len = len(current_sentence_buffer)
            if buffer_len > 0:
                start_idx = min(current_char_offset_in_full_text, len(char_map) - 1)
                end_idx = min(current_char_offset_in_full_text + buffer_len - 1, len(char_map) - 1)
                buffer_duration = char_map[end_idx] - char_map[start_idx]
            else:
                buffer_duration = 0

        # If it's a natural sentence end or the last part, add the remaining buffer as a segment
        if is_natural_sentence_end or is_last_part:
            if current_sentence_buffer:
                segment_start_char_idx = current_char_offset_in_full_text
                segment_end_char_idx = segment_start_char_idx + len(current_sentence_buffer) - 1
                _add_final_segment(current_sentence_buffer, segment_start_char_idx, segment_end_char_idx)
                current_char_offset_in_full_text = segment_end_char_idx + 1
                current_sentence_buffer = ""

    return final_segments

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
    from .srt_handler import srt_to_segments
    
    logger.info(f"Reading and formatting SRT file: {file_path}")
    raw_subtitle_segments = srt_to_segments(file_path)
    if not raw_subtitle_segments:
        logger.error("No segments found in the SRT file. Aborting.")
        return None
        
    logger.info(f"Loaded {len(raw_subtitle_segments)} raw segments from SRT file.")

    merged_segments = merge_segments_intelligently(raw_subtitle_segments, logger=logger)
    logger.info(f"Merged into {len(merged_segments)} segments for translation.")
    return merged_segments
