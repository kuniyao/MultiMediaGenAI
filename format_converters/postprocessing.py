import re

def post_process_translated_segments(segments, max_chars_per_line=35, max_lines=2):
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