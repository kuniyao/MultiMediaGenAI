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
    char_offset = 0
    current_sentence = ""

    for part in sentences:
        if not part.strip():
            continue

        current_sentence += part
        stripped_part = part.strip()
        
        # Check if the part is a delimiter, which means the sentence is complete
        if (len(stripped_part) == 1 and stripped_part in '.?!') or part is sentences[-1]:
            sentence_text = current_sentence.strip()
            sentence_text = sentence_text.replace('<PERIOD>', '.')
            sentence_text = sentence_text.replace('<SPECIALPUNC>', '')

            if not sentence_text:
                char_offset += len(current_sentence)
                current_sentence = ""
                continue

            start_char_index = full_text.find(sentence_text, char_offset - len(sentence_text) if char_offset > 0 else 0)
            if start_char_index == -1:
                start_char_index = char_offset

            end_char_index = start_char_index + len(sentence_text) - 1

            start_time = char_map[min(start_char_index, len(char_map) - 1)]
            end_time = char_map[min(end_char_index, len(char_map) - 1)]

            final_segments.append({
                'text': sentence_text,
                'start': start_time,
                'end': end_time,
                'duration': end_time - start_time
            })
            
            char_offset += len(current_sentence)
            current_sentence = ""

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
