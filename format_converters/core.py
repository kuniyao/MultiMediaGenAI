import logging
import re
from pathlib import Path
from common_utils.time_utils import format_time

# Placeholder for format conversion logic

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

def transcript_to_markdown(transcript_data, lang_code, source_type, video_id, logger=None):
    """Converts transcript data (list of dicts) to Markdown with timestamps."""
    logger_to_use = logger if logger else logging.getLogger(__name__)
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

def reconstruct_translated_srt(translated_json_segments, logger=None):
    """Reconstructs SRT from translated JSON objects containing original timestamps and translated texts."""
    logger_to_use = logger if logger else logging.getLogger(__name__)
    
    srt_content = []
    if not translated_json_segments:
        logger_to_use.warning("No translated segments provided to reconstruct_translated_srt.")
        return ""

    for i, item in enumerate(translated_json_segments):
        try:
            translated_text = item['translated_text']
            source_data = item['source_data']
            start_seconds = source_data['start_seconds']
            duration_seconds = source_data['duration_seconds']
            
            start_time_str = format_time(start_seconds)
            end_time_str = format_time(start_seconds + duration_seconds)
            
            srt_content.append(f"{i+1}\n{start_time_str} --> {end_time_str}\n{translated_text}\n")
        except KeyError as e:
            logger_to_use.error(f"Missing key {e} in translated_json_segment item {i}: {item}. Skipping segment.", exc_info=True)
            srt_content.append(f"{i+1}\nERROR --> ERROR\n[Segment data error: {e}]\n") # Add an error placeholder
        except TypeError as e:
            logger_to_use.error(f"Type error (likely None for source_data or time fields) in item {i}: {item}. Error: {e}. Skipping segment.", exc_info=True)
            srt_content.append(f"{i+1}\nERROR --> ERROR\n[Segment data type error: {e}]\n")
    return "\n".join(srt_content)

def reconstruct_translated_markdown(
    translated_json_segments,
    original_lang, 
    source_type, 
    target_lang="zh-CN", 
    video_id="", 
    logger=None
):
    """Reconstructs Markdown from translated JSON objects containing original timestamps and translated texts."""
    logger_to_use = logger if logger else logging.getLogger(__name__)

    if not translated_json_segments:
        logger_to_use.warning("No translated segments provided to reconstruct_translated_markdown.")
        # Return a header even if no segments
        md_content_header = [f"# YouTube Video Translation: {video_id}\n"]
        md_content_header.append(f"**Original Language:** {original_lang} ({source_type})")
        md_content_header.append(f"**Translated Language:** {target_lang}\n")
        md_content_header.append("[No translated segments found]")
        return "\n".join(md_content_header)

    md_content = [f"# YouTube Video Translation: {video_id}\n"]
    md_content.append(f"**Original Language:** {original_lang} ({source_type})")
    md_content.append(f"**Translated Language:** {target_lang}\n")
    
    for i, item in enumerate(translated_json_segments):
        try:
            translated_text = item['translated_text']
            source_data = item['source_data']
            start_seconds = source_data['start_seconds']
            duration_seconds = source_data['duration_seconds']

            start_time_str = format_time(start_seconds)
            end_time_str = format_time(start_seconds + duration_seconds)
            
            md_content.append(f"## {start_time_str} --> {end_time_str}\n{translated_text}\n")
        except KeyError as e:
            logger_to_use.error(f"Missing key {e} in translated_json_segment item {i} for Markdown: {item}. Skipping segment.", exc_info=True)
            md_content.append(f"## ERROR --> ERROR\n[Segment data error: {e}]\n") # Add an error placeholder
        except TypeError as e:
            logger_to_use.error(f"Type error (likely None for source_data or time fields) in item {i} for Markdown: {item}. Error: {e}. Skipping segment.", exc_info=True)
            md_content.append(f"## ERROR --> ERROR\n[Segment data type error: {e}]\n")
            
    return "\n".join(md_content)

def srt_time_to_seconds(time_str):
    """Converts SRT time format (HH:MM:SS,ms) to seconds."""
    parts = time_str.split(',')
    main_part = parts[0]
    ms = int(parts[1])
    h, m, s = map(int, main_part.split(':'))
    return h * 3600 + m * 60 + s + ms / 1000

def srt_to_segments(srt_file: Path):
    """Parses an SRT file and returns a list of subtitle segments."""
    content = srt_file.read_text(encoding='utf-8')
    content = content.replace('\r\n', '\n')
    subtitle_blocks = content.strip().split('\n\n')

    segments = []
    for block in subtitle_blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            try:
                # Expecting index, time, text
                time_line = lines[1]
                start_str, end_str = [t.strip() for t in time_line.split('-->')]
                text = "\n".join(lines[2:])

                segments.append({
                    "start": srt_time_to_seconds(start_str),
                    "end": srt_time_to_seconds(end_str),
                    "text": text
                })
            except (ValueError, IndexError) as e:
                logging.warning(f"Skipping malformed SRT block:\n{block}\nError: {e}")
                continue
    return segments

def format_subtitles(subtitle_segments, max_len=130, max_gap_seconds=1.5):
    """
    Formats subtitles by merging short, consecutive segments and cleaning up text.
    It will not merge segments if the time gap between them is too large.
    """
    if not subtitle_segments:
        return [], 0

    merged_subtitles = []
    buffer = []
    total_words = 0

    def flush_buffer():
        nonlocal total_words
        if not buffer:
            return
        
        start_time = buffer[0]['start']
        end_time = buffer[-1]['end']
        
        full_text = " ".join([sub['text'].replace('\n', ' ') for sub in buffer])
        
        total_words += len(re.findall(r'\w+', full_text))

        merged_subtitles.append({
            "start": start_time,
            "end": end_time,
            "text": full_text
        })
        buffer.clear()

    for sub in subtitle_segments:
        text = sub['text']
        
        if not buffer:
            buffer.append(sub)
            continue

        # Check conditions to flush BEFORE adding the new segment
        time_gap = sub['start'] - buffer[-1]['end']
        current_buffer_text = " ".join(s['text'] for s in buffer)
        
        # 1. Flush if time gap is too large
        if time_gap >= max_gap_seconds:
            flush_buffer()
            buffer.append(sub)
            continue
        
        # 2. Flush if adding the new text exceeds max length
        if len(current_buffer_text) + len(text) + 1 > max_len:
            flush_buffer()
            buffer.append(sub)
            continue

        # If all checks pass, add the segment to the buffer
        buffer.append(sub)

        # 3. Flush AFTER adding if the new segment completes a sentence
        if text.strip().endswith(('.', '?', '!', '。', '？', '！')):
            flush_buffer()
            
    flush_buffer()  # Flush any remaining subtitles

    return merged_subtitles, total_words

def post_process_segments(segments, max_chars_per_line=35, max_lines=2):
    """
    Post-processes translated segments using a hybrid re-timing approach.
    - Uses 'average' timing for dialogue splits to ensure stability.
    - Uses 'proportional' timing for punctuation splits for natural rhythm.
    """
    final_segments = []
    for seg in segments:
        final_segments.extend(_process_one_segment_hybrid(seg, max_chars_per_line, max_lines))
    return final_segments

def _process_one_segment_hybrid(segment, max_chars_per_line, max_lines):
    text = segment.get('translation', segment.get('text', '')).strip()
    start_time = segment['start']
    end_time = segment['end']
    duration = end_time - start_time

    if not text or duration <= 0:
        return [segment]

    # --- Stage 1: Dialogue Splitting (Macro - Averaging) ---
    dialogue_splitter = re.compile(r'\s*-\s*')
    dialogue_parts = [p.strip() for p in dialogue_splitter.split(text) if p.strip()]

    if len(dialogue_parts) > 1:
        # Re-add dialogue markers for all but the first part
        processed_dialogue_parts = [dialogue_parts[0]] + ['- ' + p for p in dialogue_parts[1:]]
        
        # Average timing for dialogue splits
        num_dialogue_parts = len(processed_dialogue_parts)
        avg_duration_per_dialogue = duration / num_dialogue_parts
        
        all_new_segments = []
        current_time = start_time
        
        for i, part_text in enumerate(processed_dialogue_parts):
            part_start_time = current_time
            part_end_time = current_time + avg_duration_per_dialogue
            
            # For each dialogue part, do a proportional split for punctuation
            inner_segments = _split_by_punctuation_proportional({
                'start': part_start_time,
                'end': part_end_time,
                'translation': part_text
            }, max_chars_per_line, max_lines)
            
            all_new_segments.extend(inner_segments)
            current_time = part_end_time
            
        # Ensure the very last segment ends exactly at the original end time
        if all_new_segments:
            all_new_segments[-1]['end'] = end_time

        return all_new_segments

    else:
        # No dialogue splits, just split by punctuation proportionally
        return _split_by_punctuation_proportional(segment, max_chars_per_line, max_lines)


def _split_by_punctuation_proportional(segment, max_chars_per_line, max_lines):
    text = segment.get('translation', segment.get('text', '')).strip()
    start_time = segment['start']
    end_time = segment['end']
    duration = end_time - start_time

    if not text or duration <= 0:
        return [_wrap_and_create_segment(text, start_time, end_time, max_chars_per_line, max_lines)]
    
    # Use only strong sentence-ending punctuation for time splitting.
    punc_splitter = re.compile(r'([。？！.])')
    text_fragments = []
    
    # Split by punctuation and keep the punctuation
    parts = punc_splitter.split(text)
    for i in range(0, len(parts), 2):
        fragment = "".join(parts[i:i+2]).strip()
        if fragment:
            text_fragments.append(fragment)
            
    if not text_fragments: # If no punctuation, treat as a single fragment
        return [_wrap_and_create_segment(text, start_time, end_time, max_chars_per_line, max_lines)]

    # Proportional timing
    total_len = sum(len(p) for p in text_fragments)
    if total_len == 0:
        return [_wrap_and_create_segment(text, start_time, end_time, max_chars_per_line, max_lines)]
        
    new_segments = []
    current_time = start_time
    for part_text in text_fragments:
        part_duration = (len(part_text) / total_len) * duration
        part_end_time = current_time + part_duration
        new_segments.append(_wrap_and_create_segment(part_text, current_time, part_end_time, max_chars_per_line, max_lines))
        current_time = part_end_time

    if new_segments:
        new_segments[-1]['end'] = end_time
        
    return new_segments

def _wrap_and_create_segment(text, start, end, max_chars, max_lines):
    wrapped_text = _wrap_text(text, max_chars, max_lines)
    return {'start': start, 'end': end, 'translation': wrapped_text}

def _wrap_text(text, max_chars_per_line, max_lines):
    """
    Wraps text to a specified line length and max number of lines.
    This is a simplified word-wrap logic, might need improvement for CJK.
    """
    if len(text) <= max_chars_per_line:
        return text

    # For CJK languages, simple character count is better than word splitting.
    # This is a simplified logic, a more advanced one would use NLP.
    lines = []
    current_text = text
    while len(current_text) > max_chars_per_line:
        # Find a suitable break point (punctuation or space) backwards from the max length
        break_pos = -1
        # Prefer breaking at major punctuation
        for punc in ['。', '？', '！', '，', '.', '?', '!', ',']:
            pos = current_text.rfind(punc, 0, max_chars_per_line)
            if pos != -1:
                break_pos = pos + 1
                break
        
        if break_pos == -1:
            # No punctuation found, just cut at the character limit
            break_pos = max_chars_per_line

        lines.append(current_text[:break_pos].strip())
        current_text = current_text[break_pos:].strip()

    if current_text:
        lines.append(current_text)

    # Enforce max_lines rule
    if len(lines) > max_lines:
        # Combine overflowing lines into the last allowed line
        final_line_text = " ".join(lines[max_lines-1:])
        lines = lines[:max_lines-1] + [final_line_text]
        # Rewrap the potentially long final line (one last chance)
        final_line_wrapped = [lines[-1][i:i+max_chars_per_line] for i in range(0, len(lines[-1]), max_chars_per_line)]
        lines[-1] = "\n".join(final_line_wrapped[:max_lines - len(lines) +1])


    return "\n".join(lines).strip() 