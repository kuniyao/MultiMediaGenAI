import re

def merge_consecutive_segments(subtitle_segments, max_len=130, max_gap_seconds=1.5):
    """
    Merges short, consecutive subtitle segments to create more contextually complete chunks for translation.
    It will not merge segments if the time gap between them is too large or if it exceeds a max length.
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