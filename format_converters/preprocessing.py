import re
import logging
import config
from dataclasses import dataclass, field

@dataclass
class _SegmentBuffer:
    """A buffer to hold segment data during the merging process."""
    text: str = ""
    start_char_offset: int = -1
    
    char_map_slice: list[float] = field(default_factory=list)

    def __post_init__(self):
        self.end_char_offset = self.start_char_offset + len(self.text) -1

    @property
    def is_empty(self) -> bool:
        return not self.text

    @property
    def start_time(self) -> float:
        return self.char_map_slice[0] if self.char_map_slice else 0.0

    @property
    def end_time(self) -> float:
        return self.char_map_slice[-1] if self.char_map_slice else 0.0

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    def append(self, text_part: str, char_map_slice_part: list[float]):
        if self.is_empty:
            self.start_char_offset = 0 # Assuming it starts from 0 initially
        
        self.text += text_part
        self.char_map_slice.extend(char_map_slice_part)
        self.end_char_offset += len(text_part)

    def split_at(self, split_index: int) -> tuple['_SegmentBuffer', '_SegmentBuffer']:
        """Splits the buffer at a given index and returns two new buffers."""
        text1 = self.text[:split_index].rstrip()
        text2 = self.text[split_index:].lstrip()

        # Adjust split index for char_map based on stripped text
        map_split_index = len(text1)

        buffer1 = _SegmentBuffer(
            text=text1,
            start_char_offset=self.start_char_offset,
            char_map_slice=self.char_map_slice[:map_split_index]
        )
        
        buffer2 = _SegmentBuffer(
            text=text2,
            start_char_offset=self.start_char_offset + map_split_index,
            char_map_slice=self.char_map_slice[map_split_index:]
        )
        return buffer1, buffer2

class IntelligentSegmentMerger:
    """
    Encapsulates the logic for merging raw transcript segments into
    semantically coherent sentences.
    """
    MAX_MERGED_SEGMENT_CHARS = 250
    MAX_MERGED_SEGMENT_DURATION = 15

    # Regex patterns for normalization and splitting
    _DECIMAL_PATTERN = re.compile(r'(\d)\.(\d)')
    _ABBREVIATION_PATTERN = re.compile(r'(Mr|Mrs|Miss|Ms|Dr|St)\.')
    _SPECIAL_PUNCTUATION_PATTERN = re.compile(r'\s*([.?!]{2,})')
    _CHINESE_PUNCTUATION_PATTERN = re.compile(r'。。+')
    # Updated to handle quotes after sentence-ending punctuation
    _SENTENCE_SPLIT_PATTERN = re.compile(r'(?<!<SPECIALPUNC>)([.?!])["\']?(?!<SPECIALPUNC>)(?=\s+|$)')

    # Prioritized list of delimiters for smart splitting
    _SMART_SPLIT_DELIMITERS = [',', ';', ':', ' and ', ' but ', ' or ', ' so ']

    # Normalization rules, making it easy to add more.
    # The order matters: protect decimals first.
    _NORMALIZATION_RULES = [
        (_DECIMAL_PATTERN, r'\1<DECIMAL_DOT>\2'),
        (_CHINESE_PUNCTUATION_PATTERN, '...'),
        (_ABBREVIATION_PATTERN, r'\1<PERIOD>'),
        (_SPECIAL_PUNCTUATION_PATTERN, r'<SPECIALPUNC>\1<SPECIALPUNC>')
    ]

    def __init__(self, transcript_segments, logger, max_chars=250, max_duration=15):
        self.transcript_segments = transcript_segments
        self.logger = logger
        self.full_text = ""
        self.char_map = []
        self.max_chars = max_chars
        self.max_duration = max_duration

    def merge(self):
        """
        Executes the merging process.
        """
        self._prepare_text_and_char_map()
        if not self.full_text:
            return []

        sentences = self._split_text_into_sentences()
        final_segments = self._build_merged_segments(sentences)

        return final_segments

    def _prepare_text_and_char_map(self):
        """
        Combines all text from segments and creates a character-to-timestamp map.
        """
        last_time = 0.0
        for segment in self.transcript_segments:
            is_dict = isinstance(segment, dict)
            text = (segment.get('text', '') if is_dict else getattr(segment, 'text', '')).strip()
            start = segment.get('start', last_time) if is_dict else getattr(segment, 'start', last_time)

            if not is_dict and hasattr(segment, 'duration'):
                duration = segment.duration
            elif is_dict and 'duration' in segment:
                duration = segment['duration']
            else: # Fallback for local files that might be missing duration
                end = segment.get('end', start) if is_dict else getattr(segment, 'end', start)
                duration = end - start

            end_time = start + duration
            last_time = end_time

            if not text:
                continue

            self.full_text += text + " "

            if len(text) > 0:
                time_per_char = duration / len(text)
                for i in range(len(text)):
                    self.char_map.append(start + i * time_per_char)
                self.char_map.append(end_time)

        self.full_text = self.full_text.strip()

    def _split_text_into_sentences(self):
        """
        Normalizes and splits the full text into sentences using regex.
        """
        normalized_text = self.full_text
        for pattern, replacement in self._NORMALIZATION_RULES:
            normalized_text = pattern.sub(replacement, normalized_text)

        return self._SENTENCE_SPLIT_PATTERN.split(normalized_text)

    def _find_best_split_point(self, text: str) -> int:
        """Finds the best point to split a long text segment."""
        split_point = self.max_chars
        
        # Try to split by prioritized delimiters first
        for delimiter in self._SMART_SPLIT_DELIMITERS:
            pos = text.rfind(delimiter, 0, split_point)
            if pos != -1:
                # Split after the delimiter
                return pos + len(delimiter)
        
        # Fallback to the last space
        last_space = text.rfind(' ', 0, split_point)
        if last_space != -1:
            return last_space + 1

        # If no good split point is found, force split at max_chars
        return split_point

    def _build_merged_segments(self, sentences):
        """
        Reconstructs final segments from sentences using a buffer and smart splitting.
        """
        final_segments = []
        current_buffer = _SegmentBuffer()
        char_offset = 0

        def _add_segment_from_buffer(buffer: _SegmentBuffer):
            if buffer.is_empty:
                return
            
            text = buffer.text.strip().replace('<PERIOD>', '.').replace('<DECIMAL_DOT>', '.')
            text = text.replace('<SPECIALPUNC>', '')

            if not text:
                return

            final_segments.append({
                'text': text,
                'start': buffer.start_time,
                'end': buffer.end_time,
                'duration': buffer.duration
            })
            self.logger.debug(f"Added segment: '{text[:50]}...' (Chars: {len(text)}, Time: {buffer.start_time:.2f}-{buffer.end_time:.2f})")

        for part in sentences:
            if not part:
                continue
            
            part_len = len(part)
            part_char_map_slice = self.char_map[char_offset : char_offset + part_len]
            current_buffer.append(part, part_char_map_slice)
            char_offset += part_len

            # Smart splitting for long buffers
            while len(current_buffer.text) > self.max_chars or current_buffer.duration > self.max_duration:
                split_point = self._find_best_split_point(current_buffer.text)
                
                # Avoid infinite loops if a single part is too long
                if split_point == 0 or split_point >= len(current_buffer.text):
                     break

                buffer_to_add, remaining_buffer = current_buffer.split_at(split_point)
                _add_segment_from_buffer(buffer_to_add)
                current_buffer = remaining_buffer

            # Check if the part ends a sentence
            if part.strip() and part.strip()[-1] in ".?!":
                 _add_segment_from_buffer(current_buffer)
                 current_buffer = _SegmentBuffer()

        # Add any remaining text in the buffer
        _add_segment_from_buffer(current_buffer)

        return final_segments

def merge_segments_intelligently(transcript_segments, logger=None):
    """
    Merges raw transcript segments into semantically coherent sentences
    using regex-based intelligent splitting.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    if not transcript_segments:
        return []

    merger = IntelligentSegmentMerger(transcript_segments, logger_to_use)
    return merger.merge()

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
