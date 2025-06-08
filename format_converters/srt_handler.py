import logging
from pathlib import Path
from .time_utils import format_time, srt_time_to_seconds

def segments_to_srt_string(subtitle_segments):
    """
    Converts a list of subtitle segments into a single SRT formatted string.
    
    The input segments should be a list of dictionaries, where each dictionary
    has 'start', 'end', and 'translation' (or 'text') keys.
    """
    srt_blocks = []
    for i, sub in enumerate(subtitle_segments):
        try:
            start_time = format_time(sub['start'])
            end_time = format_time(sub['end'])
            # Use the 'translation' field first, fallback to 'text'
            text = sub.get('translation', sub.get('text', ''))
            
            block = f"{i + 1}\n{start_time} --> {end_time}\n{text}"
            srt_blocks.append(block)
        except KeyError as e:
            # Log or handle the error for the problematic segment
            logging.error(f"Skipping segment due to missing key {e}: {sub}")
            continue
    
    # Join all blocks with double newlines, and add a final newline for file standards
    return "\n\n".join(srt_blocks) + "\n"

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