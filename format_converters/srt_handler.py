import logging
from pathlib import Path
from .time_utils import format_time, srt_time_to_seconds

def write_srt_file(subtitle_segments, output_path: Path):
    """
    Writes a list of subtitle segments to an SRT file.
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, sub in enumerate(subtitle_segments):
            start_time = format_time(sub['start'])
            end_time = format_time(sub['end'])
            # Use the 'translation' field for the text
            text = sub.get('translation', sub.get('text', ''))
            
            f.write(f"{i + 1}\n")
            f.write(f"{start_time} --> {end_time}\n")
            f.write(f"{text}\n\n")

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