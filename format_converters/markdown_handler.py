import logging
from .time_utils import format_time
from .book_schema import SubtitleTrack

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
    subtitle_track: SubtitleTrack,
    target_lang: str,
    logger: logging.Logger
):
    """
    从一个已翻译的 SubtitleTrack 对象重建一个简洁的、便于阅读的 Markdown 文件。
    """
    if not subtitle_track:
        logger.warning("没有提供 SubtitleTrack 对象，无法生成 Markdown。")
        return "# Translation Error\n\n[No SubtitleTrack object was provided to markdown generator.]"

    md_content = [f"# YouTube 视频翻译: {subtitle_track.video_id}\n"]
    md_content.append(f"**原始语言:** `{subtitle_track.source_lang}` (类型: `{subtitle_track.source_type}`)")
    md_content.append(f"**目标语言:** `{target_lang}`")
    md_content.append(f"\n---\n")
    
    if not subtitle_track.segments:
        logger.warning("SubtitleTrack 对象不包含任何片段。")
        md_content.append("\n**注意: 未找到任何字幕片段。**\n")
        return "\n".join(md_content)

    for i, segment in enumerate(subtitle_track.segments):
        start_time_str = format_time(segment.start)
        end_time_str = format_time(segment.end)
        
        md_content.append(f"### 片段 {i+1} (`{start_time_str}` --> `{end_time_str}`)\n")
        
        # 清理文本中的换行符，以获得更简洁的单行输出
        source_text_clean = segment.source_text.replace('\\n', ' ').strip()
        translated_text_clean = segment.translated_text.replace('\\n', ' ').strip()
        
        md_content.append(f"原文: {source_text_clean}")
        md_content.append(f"译文: {translated_text_clean}\n") # 在每个片段后添加一个换行符用于分隔
            
    return "\n".join(md_content)