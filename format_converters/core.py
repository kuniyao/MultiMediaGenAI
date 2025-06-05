import logging

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