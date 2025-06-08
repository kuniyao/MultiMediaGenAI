import logging
from .time_utils import format_time

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