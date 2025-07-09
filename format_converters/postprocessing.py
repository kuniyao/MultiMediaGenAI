import re
from .srt_handler import segments_to_srt_string
from .book_schema import SubtitleTrack, SubtitleSegment
from typing import List
import logging

class SubtitlePostProcessor:
    """
    Encapsulates the logic for post-processing translated subtitle segments.
    This includes splitting by dialogue/punctuation and re-wrapping text.
    """
    # Pre-compiled regex patterns for efficiency
    _DIALOGUE_SPLITTER_PATTERN = re.compile(r'\s*-\s*')
    _PUNCTUATION_SPLITTER_PATTERN = re.compile(r'([。？！.])')
    _DECIMAL_PATTERN = re.compile(r'(\d)\.(\d)')
    
    # List of punctuation to prefer breaking on for line wrapping
    _WRAP_BREAK_PUNCTUATION = ['。', '？', '！', '，', '.', '?', '!', ',']

    # Placeholders for protecting text during splitting
    _PLACEHOLDERS = {
        "DECIMAL_DOT": "<DECIMAL_DOT>"
    }

    def __init__(self, max_chars_per_line=35, max_lines=2, logger=None):
        self.max_chars_per_line = max_chars_per_line
        self.max_lines = max_lines
        self.logger = logger if logger else logging.getLogger(__name__)

    def process(self, segments: List[SubtitleSegment]) -> List[dict]:
        """Processes a list of SubtitleSegment objects."""
        final_segments = []
        for seg in segments:
            final_segments.extend(self._process_one_segment(seg))
        return final_segments

    def _protect_text(self, text: str) -> str:
        """Protects patterns in text from being split."""
        text = self._DECIMAL_PATTERN.sub(
            rf'\1{self._PLACEHOLDERS["DECIMAL_DOT"]}\2', text
        )
        return text

    def _restore_text(self, text: str) -> str:
        """Restores protected patterns in text."""
        for key, placeholder in self._PLACEHOLDERS.items():
            original = '.' if key == "DECIMAL_DOT" else '' # Add more logic if other placeholders are added
            text = text.replace(placeholder, original)
        return text

    def _process_one_segment(self, segment: SubtitleSegment) -> List[dict]:
        """
        Processes a single segment, handling dialogue and punctuation splitting.
        This is a hybrid approach using average and proportional timing.
        """
        text = self._protect_text(segment.translated_text.strip())
        start_time = segment.start
        end_time = segment.end
        duration = end_time - start_time

        if not text or duration <= 0:
            return [{'start': start_time, 'end': end_time, 'text': text}]

        # --- Stage 1: Dialogue Splitting (Macro - Averaging) ---
        dialogue_parts = [p.strip() for p in self._DIALOGUE_SPLITTER_PATTERN.split(text) if p.strip()]

        if len(dialogue_parts) > 1:
            processed_dialogue_parts = [dialogue_parts[0]] + ['- ' + p for p in dialogue_parts[1:]]
            
            num_dialogue_parts = len(processed_dialogue_parts)
            avg_duration_per_dialogue = duration / num_dialogue_parts
            
            all_new_segments = []
            current_time = start_time
            
            for i, part_text in enumerate(processed_dialogue_parts):
                part_start_time = current_time
                part_end_time = current_time + avg_duration_per_dialogue
                
                temp_segment_for_split = {
                    'start': part_start_time,
                    'end': part_end_time,
                    'text': part_text
                }
                inner_segments = self._split_by_punctuation(temp_segment_for_split)
                
                all_new_segments.extend(inner_segments)
                current_time = part_end_time
                
            if all_new_segments:
                all_new_segments[-1]['end'] = end_time

            return all_new_segments
        else:
            temp_segment_for_split = {
                'start': start_time,
                'end': end_time,
                'text': text
            }
            return self._split_by_punctuation(temp_segment_for_split)

    def _split_by_punctuation(self, segment: dict) -> List[dict]:
        """
        Splits a segment by punctuation and then by line limits,
        proportionally distributing time at each split level.
        """
        # Note: Text coming into this function is already protected.
        text = segment.get('text', '').strip()
        start_time = segment['start']
        end_time = segment['end']
        duration = end_time - start_time

        if not text or duration <= 0:
            return self._create_segment_from_chunk(text, start_time, end_time)

        # --- Level 1 Split: By Punctuation ---
        text_fragments = []
        parts = self._PUNCTUATION_SPLITTER_PATTERN.split(text)
        for i in range(0, len(parts), 2):
            fragment = "".join(parts[i:i+2]).strip()
            if fragment:
                text_fragments.append(fragment)

        if not text_fragments:
            return self._create_segment_from_chunk(text, start_time, end_time)

        total_len = sum(len(p) for p in text_fragments)
        if total_len == 0:
            return self._create_segment_from_chunk(text, start_time, end_time)

        final_segments = []
        current_time = start_time
        
        for fragment_text in text_fragments:
            fragment_duration = (len(fragment_text) / total_len) * duration if total_len > 0 else 0
            fragment_end_time = current_time + fragment_duration

            # --- Level 2 Split: By Line Limit ---
            text_chunks = self._chunk_text_by_line_limit(fragment_text)
            
            if len(text_chunks) <= 1:
                # No overflow, create a single segment
                final_segments.extend(self._create_segment_from_chunk(fragment_text, current_time, fragment_end_time))
            else:
                # Overflow occurred, re-distribute fragment's duration among chunks
                total_chunk_len = sum(len(c) for c in text_chunks)
                chunk_current_time = current_time
                for chunk_text in text_chunks:
                    chunk_duration = (len(chunk_text) / total_chunk_len) * fragment_duration if total_chunk_len > 0 else 0
                    chunk_end_time = chunk_current_time + chunk_duration
                    final_segments.extend(self._create_segment_from_chunk(chunk_text, chunk_current_time, chunk_end_time))
                    chunk_current_time = chunk_end_time
            
            current_time = fragment_end_time

        if final_segments:
            final_segments[-1]['end'] = end_time

        return final_segments

    def _create_segment_from_chunk(self, text: str, start: float, end: float) -> List[dict]:
        """Creates a final segment dictionary from a text chunk."""
        restored_text = self._restore_text(text)
        # This function now returns a list, though it's a list of one
        return [{'start': start, 'end': end, 'text': restored_text.strip()}]

    def _chunk_text_by_line_limit(self, text: str) -> List[str]:
        """
        Wraps text and chunks it into parts that respect the max_lines limit.
        Each part in the returned list is a string, potentially with internal newlines.
        """
        if not text:
            return []

        # First, wrap the entire text without regard to max_lines yet
        all_lines = []
        current_text = text
        while len(current_text) > self.max_chars_per_line:
            break_pos = -1
            for punc in self._WRAP_BREAK_PUNCTUATION:
                pos = current_text.rfind(punc, 0, self.max_chars_per_line)
                if pos != -1:
                    break_pos = pos + 1
                    break
            
            if break_pos == -1:
                break_pos = self.max_chars_per_line

            all_lines.append(current_text[:break_pos].strip())
            current_text = current_text[break_pos:].strip()

        if current_text:
            all_lines.append(current_text)

        # Now, chunk the wrapped lines into groups of max_lines
        final_chunks = []
        for i in range(0, len(all_lines), self.max_lines):
            chunk_lines = all_lines[i:i + self.max_lines]
            final_chunks.append("\n".join(chunk_lines))
            
        return final_chunks

def post_process_translated_segments(segments: List[SubtitleSegment], max_chars_per_line=35, max_lines=2) -> List[dict]:
    """
    Post-processes translated segments using a dedicated processor class.
    """
    processor = SubtitlePostProcessor(max_chars_per_line=max_chars_per_line, max_lines=max_lines)
    return processor.process(segments)

def generate_post_processed_srt(subtitle_track: SubtitleTrack, logger: logging.Logger):
    """
    Takes a translated SubtitleTrack object, post-processes its segments for 
    optimal SRT formatting, and returns the final SRT content as a string.

    Args:
        subtitle_track (SubtitleTrack): The track object containing translated segments.
        logger: A logger instance.

    Returns:
        str: The fully processed SRT content.
    """
    if not subtitle_track.segments:
        logger.warning("Subtitle track contains no segments. Returning empty SRT content.")
        return ""
        
    # 1. Run the main post-processing logic
    logger.info("Post-processing translated segments for optimal formatting...")
    # The segments from the track are passed to the processor
    final_segments_as_dicts = post_process_translated_segments(subtitle_track.segments)

    # 2. Generate the final SRT string
    logger.info("Generating SRT content from final segments...")
    # srt_handler expects a list of dictionaries with 'start', 'end', and 'text' keys
    translated_srt_content = segments_to_srt_string(final_segments_as_dicts)
    
    return translated_srt_content 