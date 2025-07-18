# flake8: noqa
# Purpose: Expose key functions from the submodules to make them easily accessible
# at the package level, e.g., `from format_converters import srt_to_segments`.

from .time_utils import (
    format_time,
    srt_time_to_seconds,
    _normalize_timestamp_id,
    _parse_time_part
)

from .srt_handler import (
    segments_to_srt_string,
    srt_to_segments
)

from .markdown_handler import (
    reconstruct_translated_markdown,
    transcript_to_markdown
)

from .preprocessing import (
    merge_segments_intelligently,
    load_and_merge_srt_segments
)

from .postprocessing import (
    post_process_translated_segments,
    generate_post_processed_srt
)

# Initializes the format_converters module 